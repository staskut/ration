"""Validation, the shopping list and the prep plan.

Everything here is computed by `ration.domain` and assembled for transport. No
arithmetic in this module: if a number needs working out, the engine works it
out and this reads it.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from ration.api.broadcast import notify
from ration.api.deps import CurrentUserDep, OwnedPlanDep, SessionDep
from ration.api.errors import not_found
from ration.api.pipelines import shopping_list_for
from ration.api.routers.plans import _report
from ration.api.schemas.derived import (
    CheckedPatch,
    CookSessionIO,
    CookSessionItemIO,
    ShoppingLineIO,
    ShoppingListIO,
)
from ration.api.schemas.plans import ValidationReport
from ration.domain.prep import prep_plan
from ration.repositories import models
from ration.repositories.repositories import CatalogRepository, PlanRepository

router = APIRouter(tags=["derived"])


@router.get("/plans/{plan_id}/validation", operation_id="getValidation")
def get_validation(plan: OwnedPlanDep, session: SessionDep) -> ValidationReport:
    return _report(session, plan.id)


@router.get("/plans/{plan_id}/shopping-list", operation_id="getShoppingList")
def get_shopping_list(
    plan: OwnedPlanDep, session: SessionDep, user: CurrentUserDep
) -> ShoppingListIO:
    """The most computation-heavy endpoint, and the instrumented one (HLD §7).

    The pipeline runs in `api/pipelines.py`, stage by stage, so each stage of
    HLD §4 is its own span. This handler assembles the response and nothing
    else.
    """
    return ShoppingListIO(
        plan_id=plan.id,
        lines=[
            ShoppingLineIO(
                ingredient_id=entry.line.ingredient_id,
                name=entry.line.name,
                shop_section=entry.line.shop_section,  # type: ignore[arg-type]
                needed_raw_g=entry.line.needed_raw_g,
                purchase_amount=entry.line.purchase_amount,
                overage_g=entry.line.overage_g,
                packages=entry.line.packages,
                package_unit=entry.line.package_unit,
                checked=entry.checked,
                size_is_critical=entry.line.size_is_critical,
                is_staple=entry.line.is_staple,
            )
            for entry in shopping_list_for(session, plan.id, user.locale)
        ],
    )


@router.patch(
    "/plans/{plan_id}/shopping-list/{ingredient_id}",
    operation_id="setShoppingItemChecked",
)
def set_checked(
    plan: OwnedPlanDep,
    ingredient_id: str,
    body: CheckedPatch,
    session: SessionDep,
    user: CurrentUserDep,
    request: Request = None,  # type: ignore[assignment]
) -> ShoppingLineIO:
    """Both roles may write this — the follower is the one in the shop.

    State lives here rather than in browser storage: the follower may plan on
    one device and shop with another, and nothing in the system may depend on
    them maintaining anything (PRD §2.1).
    """
    listing = get_shopping_list(plan, session, user)
    line = next((x for x in listing.lines if x.ingredient_id == ingredient_id), None)
    if line is None:
        raise not_found("Shopping list item")

    row_id = CatalogRepository(session).ingredient_ids_by_slug()[ingredient_id]
    state = session.get(models.ShoppingCheckState, (plan.id, row_id))
    if state is None:
        state = models.ShoppingCheckState(plan_id=plan.id, ingredient_id=row_id)
        session.add(state)
    state.checked = body.checked
    session.flush()

    notify(request, plan.id, ["shopping_list"])
    line.checked = body.checked
    return line


@router.get("/plans/{plan_id}/prep-plan", operation_id="getPrepPlan")
def get_prep_plan(
    plan: OwnedPlanDep, session: SessionDep, user: CurrentUserDep
) -> list[CookSessionIO]:
    catalog = CatalogRepository(session).load()
    domain_plan = PlanRepository(session).load(plan.id)
    assert domain_plan is not None
    return [
        CookSessionIO(
            module_id=s.module_id,
            module_name=s.module_name,
            portions=s.portions,
            day_indexes=list(s.day_indexes),
            prep_notes=s.prep_notes,
            items=[
                CookSessionItemIO(
                    ingredient_id=i.ingredient_id,
                    name=i.name,
                    grams_raw=i.grams_raw,
                    grams_cooked_per_portion=i.grams_cooked_per_portion,
                )
                for i in s.items
            ],
        )
        for s in prep_plan(domain_plan, catalog, locale=user.locale)
    ]
