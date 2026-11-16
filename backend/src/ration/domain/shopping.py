"""Turn a plan into something you can carry round a shop.

The pipeline, in order:

    plan entries
      -> cooked grams, scaled by portion_factor
      -> divided by yield_factor            -> raw grams
      -> merged by ingredient id
      -> rounded up to whole packages
      -> grouped by shop section

The step that is *not* there is the important one. ``batch_portions`` is never
applied. A lunch cooked once for three days appears in the plan as three
entries, one per day, and each is one portion. Multiplying by batch_portions as
well would triple-count it, and the resulting list would be wrong in a way that
looks plausible — the failure mode this module exists to avoid.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

from ration.domain.types import Catalog, Ingredient, Plan

_ONE_DECIMAL = Decimal("0.1")


@dataclass(frozen=True, slots=True)
class ShoppingLine:
    """One ingredient to buy.

    ``needed_raw_g`` is what the plan actually consumes. ``purchase_amount`` is
    what you end up with after rounding to whole packages, and ``overage_g`` is
    the difference — shown so the planner can see that 94 g of whey protein means
    buying a tub, rather than wondering why the number looks odd.
    """

    ingredient_id: str
    name: str
    shop_section: str
    needed_raw_g: Decimal
    purchase_amount: Decimal
    overage_g: Decimal
    packages: int | None = None
    package_unit: str | None = None
    size_is_critical: bool = False
    is_staple: bool = False


def shopping_list(plan: Plan, catalog: Catalog, locale: str = "ru") -> tuple[ShoppingLine, ...]:
    """Everything the plan needs, in raw weights, grouped by shop section.

    The single entry point, and the composition of the five stages below. It
    exists separately from them because a caller that only wants a shopping
    list should not have to know the pipeline — and because the golden test
    (`tests/unit/test_golden_shopping.py`) calls this and nothing else.

    The stages are public so the API can time each one as its own span without
    the engine knowing anything about telemetry (HLD §4, §7, AD-1). Composing
    them by hand must produce exactly this; a test asserts it.
    """
    cooked = expand_entries(plan, catalog)
    raw = convert_to_raw(cooked)
    merged = merge_by_ingredient(raw)
    lines = round_to_packages(merged, catalog, locale)
    return group_by_shop_section(lines)


@dataclass(frozen=True, slots=True)
class CookedDemand:
    """One module line, scaled to one plan entry, still in cooked grams."""

    ingredient_id: str
    grams_cooked: Decimal
    yield_factor: Decimal
    size_is_critical: bool


@dataclass(frozen=True, slots=True)
class RawDemand:
    """The same line after the yield conversion: what has to be bought for it."""

    ingredient_id: str
    grams_raw: Decimal
    size_is_critical: bool


def expand_entries(plan: Plan, catalog: Catalog) -> tuple[CookedDemand, ...]:
    """Every entry in the plan, flattened to module lines in cooked grams.

    ``batch_portions`` is deliberately absent. A lunch cooked once for three
    days appears as three entries, one per day, and each is one portion;
    multiplying by the batch size as well would triple-count it (PRD §6.4).

    The yield factor is resolved here rather than at the conversion, because a
    line may override the ingredient's own (D4) and the override belongs to the
    line that is being expanded.
    """
    return tuple(
        CookedDemand(
            ingredient_id=line.ingredient_id,
            grams_cooked=line.grams_cooked * entry.portion_factor,
            yield_factor=line.yield_factor_override
            or catalog.ingredient(line.ingredient_id).yield_factor,
            size_is_critical=line.size_is_critical,
        )
        for entry in plan.all_entries
        for line in catalog.module(entry.module_id).lines
    )


def convert_to_raw(cooked: tuple[CookedDemand, ...]) -> tuple[RawDemand, ...]:
    """Cooked grams to raw grams, the one place yield is applied (AD-3)."""
    return tuple(
        RawDemand(
            ingredient_id=demand.ingredient_id,
            grams_raw=demand.grams_cooked / demand.yield_factor,
            size_is_critical=demand.size_is_critical,
        )
        for demand in cooked
    )


def merge_by_ingredient(raw: tuple[RawDemand, ...]) -> tuple[RawDemand, ...]:
    """Sum raw grams per ingredient, in order of first appearance.

    Merging is by ingredient id, never by name — aliases are resolved when an
    ingredient is entered, not here (PRD §6.3).
    """
    totals: dict[str, Decimal] = defaultdict(Decimal)
    critical: set[str] = set()
    for demand in raw:
        totals[demand.ingredient_id] += demand.grams_raw
        if demand.size_is_critical:
            critical.add(demand.ingredient_id)
    return tuple(
        RawDemand(ingredient_id, grams, ingredient_id in critical)
        for ingredient_id, grams in totals.items()
    )


def round_to_packages(
    merged: tuple[RawDemand, ...], catalog: Catalog, locale: str = "ru"
) -> tuple[ShoppingLine, ...]:
    """Round each need up to whole packages and name it for the shop."""
    return tuple(
        _to_line(
            catalog.ingredient(demand.ingredient_id),
            demand.grams_raw,
            demand.size_is_critical,
            locale,
        )
        for demand in merged
    )


def group_by_shop_section(lines: tuple[ShoppingLine, ...]) -> tuple[ShoppingLine, ...]:
    """Arrange the list the way the shop is: by section, then by name.

    A stable sort, so two lines in the same section with the same name keep the
    order the plan put them in.
    """
    return tuple(sorted(lines, key=lambda line: (line.shop_section, line.name)))


def _to_line(
    ingredient: Ingredient, raw_grams: Decimal, size_is_critical: bool, locale: str
) -> ShoppingLine:
    needed = raw_grams.quantize(_ONE_DECIMAL, rounding=ROUND_HALF_UP)

    if ingredient.package_size is None:
        packages, purchase = None, needed
    else:
        packages = int(
            (raw_grams / ingredient.package_size).quantize(Decimal(1), rounding=ROUND_CEILING)
        )
        purchase = (ingredient.package_size * packages).quantize(
            _ONE_DECIMAL, rounding=ROUND_HALF_UP
        )

    return ShoppingLine(
        ingredient_id=ingredient.id,
        name=ingredient.name(locale),
        shop_section=ingredient.shop_section,
        needed_raw_g=needed,
        purchase_amount=purchase,
        overage_g=purchase - needed,
        packages=packages,
        package_unit=ingredient.package_unit,
        size_is_critical=size_is_critical,
        is_staple=ingredient.is_staple,
    )


def group_by_section(
    lines: tuple[ShoppingLine, ...],
) -> dict[str, tuple[ShoppingLine, ...]]:
    """The same lines arranged the way the shop is, for display."""
    grouped: dict[str, list[ShoppingLine]] = defaultdict(list)
    for line in lines:
        grouped[line.shop_section].append(line)
    return {section: tuple(items) for section, items in grouped.items()}
