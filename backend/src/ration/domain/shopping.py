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
    """Everything the plan needs, in raw weights, grouped by shop section."""
    needed, critical = _accumulate_raw_grams(plan, catalog)
    lines = [
        _to_line(catalog.ingredient(ingredient_id), raw_grams, ingredient_id in critical, locale)
        for ingredient_id, raw_grams in needed.items()
    ]
    return tuple(sorted(lines, key=lambda line: (line.shop_section, line.name)))


def _accumulate_raw_grams(plan: Plan, catalog: Catalog) -> tuple[dict[str, Decimal], set[str]]:
    """Sum raw grams per ingredient across the whole plan.

    Merging is by ingredient id, never by name — aliases are resolved when an
    ingredient is entered, not here (PRD 6.3).
    """
    needed: dict[str, Decimal] = defaultdict(Decimal)
    critical: set[str] = set()

    for entry in plan.all_entries:
        module = catalog.module(entry.module_id)
        for line in module.lines:
            ingredient = catalog.ingredient(line.ingredient_id)
            cooked = line.grams_cooked * entry.portion_factor
            # A line may override the ingredient's yield when its preparation
            # differs — raw pepper against roasted pepper, for example.
            yield_factor = line.yield_factor_override or ingredient.yield_factor
            needed[line.ingredient_id] += cooked / yield_factor
            if line.size_is_critical:
                critical.add(line.ingredient_id)

    return dict(needed), critical


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
