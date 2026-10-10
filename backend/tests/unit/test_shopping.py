"""The shopping pipeline, tested on small hand-built plans.

The reference fixture is used in test_golden_shopping.py. These cases construct
plans directly so each rule can be isolated.
"""

from datetime import date
from decimal import Decimal

import pytest

from ration.domain.shopping import group_by_section, shopping_list
from ration.domain.types import (
    DAYS_PER_PLAN,
    Catalog,
    Ingredient,
    Module,
    ModuleLine,
    Plan,
    PlanDay,
    PlanEntry,
)


def make_plan(entries_per_day: dict[int, tuple[PlanEntry, ...]]) -> Plan:
    return Plan(
        id="p",
        name="test",
        profile_id="pr",
        start_date=date(2026, 10, 12),
        days=tuple(
            PlanDay(
                day_index=i,
                date=date(2026, 10, 12),
                entries=entries_per_day.get(i, ()),
            )
            for i in range(DAYS_PER_PLAN)
        ),
    )


def entry(module_id: str, index: int = 0, portion: str = "1") -> PlanEntry:
    return PlanEntry(
        id=f"e{index}",
        slot="lunch",
        module_id=module_id,
        portion_factor=Decimal(portion),
    )


@pytest.fixture
def catalog() -> Catalog:
    return Catalog(
        ingredients={
            # Loses a third of its weight when cooked, sold loose.
            "turkey": Ingredient(
                id="turkey",
                names={"ru": "Индейка"},
                kcal_per_100g=Decimal(185),
                protein_per_100g=Decimal(25),
                yield_factor=Decimal("0.5"),
                shop_section="meat_fish",
            ),
            # Eaten as purchased, sold in 150 g bags.
            "nuts": Ingredient(
                id="nuts",
                names={"ru": "Орехи"},
                kcal_per_100g=Decimal(620),
                protein_per_100g=Decimal(15),
                yield_factor=Decimal(1),
                package_size=Decimal(150),
                package_unit="g",
                shop_section="nuts_pastes",
            ),
            # Sold by the item.
            "cucumber": Ingredient(
                id="cucumber",
                names={"ru": "Огурцы"},
                kcal_per_100g=Decimal(15),
                protein_per_100g=Decimal("0.7"),
                yield_factor=Decimal(1),
                package_size=Decimal(100),
                package_unit="pcs",
                shop_section="produce",
            ),
        },
        modules={
            "batch_lunch": Module(
                id="batch_lunch",
                name="Batch lunch",
                slot="lunch",
                batch_portions=3,
                lines=(ModuleLine("turkey", Decimal(100)),),
            ),
            "single_lunch": Module(
                id="single_lunch",
                name="Single lunch",
                slot="lunch",
                lines=(ModuleLine("turkey", Decimal(100)),),
            ),
            "nut_snack": Module(
                id="nut_snack",
                name="Nuts",
                slot="snack",
                lines=(ModuleLine("nuts", Decimal(50)),),
            ),
            "other_nut_snack": Module(
                id="other_nut_snack",
                name="More nuts",
                slot="snack",
                lines=(ModuleLine("nuts", Decimal(25)),),
            ),
            "cucumber_salad": Module(
                id="cucumber_salad",
                name="Cucumber",
                slot="dinner",
                lines=(ModuleLine("cucumber", Decimal(200)),),
            ),
        },
    )


def only(lines: tuple, ingredient_id: str):  # type: ignore[type-arg]
    return next(line for line in lines if line.ingredient_id == ingredient_id)


def test_shopping_batch_not_double_counted(catalog: Catalog) -> None:
    """The single most likely arithmetic error in the system.

    A lunch cooked once for three days is three plan entries, each one portion.
    Applying batch_portions as well would ask for three times the food.
    """
    batched = make_plan({i: (entry("batch_lunch", i),) for i in range(3)})
    singles = make_plan({i: (entry("single_lunch", i),) for i in range(3)})

    assert (
        only(shopping_list(batched, catalog), "turkey").needed_raw_g
        == only(shopping_list(singles, catalog), "turkey").needed_raw_g
    )


def test_cooked_weight_converts_to_raw_by_yield(catalog: Catalog) -> None:
    # 100 g cooked at a 0.5 yield needs 200 g raw.
    plan = make_plan({0: (entry("single_lunch"),)})
    assert only(shopping_list(plan, catalog), "turkey").needed_raw_g == Decimal("200.0")


