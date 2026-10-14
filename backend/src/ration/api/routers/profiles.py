"""Targets, budgets and rules over HTTP.

The three rule endpoints replace their collection wholesale rather than merging.
A partial update to a rule set is ambiguous about deletions — an absent rule
could mean "unchanged" or "remove it", and the planner has no way to say which.
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ration.api.deps import CurrentUserDep, PlannerDep, SessionDep, owned_profile
from ration.api.errors import ErrorDetail, not_found, unprocessable
from ration.api.schemas.profiles import (
    FrequencyRuleIO,
    IngredientRuleIO,
    ProfileResponse,
    ProfileTargetsPatch,
    SlotBudgetIO,
)
from ration.repositories import models
from ration.repositories.repositories import CatalogRepository

router = APIRouter(tags=["profiles"])


def _load(session: SessionDep, profile_id: str) -> models.Profile:
    row = session.scalars(
        select(models.Profile)
        .where(models.Profile.id == profile_id)
        .options(
            selectinload(models.Profile.slot_budgets),
            selectinload(models.Profile.ingredient_rules),
            selectinload(models.Profile.frequency_rules),
        )
    ).one_or_none()
    if row is None:
        raise not_found("Profile")
    return row


def _to_response(row: models.Profile, session: SessionDep) -> ProfileResponse:
    slugs = {i: s for s, i in CatalogRepository(session).ingredient_ids_by_slug().items()}
    return ProfileResponse(
        id=row.id,
        name=row.name,
        locale=row.locale,
        daily_kcal_target=row.daily_kcal_target,
        daily_kcal_tolerance=row.daily_kcal_tolerance,
        daily_protein_min=row.daily_protein_min,
        daily_protein_target=row.daily_protein_target,
        slot_budgets=[
            SlotBudgetIO(
                slot=b.slot,  # type: ignore[arg-type]
                kcal_min=b.kcal_min,
                kcal_max=b.kcal_max,
                protein_min=b.protein_min,
                protein_max=b.protein_max,
                optional=b.optional,
            )
            for b in sorted(row.slot_budgets, key=lambda b: b.slot)
        ],
        ingredient_rules=[
            IngredientRuleIO(
                ingredient_id=slugs[r.ingredient_id],
                rule=r.rule,  # type: ignore[arg-type]
                threshold_g=r.threshold_g,
            )
            for r in sorted(row.ingredient_rules, key=lambda r: r.ingredient_id)
        ],
        frequency_rules=[
            FrequencyRuleIO(
                tag=r.tag,
                max_per_week=r.max_per_week,
                blocked_on_templates=(
                    [t.strip() for t in r.blocked_on_templates.split(",") if t.strip()]  # type: ignore[misc]
                    if r.blocked_on_templates
                    else []
                ),
            )
            for r in sorted(row.frequency_rules, key=lambda r: r.tag)
        ],
    )


def _replace(owner: object, attribute: str, items: list, session: SessionDep) -> None:  # type: ignore[no-untyped-def]
    setattr(owner, attribute, [])
    session.flush()
    setattr(owner, attribute, items)
    session.flush()


@router.get("/profiles/{profile_id}", operation_id="getProfile")
def get_profile(profile_id: str, session: SessionDep, user: CurrentUserDep) -> ProfileResponse:
    return _to_response(_load(session, owned_profile(profile_id, user)), session)


@router.patch("/profiles/{profile_id}", operation_id="updateProfile")
def update_profile(
    profile_id: str,
    body: ProfileTargetsPatch,
    session: SessionDep,
    planner: PlannerDep,
) -> ProfileResponse:
    row = _load(session, owned_profile(profile_id, planner))

    tolerance = (
        body.daily_kcal_tolerance
        if body.daily_kcal_tolerance is not None
        else row.daily_kcal_tolerance
    )
    if tolerance < 0:
        raise unprocessable(
            "NEGATIVE_TOLERANCE",
            "daily_kcal_tolerance cannot be negative",
            ErrorDetail(field="daily_kcal_tolerance", code="negative"),
        )
    target = body.daily_kcal_target if body.daily_kcal_target is not None else row.daily_kcal_target
    if target <= 0:
        raise unprocessable(
            "NON_POSITIVE_TARGET",
            "daily_kcal_target must be positive",
            ErrorDetail(field="daily_kcal_target", code="not_positive"),
        )

    for field in (
        "name",
        "locale",
        "daily_kcal_target",
        "daily_kcal_tolerance",
        "daily_protein_min",
        "daily_protein_target",
    ):
        value = getattr(body, field)
        if value is not None:
            setattr(row, field, value)
    session.flush()
    return _to_response(row, session)


@router.put("/profiles/{profile_id}/slot-budgets", operation_id="replaceSlotBudgets")
def replace_slot_budgets(
    profile_id: str,
    body: list[SlotBudgetIO],
    session: SessionDep,
    planner: PlannerDep,
) -> list[SlotBudgetIO]:
    row = _load(session, owned_profile(profile_id, planner))

    slots = [b.slot for b in body]
    duplicates = {s for s in slots if slots.count(s) > 1}
    if duplicates:
        raise unprocessable(
            "DUPLICATE_SLOT_BUDGET",
            f"More than one budget for: {', '.join(sorted(duplicates))}",
            ErrorDetail(field="slot", code="duplicate"),
        )
    for budget in body:
        if budget.kcal_min > budget.kcal_max:
            raise unprocessable(
                "INVERTED_RANGE",
                f"{budget.slot}: kcal_min exceeds kcal_max",
                ErrorDetail(field="kcal_min", code="inverted"),
            )
        if budget.protein_max is not None and budget.protein_min > budget.protein_max:
            raise unprocessable(
                "INVERTED_RANGE",
                f"{budget.slot}: protein_min exceeds protein_max",
                ErrorDetail(field="protein_min", code="inverted"),
            )

    _replace(
        row,
        "slot_budgets",
        [
            models.SlotBudget(
                slot=b.slot,
                kcal_min=b.kcal_min,
                kcal_max=b.kcal_max,
                protein_min=b.protein_min,
                protein_max=b.protein_max,
                optional=b.optional,
            )
            for b in body
        ],
        session,
    )
    return _to_response(row, session).slot_budgets


@router.put("/profiles/{profile_id}/ingredient-rules", operation_id="replaceIngredientRules")
def replace_ingredient_rules(
    profile_id: str,
    body: list[IngredientRuleIO],
    session: SessionDep,
    planner: PlannerDep,
) -> list[IngredientRuleIO]:
    row = _load(session, owned_profile(profile_id, planner))
    ids = CatalogRepository(session).ingredient_ids_by_slug()

    missing = sorted({r.ingredient_id for r in body} - ids.keys())
    if missing:
        raise unprocessable(
            "UNKNOWN_INGREDIENT",
            f"Unknown ingredient(s): {', '.join(missing)}",
            ErrorDetail(field="ingredient_id", code="unknown"),
        )
    for rule in body:
        # The domain type enforces this too, but as a ValueError — correct for a
        # pure layer, wrong as a status code.
        if rule.rule == "caution" and rule.threshold_g is None:
            raise unprocessable(
                "THRESHOLD_REQUIRED",
                f"A caution rule for {rule.ingredient_id} needs a threshold_g",
                ErrorDetail(field="threshold_g", code="missing"),
            )
        if rule.threshold_g is not None and rule.threshold_g <= Decimal(0):
            raise unprocessable(
                "THRESHOLD_NOT_POSITIVE",
                "threshold_g must be positive",
                ErrorDetail(field="threshold_g", code="not_positive"),
            )

    seen = [r.ingredient_id for r in body]
    duplicates = {i for i in seen if seen.count(i) > 1}
    if duplicates:
        raise unprocessable(
            "DUPLICATE_RULE",
            f"More than one rule for: {', '.join(sorted(duplicates))}",
            ErrorDetail(field="ingredient_id", code="duplicate"),
        )

    _replace(
        row,
        "ingredient_rules",
        [
            models.ProfileIngredientRule(
                ingredient_id=ids[r.ingredient_id],
                rule=r.rule,
                threshold_g=r.threshold_g,
            )
            for r in body
        ],
        session,
    )
    return _to_response(row, session).ingredient_rules


@router.put("/profiles/{profile_id}/frequency-rules", operation_id="replaceFrequencyRules")
def replace_frequency_rules(
    profile_id: str,
    body: list[FrequencyRuleIO],
    session: SessionDep,
    planner: PlannerDep,
) -> list[FrequencyRuleIO]:
    row = _load(session, owned_profile(profile_id, planner))

    tags = [r.tag for r in body]
    duplicates = {t for t in tags if tags.count(t) > 1}
    if duplicates:
        raise unprocessable(
            "DUPLICATE_RULE",
            f"More than one rule for tag: {', '.join(sorted(duplicates))}",
            ErrorDetail(field="tag", code="duplicate"),
        )
    for rule in body:
        if rule.max_per_week is not None and rule.max_per_week < 0:
            raise unprocessable(
                "NEGATIVE_LIMIT",
                "max_per_week cannot be negative",
                ErrorDetail(field="max_per_week", code="negative"),
            )

    _replace(
        row,
        "frequency_rules",
        [
            models.FrequencyRule(
                tag=r.tag,
                max_per_week=r.max_per_week,
                blocked_on_templates=",".join(sorted(set(r.blocked_on_templates))) or None,
            )
            for r in body
        ],
        session,
    )
    return _to_response(row, session).frequency_rules
