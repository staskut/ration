"""Translate database rows into frozen domain objects.

This is the only place the two worlds meet. Nothing with an ORM identity travels
outwards: an engine that received a lazily-loading model could emit a query in
the middle of an arithmetic loop, and the purity contract exists precisely to
make that impossible.

Numbers are converted to Decimal on the way out, so a driver that hands back a
float cannot leak one into a calculation.
"""

from __future__ import annotations

from decimal import Decimal
from typing import cast

from ration.domain.types import (
    Catalog,
    Feedback,
    FrequencyRule,
    Ingredient,
    IngredientRule,
    Module,
    ModuleLine,
    Plan,
    PlanDay,
    PlanEntry,
    Profile,
    Rating,
    Role,
    Satiety,
    Slot,
    SlotBudget,
    Template,
)
from ration.repositories import models


def to_decimal(value: object) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def optional_decimal(value: object) -> Decimal | None:
    return None if value is None else to_decimal(value)


def ingredient_to_domain(row: models.Ingredient) -> Ingredient:
    return Ingredient(
        id=row.slug,
        names={name.locale: name.name for name in row.names},
        kcal_per_100g=to_decimal(row.kcal_per_100g),
        protein_per_100g=to_decimal(row.protein_per_100g),
        yield_factor=to_decimal(row.yield_factor),
        package_size=optional_decimal(row.package_size),
        package_unit=row.package_unit,
        shop_section=row.shop_section,
        is_staple=row.is_staple,
        yield_source=cast(str, row.yield_source),  # type: ignore[arg-type]
    )


def module_to_domain(row: models.Module, ingredient_slugs: dict[str, str]) -> Module:
    """Build a domain module.

    ``ingredient_slugs`` maps database ids to catalog slugs, because the domain
    layer refers to ingredients by slug and never sees a database id.
    """
    return Module(
        id=row.slug,
        name=row.name,
        slot=cast(Slot, row.slot),
        role=cast(Role, row.role),
        batch_portions=row.batch_portions,
        prep_notes=row.prep_notes,
        tags=frozenset(tag.tag for tag in row.tags),
        lines=tuple(
            ModuleLine(
                ingredient_id=ingredient_slugs[line.ingredient_id],
                grams_cooked=to_decimal(line.grams_cooked),
                size_is_critical=line.size_is_critical,
                yield_factor_override=optional_decimal(line.yield_factor_override),
            )
            for line in row.lines
        ),
    )


def profile_to_domain(row: models.Profile, ingredient_slugs: dict[str, str]) -> Profile:
    return Profile(
        id=row.id,
        name=row.name,
        locale=row.locale,
        daily_kcal_target=to_decimal(row.daily_kcal_target),
        daily_kcal_tolerance=to_decimal(row.daily_kcal_tolerance),
        daily_protein_min=to_decimal(row.daily_protein_min),
        daily_protein_target=to_decimal(row.daily_protein_target),
        slot_budgets=tuple(
            SlotBudget(
                slot=cast(Slot, budget.slot),
                kcal_min=to_decimal(budget.kcal_min),
                kcal_max=to_decimal(budget.kcal_max),
                protein_min=to_decimal(budget.protein_min),
                protein_max=optional_decimal(budget.protein_max),
                optional=budget.optional,
            )
            for budget in sorted(row.slot_budgets, key=lambda b: b.slot)
        ),
        ingredient_rules=tuple(
            IngredientRule(
                ingredient_id=ingredient_slugs[rule.ingredient_id],
                rule=cast(str, rule.rule),  # type: ignore[arg-type]
                threshold_g=optional_decimal(rule.threshold_g),
            )
            for rule in sorted(row.ingredient_rules, key=lambda r: r.ingredient_id)
        ),
        frequency_rules=tuple(
            FrequencyRule(
                tag=rule.tag,
                max_per_week=rule.max_per_week,
                blocked_on_templates=_split_templates(rule.blocked_on_templates),
            )
            for rule in sorted(row.frequency_rules, key=lambda r: r.tag)
        ),
    )


def plan_to_domain(row: models.Plan, module_slugs: dict[str, str]) -> Plan:
    return Plan(
        id=row.id,
        name=row.name,
        profile_id=row.profile_id,
        start_date=row.start_date,
        status=cast(str, row.status),  # type: ignore[arg-type]
        days=tuple(
            PlanDay(
                day_index=day.day_index,
                date=day.date,
                day_template=cast(Template, day.day_template),
                notes=day.notes,
                entries=tuple(
                    PlanEntry(
                        id=entry.id,
                        slot=cast(Slot, entry.slot),
                        module_id=module_slugs[entry.module_id],
                        portion_factor=to_decimal(entry.portion_factor),
                        position=entry.position,
                    )
                    for entry in day.entries
                ),
            )
            for day in sorted(row.days, key=lambda d: d.day_index)
        ),
    )


def feedback_to_domain(row: models.Feedback) -> Feedback:
    return Feedback(
        plan_entry_id=row.plan_entry_id,
        status=cast(str, row.status),  # type: ignore[arg-type]
        rating=cast(Rating | None, row.rating),
        bloating=row.bloating,
        satiety=cast(Satiety | None, row.satiety),
        note=row.note,
    )


def catalog_from(ingredients: list[models.Ingredient], modules: list[models.Module]) -> Catalog:
    slugs = {row.id: row.slug for row in ingredients}
    return Catalog(
        ingredients={row.slug: ingredient_to_domain(row) for row in ingredients},
        modules={row.slug: module_to_domain(row, slugs) for row in modules},
    )


def _split_templates(value: str | None) -> frozenset[Template]:
    if not value:
        return frozenset()
    return frozenset(cast(Template, part.strip()) for part in value.split(",") if part.strip())


def join_templates(templates: frozenset[Template]) -> str | None:
    return ",".join(sorted(templates)) or None
