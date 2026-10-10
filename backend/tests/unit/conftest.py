"""Shared builders for validation tests.

Each test constructs the plan it needs rather than reaching for the reference
fixture, so a failure points at one rule instead of at the whole week.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from ration.domain.types import (
    DAYS_PER_PLAN,
    Catalog,
    FrequencyRule,
    Ingredient,
    IngredientRule,
    Module,
    ModuleLine,
    Plan,
    PlanDay,
    PlanEntry,
    Profile,
    Role,
    Slot,
    SlotBudget,
    Template,
)

# Round numbers, so every expected value in a test is hand-checkable.
#   plain:  100 kcal / 10 g protein per 100 g
#   rich:   500 kcal / 50 g protein per 100 g
INGREDIENTS = {
    "plain": Ingredient(
        id="plain",
        names={"ru": "Простое"},
        kcal_per_100g=Decimal(100),
        protein_per_100g=Decimal(10),
    ),
    "rich": Ingredient(
        id="rich",
        names={"ru": "Калорийное"},
        kcal_per_100g=Decimal(500),
        protein_per_100g=Decimal(50),
    ),
    "hummus": Ingredient(
        id="hummus",
        names={"ru": "Хумус"},
        kcal_per_100g=Decimal(170),
        protein_per_100g=Decimal(8),
    ),
    "chicken_breast": Ingredient(
        id="chicken_breast",
        names={"ru": "Куриная грудка"},
        kcal_per_100g=Decimal(165),
        protein_per_100g=Decimal(31),
    ),
}


def make_module(
    module_id: str,
    slot: Slot = "dinner",
    *,
    role: Role = "main",
    grams: str = "100",
    ingredient: str = "plain",
    batch_portions: int = 1,
    tags: frozenset[str] = frozenset(),
) -> Module:
    return Module(
        id=module_id,
        name=module_id,
        slot=slot,
        role=role,
        batch_portions=batch_portions,
        tags=tags,
        lines=(ModuleLine(ingredient, Decimal(grams)),),
    )


def make_catalog(*modules: Module) -> Catalog:
    return Catalog(ingredients=INGREDIENTS, modules={m.id: m for m in modules})


def make_entry(
    module_id: str,
    slot: Slot = "dinner",
    *,
    position: int = 0,
    portion: str = "1",
) -> PlanEntry:
    return PlanEntry(
        id=f"{module_id}-{slot}-{position}",
        slot=slot,
        module_id=module_id,
        portion_factor=Decimal(portion),
        position=position,
    )


def make_plan(
    days: dict[int, tuple[PlanEntry, ...]],
    templates: dict[int, Template] | None = None,
) -> Plan:
    templates = templates or {}
    return Plan(
        id="plan",
        name="test",
        profile_id="profile",
        start_date=date(2026, 10, 12),
        days=tuple(
            PlanDay(
                day_index=i,
                date=date(2026, 10, 12),
                day_template=templates.get(i, "normal"),
                entries=days.get(i, ()),
            )
            for i in range(DAYS_PER_PLAN)
        ),
    )


def make_profile(
    *,
    kcal_target: str = "1000",
    kcal_tolerance: str = "50",
    protein_min: str = "50",
    budgets: tuple[SlotBudget, ...] = (),
    ingredient_rules: tuple[IngredientRule, ...] = (),
    frequency_rules: tuple[FrequencyRule, ...] = (),
) -> Profile:
    return Profile(
        id="profile",
        name="test",
        daily_kcal_target=Decimal(kcal_target),
        daily_kcal_tolerance=Decimal(kcal_tolerance),
        daily_protein_min=Decimal(protein_min),
        daily_protein_target=Decimal(protein_min),
        slot_budgets=budgets,
        ingredient_rules=ingredient_rules,
        frequency_rules=frequency_rules,
    )


def budget(
    slot: Slot = "dinner",
    *,
    kcal: tuple[str, str] = ("0", "10000"),
    protein: tuple[str, str] = ("0", "10000"),
) -> SlotBudget:
    return SlotBudget(
        slot=slot,
        kcal_min=Decimal(kcal[0]),
        kcal_max=Decimal(kcal[1]),
        protein_min=Decimal(protein[0]),
        protein_max=Decimal(protein[1]),
    )


@pytest.fixture
def codes():
    """Collect the codes from a findings tuple, for concise assertions."""

    def _codes(findings) -> list[str]:  # type: ignore[no-untyped-def]
        return [f.code for f in findings]

    return _codes
