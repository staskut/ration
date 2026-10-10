"""The ingredient catalog fixture is well-formed and internally consistent.

These are not tests of behaviour. They guard a hand-transcription that every
golden test downstream depends on, so an error here would surface later as a
phantom engine bug.
"""

from decimal import Decimal

import pytest
import yaml

from ration.domain.types import MAX_YIELD_FACTOR
from ration.seed.loader import SEED_DIR, load_reference

RAW = yaml.safe_load((SEED_DIR / "ingredients.yaml").read_text(encoding="utf-8"))
REQUIRED = {
    "slug",
    "name_ru",
    "kcal_per_100g",
    "protein_per_100g",
    "yield_factor",
    "package_size",
    "package_unit",
    "shop_section",
}
# Section 12 of the reference document groups the shopping list by these.
SECTIONS = {
    "meat_fish",
    "dairy",
    "produce",
    "fruit",
    "grains",
    "nuts_pastes",
    "oils_sauces",
    "supplements",
    "treats",
}


def test_every_entry_has_the_required_fields() -> None:
    missing = {e.get("slug", "?"): REQUIRED - e.keys() for e in RAW if REQUIRED - e.keys()}
    assert missing == {}


def test_slugs_are_unique() -> None:
    slugs = [e["slug"] for e in RAW]
    assert len(slugs) == len(set(slugs))


def test_every_shop_section_is_one_the_document_uses() -> None:
    assert {e["shop_section"] for e in RAW} <= SECTIONS


def test_numbers_are_quoted_so_they_parse_as_exact_decimals() -> None:
    """An unquoted 0.65 would arrive as a binary float and silently undo the
    precision the whole domain layer is built on."""
    floats = [
        f"{e['slug']}.{field}"
        for e in RAW
        for field in ("kcal_per_100g", "protein_per_100g", "yield_factor", "package_size")
        if type(e.get(field)) is float
    ]
    assert floats == []


def test_loaded_values_are_decimals() -> None:
    for ingredient in load_reference().catalog.ingredients.values():
        assert isinstance(ingredient.kcal_per_100g, Decimal)
        assert isinstance(ingredient.protein_per_100g, Decimal)
        assert isinstance(ingredient.yield_factor, Decimal)


def test_yield_factors_are_in_range() -> None:
    for ingredient in load_reference().catalog.ingredients.values():
        assert Decimal(0) < ingredient.yield_factor <= MAX_YIELD_FACTOR


def test_items_eaten_as_purchased_have_a_yield_of_one() -> None:
    catalog = load_reference().catalog
    for slug in ("banana", "cucumber", "nuts", "olive_oil", "whey_protein"):
        assert catalog.ingredient(slug).yield_factor == Decimal(1)


@pytest.mark.parametrize(
    ("slug", "expected"),
    [
        # Back-solved from section 12's raw weights against sections 9-10's
        # cooked weights. Meat and fish lose water; rice noodles absorb it.
        ("turkey_thigh", Decimal("0.65")),
        ("chicken_thigh", Decimal("0.65")),
        ("white_fish", Decimal("0.72")),
        ("shrimp", Decimal("0.58")),
        ("squid", Decimal("0.62")),
        ("rice_noodles", Decimal("2.85")),
    ],
)
def test_cooking_yields_match_the_document(slug: str, expected: Decimal) -> None:
    assert load_reference().catalog.ingredient(slug).yield_factor == expected


def test_items_sold_by_count_carry_a_weight_per_piece() -> None:
    """Section 12 asks for "3 medium cucumbers", not 350 g, so the shopping
    engine needs a gram weight per piece to round with."""
    for ingredient in load_reference().catalog.ingredients.values():
        if ingredient.package_unit == "pcs":
            assert ingredient.package_size is not None
            assert ingredient.package_size > 0


def test_every_ingredient_has_a_russian_name() -> None:
    for ingredient in load_reference().catalog.ingredients.values():
        assert ingredient.name("ru").strip()
