"""Calories and protein, from one ingredient line up to a whole day.

Totals compose upwards: line → module → entry → slot → day. Each level sums the
level below, so a slot holding a protein module and a side module reports their
sum — which is what budgets and validation are compared against (PRD 3.6).

Rounding happens only when a total is handed out, never between steps. Rounding
intermediate values and then summing them is how a day's calories end up tens
off the sum of its parts.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal

from ration.domain.types import (
    HUNDRED_GRAMS,
    ZERO_TOTALS,
    Catalog,
    Module,
    ModuleLine,
    PlanDay,
    PlanEntry,
    Slot,
    Totals,
)

_ONE_DECIMAL = Decimal("0.1")


def round_totals(totals: Totals) -> Totals:
    """Round to one decimal place, half-up. Applied at the boundary only."""
    return Totals(
        kcal=totals.kcal.quantize(_ONE_DECIMAL, rounding=ROUND_HALF_UP),
        protein_g=totals.protein_g.quantize(_ONE_DECIMAL, rounding=ROUND_HALF_UP),
    )


def line_totals(line: ModuleLine, catalog: Catalog) -> Totals:
    """Nutrition for one ingredient line, from its cooked weight."""
    ingredient = catalog.ingredient(line.ingredient_id)
    hundreds = line.grams_cooked / HUNDRED_GRAMS
    return Totals(
        kcal=ingredient.kcal_per_100g * hundreds,
        protein_g=ingredient.protein_per_100g * hundreds,
    )


def module_totals(module: Module, catalog: Catalog) -> Totals:
    """Nutrition for one portion of a module.

    Independent of ``batch_portions``: cooking three portions at once does not
    change what one portion contains.
    """
    return _sum(line_totals(line, catalog) for line in module.lines)


def entry_totals(entry: PlanEntry, catalog: Catalog) -> Totals:
    """Nutrition for a planned module, scaled by its portion factor."""
    module = catalog.module(entry.module_id)
    return module_totals(module, catalog).scaled_by(entry.portion_factor)


def slot_totals(entries: Iterable[PlanEntry], catalog: Catalog) -> Totals:
    """Nutrition for every entry in one slot.

    A slot holds one ``main`` and any number of ``side`` entries, and budgets
    apply to this sum rather than to any single entry.
    """
    return _sum(entry_totals(entry, catalog) for entry in entries)


def day_totals(day: PlanDay, catalog: Catalog) -> Totals:
    """Nutrition for a whole day. An unplanned day is zero, not an error."""
    return _sum(entry_totals(entry, catalog) for entry in day.entries)


def totals_by_slot(day: PlanDay, catalog: Catalog) -> dict[Slot, Totals]:
    """Per-slot totals for the slots this day actually uses."""
    result: dict[Slot, Totals] = {}
    for entry in day.entries:
        result[entry.slot] = result.get(entry.slot, ZERO_TOTALS) + entry_totals(entry, catalog)
    return result


def _sum(totals: Iterable[Totals]) -> Totals:
    accumulated = ZERO_TOTALS
    for item in totals:
        accumulated = accumulated + item
    return accumulated
