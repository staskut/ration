"""The prep plan against sections 10 and 11 of the reference document.

Section 10 states the batch quantities a human worked out: "на три порции,
готовое бедро индейки 360 г, готовая рисовая лапша 510 г". Those are cooked
weights, so the comparison is against per-portion weight times portions — the
raw figures beside them are what to buy, which section 12 covers instead.
"""

from decimal import Decimal

import pytest

from ration.domain.prep import prep_plan
from ration.seed import load_reference

REFERENCE = load_reference()
SESSIONS = {s.module_id: s for s in prep_plan(REFERENCE.plan, REFERENCE.catalog)}

# Section 10, in cooked grams for three portions.
SECTION_10 = {
    "lunch_rice_noodles_turkey": {
        "turkey_thigh": Decimal(360),
        "rice_noodles": Decimal(510),
        "carrot": Decimal(240),
        "spinach": Decimal(150),
        "sesame_oil": Decimal(27),
        "soy_sauce": Decimal(30),
    },
    "lunch_roll_chicken": {
        "chicken_thigh": Decimal(360),
        "tortilla_wholegrain": Decimal(225),
        "bell_pepper": Decimal(240),
        "cucumber": Decimal(150),
        "napa_cabbage": Decimal(90),
        "yogurt_natural": Decimal(90),
    },
}


def test_exactly_the_two_batch_lunches_get_a_session() -> None:
    assert set(SESSIONS) == set(SECTION_10)


def test_sessions_are_ordered_by_the_day_they_start() -> None:
    sessions = prep_plan(REFERENCE.plan, REFERENCE.catalog)
    assert [s.day_indexes[0] for s in sessions] == [0, 3]


def test_each_session_runs_three_consecutive_days() -> None:
    """Section 11 cooks one lunch for days 1-3 and the other for 4-6."""
    assert SESSIONS["lunch_rice_noodles_turkey"].day_indexes == (0, 1, 2)
    assert SESSIONS["lunch_roll_chicken"].day_indexes == (3, 4, 5)


@pytest.mark.parametrize("module_id", sorted(SECTION_10))
def test_batch_quantities_match_section_10(module_id: str) -> None:
    session = SESSIONS[module_id]
    cooked_total = {
        item.ingredient_id: item.grams_cooked_per_portion * session.portions
        for item in session.items
    }
    assert cooked_total == SECTION_10[module_id]


def test_portions_come_from_the_plan_not_from_batch_portions() -> None:
    """Cooking ahead and eating less is a choice; a session saying "cook three"
    when two are planned would waste food."""
    from dataclasses import replace

    trimmed_day = replace(REFERENCE.plan.days[2], entries=())
    days = tuple(trimmed_day if d.day_index == 2 else d for d in REFERENCE.plan.days)
    sessions = {
        s.module_id: s for s in prep_plan(replace(REFERENCE.plan, days=days), REFERENCE.catalog)
    }
    assert sessions["lunch_rice_noodles_turkey"].portions == 2


def test_the_roll_carries_its_flatbread_warning() -> None:
    """The pilot's one real failure needs to reach the person cooking."""
    notes = SESSIONS["lunch_roll_chicken"].prep_notes or ""
    assert "70–80" in notes or "70-80" in notes


def test_a_plan_with_no_batch_modules_has_no_sessions() -> None:
    from dataclasses import replace

    empty = tuple(replace(d, entries=()) for d in REFERENCE.plan.days)
    assert prep_plan(replace(REFERENCE.plan, days=empty), REFERENCE.catalog) == ()


def test_raw_quantities_use_the_yield_factor() -> None:
    """360 g of cooked turkey at a 0.65 yield is about 554 g raw."""
    turkey = next(
        i for i in SESSIONS["lunch_rice_noodles_turkey"].items if i.ingredient_id == "turkey_thigh"
    )
    assert turkey.grams_raw == Decimal("553.8")
