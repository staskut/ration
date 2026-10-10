"""Totals compose from a line up to a day, and a slot sums several entries."""

from datetime import date
from decimal import Decimal

import pytest

from ration.domain.nutrition import (
    day_totals,
    entry_totals,
    line_totals,
    module_totals,
    round_totals,
    slot_totals,
    totals_by_slot,
)
from ration.domain.types import (
    Catalog,
    Ingredient,
    Module,
    ModuleLine,
    PlanDay,
    PlanEntry,
    Totals,
)


@pytest.fixture
def catalog() -> Catalog:
    """A small catalog with round numbers, so expected values are hand-checkable."""
    return Catalog(
        ingredients={
            # 200 kcal and 20 g protein per 100 g
            "fish": Ingredient(
                id="fish",
                names={"ru": "Белая рыба"},
                kcal_per_100g=Decimal(200),
                protein_per_100g=Decimal(20),
                yield_factor=Decimal("0.75"),
            ),
            # 50 kcal and 2 g protein per 100 g
            "pumpkin": Ingredient(
                id="pumpkin",
                names={"ru": "Тыква"},
                kcal_per_100g=Decimal(50),
                protein_per_100g=Decimal(2),
            ),
        },
        modules={
            "fish_main": Module(
                id="fish_main",
                name="Белая рыба",
                slot="dinner",
                lines=(ModuleLine("fish", Decimal(150)),),
            ),
            "pumpkin_side": Module(
                id="pumpkin_side",
                name="Печеная тыква",
                slot="dinner",
                role="side",
                lines=(ModuleLine("pumpkin", Decimal(200)),),
            ),
        },
    )


def test_line_totals_are_proportional_to_cooked_weight(catalog: Catalog) -> None:
    # 150 g of a 200 kcal/100 g ingredient is 300 kcal and 30 g protein.
    assert line_totals(ModuleLine("fish", Decimal(150)), catalog) == Totals(
        Decimal(300), Decimal(30)
    )


def test_module_totals_sum_their_lines(catalog: Catalog) -> None:
    combined = Module(
        id="combined",
        name="Рыба с тыквой",
        slot="dinner",
        lines=(ModuleLine("fish", Decimal(150)), ModuleLine("pumpkin", Decimal(200))),
    )
    # 300 + 100 kcal, 30 + 4 g protein
    assert module_totals(combined, catalog) == Totals(Decimal(400), Decimal(34))


def test_module_totals_ignore_batch_portions(catalog: Catalog) -> None:
    """Cooking three portions at once does not change what one portion contains."""
    one = catalog.module("fish_main")
    batched = Module(
        id="batched",
        name=one.name,
        slot=one.slot,
        lines=one.lines,
        batch_portions=3,
    )
    assert module_totals(batched, catalog) == module_totals(one, catalog)


def test_entry_totals_apply_the_portion_factor(catalog: Catalog) -> None:
    entry = PlanEntry(id="e1", slot="dinner", module_id="fish_main", portion_factor=Decimal("0.5"))
    assert entry_totals(entry, catalog) == Totals(Decimal(150), Decimal(15))


def test_a_slot_sums_a_main_and_a_side(catalog: Catalog) -> None:
    """The reason PlanEntry is plural per slot: dinner is protein plus a side."""
    main = PlanEntry(id="a", slot="dinner", module_id="fish_main")
    side = PlanEntry(id="b", slot="dinner", module_id="pumpkin_side", position=1)
    assert slot_totals((main, side), catalog) == Totals(Decimal(400), Decimal(34))


def test_an_empty_slot_is_zero_rather_than_an_error(catalog: Catalog) -> None:
    assert slot_totals((), catalog) == Totals(Decimal(0), Decimal(0))


def test_day_totals_sum_every_slot(catalog: Catalog) -> None:
    day = PlanDay(
        day_index=0,
        date=date(2026, 10, 12),
        entries=(
            PlanEntry(id="a", slot="lunch", module_id="fish_main"),
            PlanEntry(id="b", slot="dinner", module_id="fish_main"),
            PlanEntry(id="c", slot="dinner", module_id="pumpkin_side", position=1),
        ),
    )
    assert day_totals(day, catalog) == Totals(Decimal(700), Decimal(64))


def test_an_unplanned_day_is_zero(catalog: Catalog) -> None:
    empty = PlanDay(day_index=6, date=date(2026, 10, 18))
    assert day_totals(empty, catalog) == Totals(Decimal(0), Decimal(0))


def test_totals_by_slot_groups_entries(catalog: Catalog) -> None:
    day = PlanDay(
        day_index=0,
        date=date(2026, 10, 12),
        entries=(
            PlanEntry(id="a", slot="dinner", module_id="fish_main"),
            PlanEntry(id="b", slot="dinner", module_id="pumpkin_side", position=1),
            PlanEntry(id="c", slot="lunch", module_id="fish_main"),
        ),
    )
    by_slot = totals_by_slot(day, catalog)
    assert by_slot["dinner"] == Totals(Decimal(400), Decimal(34))
    assert by_slot["lunch"] == Totals(Decimal(300), Decimal(30))
    assert "breakfast" not in by_slot


def test_rounding_is_half_up_to_one_decimal() -> None:
    assert round_totals(Totals(Decimal("410.25"), Decimal("31.44"))) == Totals(
        Decimal("410.3"), Decimal("31.4")
    )


def test_intermediate_values_are_not_rounded(catalog: Catalog) -> None:
    """Three thirds of a portion must come back to a whole one.

    Rounding each entry before summing would lose a tenth here, and a day's
    calories would stop matching the sum of its meals.
    """
    third = Decimal(1) / Decimal(3)
    entries = tuple(
        PlanEntry(
            id=f"e{i}",
            slot="dinner",
            module_id="fish_main",
            portion_factor=(Decimal(1) + third).quantize(Decimal("0.01")),
        )
        for i in range(3)
    )
    unrounded = slot_totals(entries, catalog)
    assert unrounded.kcal == Decimal(300) * Decimal("1.33") * 3


def test_unknown_module_names_itself(catalog: Catalog) -> None:
    entry = PlanEntry(id="e", slot="dinner", module_id="ghost")
    with pytest.raises(KeyError, match="Unknown module: ghost"):
        entry_totals(entry, catalog)
