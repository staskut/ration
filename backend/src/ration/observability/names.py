"""The names of the shopping-list pipeline's spans, in pipeline order.

One place, so an alert, a dashboard query or a runbook can name a stage without
reading the implementation, and so renaming a stage is a change somebody has to
make deliberately rather than a string edit that silently breaks a query.

The stages are the ones in HLD §4. Six of them are the domain engine; the first
two are the repository loads and the last is the check-off merge, which happens
in the API because the follower's state is not the planner's plan.
"""

from __future__ import annotations

from typing import Final

REQUEST_SPAN: Final = "http.request"

LOAD_CATALOG: Final = "shopping_list.load_catalog"
LOAD_PLAN: Final = "shopping_list.load_plan"
EXPAND_ENTRIES: Final = "shopping_list.expand_entries"
CONVERT_YIELD: Final = "shopping_list.convert_yield"
MERGE_INGREDIENTS: Final = "shopping_list.merge_ingredients"
ROUND_PACKAGES: Final = "shopping_list.round_packages"
GROUP_SECTIONS: Final = "shopping_list.group_sections"
MERGE_CHECKED: Final = "shopping_list.merge_checked"

#: Every stage span the shopping-list route emits, in the order it emits them.
SHOPPING_LIST_STAGES: Final[tuple[str, ...]] = (
    LOAD_CATALOG,
    LOAD_PLAN,
    EXPAND_ENTRIES,
    CONVERT_YIELD,
    MERGE_INGREDIENTS,
    ROUND_PACKAGES,
    GROUP_SECTIONS,
    MERGE_CHECKED,
)
