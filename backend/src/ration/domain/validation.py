"""Check a plan against the planner's own rules.

Findings carry a stable ``code`` and a ``message_key`` with parameters, never a
formatted sentence. The follower's screens are Russian (PRD 8), so a sentence
built here would be untranslatable — and a stable code is what lets a test
assert on a finding without matching prose.

Every check is reported against rules the planner configured. Ration has no
opinion about whether a plan is healthy, and says nothing of the kind (PRD 7).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from ration.domain.nutrition import day_totals, totals_by_slot
from ration.domain.types import Catalog, Level, Plan, PlanDay, Profile, Slot

_LEVEL_ORDER: Mapping[Level, int] = {"error": 0, "warning": 1, "info": 2}


@dataclass(frozen=True, slots=True)
class Finding:
    """One rule violation, located as precisely as the check allows."""

    level: Level
    code: str
    message_key: str
    day_index: int | None = None
    slot: Slot | None = None
    entry_id: str | None = None
    params: Mapping[str, str] = field(default_factory=dict)


def validate(plan: Plan, profile: Profile, catalog: Catalog) -> tuple[Finding, ...]:
    """Every finding for a plan, errors first."""
    findings: list[Finding] = []
    for day in plan.days:
        findings.extend(_check_day_budgets(day, profile, catalog))
        findings.extend(_check_slot_budgets(day, profile, catalog))
        findings.extend(_check_excluded_ingredients(day, profile, catalog))
        findings.extend(_check_caution_thresholds(day, profile, catalog))
    return _sorted(findings)


def _check_day_budgets(day: PlanDay, profile: Profile, catalog: Catalog) -> list[Finding]:
    """Daily calorie and protein checks.

    Skipped entirely for an unplanned day: a day with no food is an in-progress
    week, not a starving one. Structural checks report that separately.
    """
    if not day.is_planned:
        return []

    findings: list[Finding] = []
    totals = day_totals(day, catalog)

    low = profile.daily_kcal_target - profile.daily_kcal_tolerance
    high = profile.daily_kcal_target + profile.daily_kcal_tolerance
    if not low <= totals.kcal <= high:
        findings.append(
            Finding(
                level="error",
                code="DAY_KCAL_OUT_OF_RANGE",
                message_key="validation.day_kcal_out_of_range",
                day_index=day.day_index,
                params={
                    "actual": _n(totals.kcal),
                    "min": _n(low),
                    "max": _n(high),
                },
            )
        )

    if totals.protein_g < profile.daily_protein_min:
        findings.append(
            Finding(
                level="error",
                code="DAY_PROTEIN_BELOW_MIN",
                message_key="validation.day_protein_below_min",
                day_index=day.day_index,
                params={
                    "actual": _n(totals.protein_g),
                    "min": _n(profile.daily_protein_min),
                },
            )
        )

    return findings


def _check_slot_budgets(day: PlanDay, profile: Profile, catalog: Catalog) -> list[Finding]:
    """Per-slot checks against the slot's **sum**.

    A slot holds one main and any number of sides, so two entries that are
    individually reasonable can still breach the budget together. Comparing a
    single entry would miss exactly that case.
    """
    findings: list[Finding] = []

    for slot, totals in totals_by_slot(day, catalog).items():
        budget = profile.budget_for(slot)
        if budget is None:
            continue

        if not budget.kcal_min <= totals.kcal <= budget.kcal_max:
            findings.append(
                Finding(
                    level="warning",
                    code="SLOT_OUT_OF_BUDGET",
                    message_key="validation.slot_kcal_out_of_budget",
                    day_index=day.day_index,
                    slot=slot,
                    params={
                        "actual": _n(totals.kcal),
                        "min": _n(budget.kcal_min),
                        "max": _n(budget.kcal_max),
                        "metric": "kcal",
                    },
                )
            )

        if not budget.protein_min <= totals.protein_g <= budget.protein_max:
            findings.append(
                Finding(
                    level="warning",
                    code="SLOT_OUT_OF_BUDGET",
                    message_key="validation.slot_protein_out_of_budget",
                    day_index=day.day_index,
                    slot=slot,
                    params={
                        "actual": _n(totals.protein_g),
                        "min": _n(budget.protein_min),
                        "max": _n(budget.protein_max),
                        "metric": "protein_g",
                    },
                )
            )

    return findings


def _check_excluded_ingredients(day: PlanDay, profile: Profile, catalog: Catalog) -> list[Finding]:
    """Any excluded ingredient anywhere in the day is an error.

    The rule lives on the profile, not on the ingredient: the same catalog could
    serve a second person who tolerates it.
    """
    findings: list[Finding] = []

    for entry in day.entries:
        module = catalog.module(entry.module_id)
        for line in module.lines:
            rule = profile.rule_for(line.ingredient_id)
            if rule is None or rule.rule != "excluded":
                continue
            findings.append(
                Finding(
                    level="error",
                    code="EXCLUDED_INGREDIENT",
                    message_key="validation.excluded_ingredient",
                    day_index=day.day_index,
                    slot=entry.slot,
                    entry_id=entry.id,
                    params={
                        "ingredient": line.ingredient_id,
                        "module": module.id,
                    },
                )
            )

    return findings


def _check_caution_thresholds(day: PlanDay, profile: Profile, catalog: Catalog) -> list[Finding]:
    """Caution ingredients are summed across the whole day before comparing.

    Two modules can each stay under the threshold and clear it together — a
    per-module check would wave that through, which is the failure this guards.
    Thresholds do not carry over between days.
    """
    consumed: dict[str, Decimal] = defaultdict(Decimal)

    for entry in day.entries:
        for line in catalog.module(entry.module_id).lines:
            rule = profile.rule_for(line.ingredient_id)
            if rule is not None and rule.rule == "caution":
                consumed[line.ingredient_id] += line.grams_cooked * entry.portion_factor

    findings: list[Finding] = []
    for ingredient_id, grams in consumed.items():
        rule = profile.rule_for(ingredient_id)
        if rule is None or rule.threshold_g is None or grams <= rule.threshold_g:
            continue
        findings.append(
            Finding(
                level="warning",
                code="CAUTION_THRESHOLD_EXCEEDED",
                message_key="validation.caution_threshold_exceeded",
                day_index=day.day_index,
                params={
                    "ingredient": ingredient_id,
                    "actual": _n(grams),
                    "threshold": _n(rule.threshold_g),
                },
            )
        )

    return findings


def _sorted(findings: Sequence[Finding]) -> tuple[Finding, ...]:
    return tuple(
        sorted(
            findings,
            key=lambda f: (
                _LEVEL_ORDER[f.level],
                f.day_index if f.day_index is not None else -1,
                f.code,
                f.slot or "",
            ),
        )
    )


def _n(value: Decimal) -> str:
    """Numbers travel as strings so no float ever reaches the API layer."""
    return str(value.quantize(Decimal("0.1")))
