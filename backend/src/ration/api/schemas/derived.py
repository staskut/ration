"""Shopping list and prep plan shapes."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from ration.api.schemas.common import DecimalStr

ShopSection = Literal[
    "meat_fish",
    "dairy",
    "produce",
    "fruit",
    "grains",
    "nuts_pastes",
    "oils_sauces",
    "supplements",
    "treats",
    "other",
]


class ShoppingLineIO(BaseModel):
    ingredient_id: str
    name: str
    shop_section: ShopSection
    needed_raw_g: DecimalStr
    purchase_amount: DecimalStr
    overage_g: DecimalStr
    packages: int | None = None
    package_unit: str | None = None
    checked: bool = False
    size_is_critical: bool = False
    is_staple: bool = False


class ShoppingListIO(BaseModel):
    plan_id: str
    lines: list[ShoppingLineIO]


class CheckedPatch(BaseModel):
    checked: bool


class CookSessionItemIO(BaseModel):
    ingredient_id: str
    name: str
    grams_raw: DecimalStr
    grams_cooked_per_portion: DecimalStr


class CookSessionIO(BaseModel):
    module_id: str
    module_name: str
    portions: int
    day_indexes: list[int]
    items: list[CookSessionItemIO]
    prep_notes: str | None = None
