"""Module transcription matches the per-dish figures stated in the document."""

from decimal import Decimal

import pytest

from ration.domain.nutrition import module_totals
from ration.seed.loader import load_module_claims, load_reference

REFERENCE = load_reference()
CLAIMS = load_module_claims()

# These are SANITY CHECKS, not a fit.
#
# The catalog carries reference nutrition values for the preparation each line
# describes; it is not tuned to reproduce section 9's per-dish totals
# (docs/decisions.md D1). Those totals are approximate by the document's own
# admission, and it says to verify against package labels. So the job here is to
# catch a gross transcription error — a line entered as 500 g instead of 50 —
# not to prove the two agree.
#
# Measured drift against section 9: calories at most 13%, protein at most 26% on
# anything with a meaningful absolute size. The protein gap is systematic and
# one-directional: every dish computes HIGHER than stated, which is what applying
# raw nutrition values to cooked weights looks like. Cooking concentrates
# protein by roughly a third, so the document most likely understated it.
KCAL_TOLERANCE_PCT = Decimal("0.20")
KCAL_TOLERANCE_MIN = Decimal(30)

PROTEIN_TOLERANCE_PCT = Decimal("0.35")
PROTEIN_TOLERANCE_MIN = Decimal(4)

MODULE_IDS = sorted(REFERENCE.catalog.modules)


def test_every_module_in_the_plan_table_is_transcribed() -> None:
    """Section 8 lists 19 distinct modules across six days.

    Section 14's feedback table shows 14 rows because it groups the shakes and
    the overnight oats; the module count is 19.
    """
    assert len(REFERENCE.catalog.modules) == 19


def test_every_ingredient_reference_resolves() -> None:
    catalog = REFERENCE.catalog
    unresolved = [
        f"{module.id} -> {line.ingredient_id}"
        for module in catalog.modules.values()
        for line in module.lines
        if line.ingredient_id not in catalog.ingredients
    ]
    assert unresolved == []


@pytest.mark.parametrize("module_id", MODULE_IDS)
def test_computed_kcal_is_in_the_same_region_as_the_stated_figure(module_id: str) -> None:
    stated, _ = CLAIMS[module_id]
    computed = module_totals(REFERENCE.catalog.modules[module_id], REFERENCE.catalog).kcal
    tolerance = max(stated * KCAL_TOLERANCE_PCT, KCAL_TOLERANCE_MIN)
    assert abs(computed - stated) <= tolerance, (
        f"{module_id}: computed {computed:.1f} kcal against a stated {stated}. "
        "A gap this large is a transcription error, not the document rounding."
    )


@pytest.mark.parametrize("module_id", MODULE_IDS)
def test_computed_protein_is_in_the_same_region_as_the_stated_figure(module_id: str) -> None:
    _, stated = CLAIMS[module_id]
    computed = module_totals(REFERENCE.catalog.modules[module_id], REFERENCE.catalog).protein_g
    tolerance = max(stated * PROTEIN_TOLERANCE_PCT, PROTEIN_TOLERANCE_MIN)
    assert abs(computed - stated) <= tolerance, (
        f"{module_id}: computed {computed:.1f} g against a stated {stated}. "
        "A gap this large is a transcription error, not the document rounding."
    )


def test_only_the_two_batch_lunches_are_cooked_ahead() -> None:
    batched = {m.id for m in REFERENCE.catalog.modules.values() if m.batch_portions > 1}
    assert batched == {"lunch_rice_noodles_turkey", "lunch_roll_chicken"}
    for module_id in batched:
        assert REFERENCE.catalog.modules[module_id].batch_portions == 3


def test_tags_that_drive_rules_are_present() -> None:
    tags = {tag for m in REFERENCE.catalog.modules.values() for tag in m.tags}
    assert {"treat", "alcohol", "salted_fish", "fish", "home_only"} <= tags


def test_salted_fish_is_tagged_on_exactly_the_two_dishes_the_rule_limits() -> None:
    tagged = {m.id for m in REFERENCE.catalog.modules.values() if "salted_fish" in m.tags}
    assert tagged == {"dinner_salted_salmon_eggs", "dinner_herring_cottage"}


def test_the_roll_marks_its_flatbread_size_as_critical() -> None:
    """The pilot's one failure: a 45 g flatbread against a 75 g spec would not
    wrap (section 14). The size is structural, not a shopping convenience."""
    roll = REFERENCE.catalog.modules["lunch_roll_chicken"]
    critical = [line.ingredient_id for line in roll.lines if line.size_is_critical]
    assert critical == ["tortilla_wholegrain"]


def test_every_module_has_a_slot_the_profile_budgets() -> None:
    budgeted = {b.slot for b in REFERENCE.profile.slot_budgets}
    assert {m.slot for m in REFERENCE.catalog.modules.values()} <= budgeted


def test_protein_drift_is_one_directional() -> None:
    """Every dish computes at or above its stated protein, never meaningfully below.

    This pins the finding rather than just tolerating it. A systematic upward gap
    is the signature of raw nutrition values applied to cooked weights; a
    two-directional scatter would instead mean the catalog is simply noisy.
    """
    below = []
    for module_id in MODULE_IDS:
        _, stated = CLAIMS[module_id]
        computed = module_totals(REFERENCE.catalog.modules[module_id], REFERENCE.catalog).protein_g
        if computed < stated - Decimal(2):
            below.append(f"{module_id}: {computed:.1f} < {stated}")
    assert below == [], f"dishes computing below their stated protein: {below}"
