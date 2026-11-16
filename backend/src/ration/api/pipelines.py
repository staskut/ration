"""The shopping-list pipeline, driven one stage at a time.

HLD §4 describes generating a shopping list as a sequence of stages. The engine
composes those stages itself in `domain.shopping.shopping_list()`; this module
runs the same stages one by one so each gets its own span, and a stage that is
slow or that raises is visible rather than inferred (HLD §7).

There is no arithmetic here, and there must not be: every stage is a call into
`domain/`, and this module's only job is to run them in order and time them.
The domain knows nothing about any of this — it may not import
`opentelemetry` or `ration.observability`, and CI enforces that (AD-1).

The duplication with `shopping_list()` is deliberate and guarded:
`tests/unit/test_shopping_stages.py` asserts that composing the stages by hand
gives exactly what the engine's own composition gives, for the reference plan.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from ration.domain.shopping import (
    ShoppingLine,
    convert_to_raw,
    expand_entries,
    group_by_shop_section,
    merge_by_ingredient,
    round_to_packages,
)
from ration.observability import names
from ration.observability.telemetry import stage
from ration.repositories.repositories import CatalogRepository, PlanRepository


@dataclass(frozen=True, slots=True)
class CheckedLine:
    """A shopping line and whether the follower has ticked it off."""

    line: ShoppingLine
    checked: bool


def shopping_list_for(session: Session, plan_id: str, locale: str) -> tuple[CheckedLine, ...]:
    """Run HLD §4's pipeline, a span per stage, and return what to render."""
    with stage(names.LOAD_CATALOG) as recorder:
        catalog = CatalogRepository(session).load()
        recorder.count(len(catalog.ingredients))

    with stage(names.LOAD_PLAN) as recorder:
        plan = PlanRepository(session).load(plan_id)
        assert plan is not None
        recorder.count(len(plan.all_entries))

    with stage(names.EXPAND_ENTRIES, items_in=len(plan.all_entries)) as recorder:
        cooked = expand_entries(plan, catalog)
        recorder.count(len(cooked))

    with stage(names.CONVERT_YIELD, items_in=len(cooked)) as recorder:
        raw = convert_to_raw(cooked)
        recorder.count(len(raw))

    with stage(names.MERGE_INGREDIENTS, items_in=len(raw)) as recorder:
        merged = merge_by_ingredient(raw)
        recorder.count(len(merged))

    with stage(names.ROUND_PACKAGES, items_in=len(merged)) as recorder:
        rounded = round_to_packages(merged, catalog, locale)
        recorder.count(len(rounded))

    with stage(names.GROUP_SECTIONS, items_in=len(rounded)) as recorder:
        lines = group_by_shop_section(rounded)
        recorder.count(len(lines))

    with stage(names.MERGE_CHECKED, items_in=len(lines)) as recorder:
        # The follower's state, not the planner's plan — which is why this
        # stage is here and not in the engine.
        checked = PlanRepository(session).checked_ingredients(plan_id)
        result = tuple(CheckedLine(line, line.ingredient_id in checked) for line in lines)
        recorder.count(len(result))

    return result
