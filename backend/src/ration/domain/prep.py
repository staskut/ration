"""Batch cook sessions: what to cook at once, and how to divide it.

A module with ``batch_portions > 1`` is cooked once and eaten over several days.
The plan says which days; this says what to buy for that session and how much
goes in each container.

Quantities here are **raw**, because a cook session is a shopping-and-cooking
instruction. The per-container breakdown is in cooked grams, because that is
what gets weighed when packing.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from ration.domain.types import Catalog, Plan

_ONE_DECIMAL = Decimal("0.1")


@dataclass(frozen=True, slots=True)
class CookSessionItem:
    ingredient_id: str
    name: str
    grams_raw: Decimal
    grams_cooked_per_portion: Decimal


@dataclass(frozen=True, slots=True)
class CookSession:
    module_id: str
    module_name: str
    portions: int
    day_indexes: tuple[int, ...]
    items: tuple[CookSessionItem, ...]
    prep_notes: str | None = None


def prep_plan(plan: Plan, catalog: Catalog, locale: str = "ru") -> tuple[CookSession, ...]:
    """One session per batch module, in the order its first day falls.

    Portions come from how many times the module is actually planned, not from
    ``batch_portions``. Cooking ahead and eating less is a choice, and a session
    that says "cook three" when two are planned would waste food.
    """
    appearances: dict[str, list[int]] = defaultdict(list)
    factors: dict[str, list[Decimal]] = defaultdict(list)

    for day in plan.days:
        for entry in day.entries:
            module = catalog.module(entry.module_id)
            if module.batch_portions > 1:
                appearances[entry.module_id].append(day.day_index)
                factors[entry.module_id].append(entry.portion_factor)

    sessions = []
    for module_id, days in appearances.items():
        module = catalog.module(module_id)
        total_factor = sum(factors[module_id], Decimal(0))

        items = []
        for line in module.lines:
            ingredient = catalog.ingredient(line.ingredient_id)
            yield_factor = line.yield_factor_override or ingredient.yield_factor
            cooked_total = line.grams_cooked * total_factor
            items.append(
                CookSessionItem(
                    ingredient_id=line.ingredient_id,
                    name=ingredient.name(locale),
                    grams_raw=(cooked_total / yield_factor).quantize(
                        _ONE_DECIMAL, rounding=ROUND_HALF_UP
                    ),
                    grams_cooked_per_portion=line.grams_cooked.quantize(
                        _ONE_DECIMAL, rounding=ROUND_HALF_UP
                    ),
                )
            )

        sessions.append(
            CookSession(
                module_id=module_id,
                module_name=module.name,
                portions=len(days),
                day_indexes=tuple(sorted(days)),
                items=tuple(items),
                prep_notes=module.prep_notes,
            )
        )

    return tuple(sorted(sessions, key=lambda s: s.day_indexes[0]))