def test_a_yield_of_one_leaves_the_quantity_untouched(catalog: Catalog) -> None:
    plan = make_plan({0: (entry("nut_snack"),)})
    assert only(shopping_list(plan, catalog), "nuts").needed_raw_g == Decimal("50.0")


def test_portion_factor_scales_the_requirement(catalog: Catalog) -> None:
    plan = make_plan({0: (entry("single_lunch", portion="0.5"),)})
    assert only(shopping_list(plan, catalog), "turkey").needed_raw_g == Decimal("100.0")


def test_two_modules_sharing_an_ingredient_merge_into_one_line(catalog: Catalog) -> None:
    plan = make_plan(
        {
            0: (
                PlanEntry(id="a", slot="snack", module_id="nut_snack"),
                PlanEntry(id="b", slot="snack", module_id="other_nut_snack", position=1),
            )
        }
    )
    lines = shopping_list(plan, catalog)
    assert len([line for line in lines if line.ingredient_id == "nuts"]) == 1
    assert only(lines, "nuts").needed_raw_g == Decimal("75.0")


def test_an_ingredient_without_a_package_size_reports_no_packages(catalog: Catalog) -> None:
    plan = make_plan({0: (entry("single_lunch"),)})
    line = only(shopping_list(plan, catalog), "turkey")
    assert line.packages is None
    assert line.overage_g == Decimal(0)
    assert line.purchase_amount == line.needed_raw_g


def test_a_partial_package_rounds_up_and_reports_overage(catalog: Catalog) -> None:
    # 50 g needed from a 150 g bag: buy one, 100 g left over.
    plan = make_plan({0: (entry("nut_snack"),)})
    line = only(shopping_list(plan, catalog), "nuts")
    assert line.packages == 1
    assert line.purchase_amount == Decimal("150.0")
    assert line.overage_g == Decimal("100.0")


def test_an_exact_multiple_does_not_add_a_spurious_package(catalog: Catalog) -> None:
    """150 g from 150 g bags is one bag, not two."""
    plan = make_plan(
        {i: (PlanEntry(id=f"e{i}", slot="snack", module_id="nut_snack"),) for i in range(3)}
    )
    line = only(shopping_list(plan, catalog), "nuts")
    assert line.needed_raw_g == Decimal("150.0")
    assert line.packages == 1
    assert line.overage_g == Decimal(0)


def test_items_sold_by_count_round_to_whole_items(catalog: Catalog) -> None:
    plan = make_plan({0: (PlanEntry(id="a", slot="dinner", module_id="cucumber_salad"),)})
    line = only(shopping_list(plan, catalog), "cucumber")
    assert line.packages == 2
    assert line.package_unit == "pcs"


def test_critical_size_propagates_from_any_contributing_line(catalog: Catalog) -> None:
    catalog_with_critical = Catalog(
        ingredients=catalog.ingredients,
        modules={
            **catalog.modules,
            "roll": Module(
                id="roll",
                name="Roll",
                slot="lunch",
                lines=(ModuleLine("nuts", Decimal(10), size_is_critical=True),),
            ),
        },
    )
    plan = make_plan(
        {
            0: (
                PlanEntry(id="a", slot="snack", module_id="nut_snack"),
                PlanEntry(id="b", slot="lunch", module_id="roll", position=1),
            )
        }
    )
    assert only(shopping_list(plan, catalog_with_critical), "nuts").size_is_critical


def test_an_unplanned_plan_produces_an_empty_list(catalog: Catalog) -> None:
    assert shopping_list(make_plan({}), catalog) == ()


def test_lines_are_grouped_by_section_and_sorted_by_name(catalog: Catalog) -> None:
    plan = make_plan(
        {
            0: (
                PlanEntry(id="a", slot="snack", module_id="nut_snack"),
                PlanEntry(id="b", slot="lunch", module_id="single_lunch", position=1),
                PlanEntry(id="c", slot="dinner", module_id="cucumber_salad", position=2),
            )
        }
    )
    lines = shopping_list(plan, catalog)
    assert [line.shop_section for line in lines] == ["meat_fish", "nuts_pastes", "produce"]
    grouped = group_by_section(lines)
    assert set(grouped) == {"meat_fish", "nuts_pastes", "produce"}
