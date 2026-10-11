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
from ration.domain.types import SLOTS, Catalog, Level, Plan, PlanDay, Profile, Slot

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
        findings.extend(_check_template_gates(day, profile, catalog))
        findings.extend(_check_day_structure(day, profile, catalog))
    findings.extend(_check_frequency_limits(plan, profile, catalog))
    findings.extend(_check_batch_runs(plan, catalog))
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

        over_ceiling = budget.protein_max is not None and totals.protein_g > budget.protein_max
        if totals.protein_g < budget.protein_min or over_ceiling:
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
                        "max": "" if budget.protein_max is None else _n(budget.protein_max),
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


def _check_template_gates(day: PlanDay, profile: Profile, catalog: Catalog) -> list[Finding]:
    """A tag the day's template forbids, such as wine on a training day.

    This is a rule about the *context* of a day rather than its contents, which
    is why day templates are real entities and not a display preference.
    """
    findings: list[Finding] = []

    for entry in day.entries:
        module = catalog.module(entry.module_id)
        for rule in profile.frequency_rules:
            if rule.tag not in module.tags:
                continue
            if day.day_template not in rule.blocked_on_templates:
                continue
            findings.append(
                Finding(
                    level="error",
                    code="TEMPLATE_GATE_VIOLATED",
                    message_key="validation.template_gate_violated",
                    day_index=day.day_index,
                    slot=entry.slot,
                    entry_id=entry.id,
                    params={
                        "tag": rule.tag,
                        "template": day.day_template,
                        "module": module.id,
                    },
                )
            )

    return findings


def _check_frequency_limits(plan: Plan, profile: Profile, catalog: Catalog) -> list[Finding]:
    """Weekly tag counts across exactly one seven-day plan.

    A plan is always seven days (PRD 3.6), so "per week" is "per plan" and no
    rolling-window arithmetic is needed anywhere. A module carrying several tags
    counts once under each matching rule.
    """
    counts: dict[str, int] = defaultdict(int)
    for entry in plan.all_entries:
        for tag in catalog.module(entry.module_id).tags:
            counts[tag] += 1

    findings: list[Finding] = []
    for rule in profile.frequency_rules:
        if rule.max_per_week is None:
            continue
        used = counts.get(rule.tag, 0)
        if used <= rule.max_per_week:
            continue
        findings.append(
            Finding(
                level="error",
                code="FREQUENCY_EXCEEDED",
                message_key="validation.frequency_exceeded",
                params={
                    "tag": rule.tag,
                    "actual": str(used),
                    "max": str(rule.max_per_week),
                },
            )
        )

    return findings


def _check_day_structure(day: PlanDay, profile: Profile, catalog: Catalog) -> list[Finding]:
    """Shape of a day: one main per slot, and what is still missing.

    Both "missing" codes are informational. A half-built week is the normal
    state of a plan being worked on, and reporting it as an error would train
    the planner to ignore errors.
    """
    if not day.is_planned:
        return [
            Finding(
                level="info",
                code="DAY_UNPLANNED",
                message_key="validation.day_unplanned",
                day_index=day.day_index,
            )
        ]

    findings: list[Finding] = []
    expected: set[Slot] = {b.slot for b in profile.slot_budgets if not b.optional} or set(SLOTS)

    for slot in SLOTS:
        entries = day.entries_in(slot)

        mains = [e for e in entries if catalog.module(e.module_id).role == "main"]
        if len(mains) > 1:
            findings.append(
                Finding(
                    level="error",
                    code="MULTIPLE_MAIN_ENTRIES",
                    message_key="validation.multiple_main_entries",
                    day_index=day.day_index,
                    slot=slot,
                    params={"actual": str(len(mains))},
                )
            )

        if not entries and slot in expected:
            findings.append(
                Finding(
                    level="info",
                    code="SLOT_EMPTY",
                    message_key="validation.slot_empty",
                    day_index=day.day_index,
                    slot=slot,
                )
            )

    return findings


def _check_batch_runs(plan: Plan, catalog: Catalog) -> list[Finding]:
    """A module cooked ahead should be eaten on consecutive days.

    Cooking a lunch for three days and eating it on days 0, 1 and 4 means it sat
    in the fridge over a gap. Fewer appearances than batch_portions is fine —
    cooking ahead and eating less is a choice, not a mistake.
    """
    appearances: dict[str, list[int]] = defaultdict(list)
    for day in plan.days:
        for entry in day.entries:
            if catalog.module(entry.module_id).batch_portions > 1:
                appearances[entry.module_id].append(day.day_index)

    findings: list[Finding] = []
    for module_id, days in appearances.items():
        ordered = sorted(set(days))
        if len(ordered) < 2:
            continue
        if ordered == list(range(ordered[0], ordered[0] + len(ordered))):
            continue
        findings.append(
            Finding(
                level="warning",
                code="BATCH_NOT_CONSECUTIVE",
                message_key="validation.batch_not_consecutive",
                day_index=ordered[0],
                params={
                    "module": module_id,
                    "days": ",".join(str(d) for d in ordered),
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
    """Numbers travel as strings, so binary rounding never reaches the API layer."""
    return str(value.quantize(Decimal("0.1")))
