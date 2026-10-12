"""Ingredient request and response shapes."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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
PackageUnit = Literal["g", "ml", "pcs"]
YieldSource = Literal["as_purchased", "estimated", "measured"]


class IngredientResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    names: dict[str, str]
    aliases: list[str] = Field(default_factory=list)
    kcal_per_100g: DecimalStr
    protein_per_100g: DecimalStr
    yield_factor: DecimalStr
    yield_source: YieldSource
    package_size: DecimalStr | None = None
    package_unit: PackageUnit | None = None
    shop_section: ShopSection
    is_staple: bool


class IngredientInput(BaseModel):
    """What a planner may send.

    `id` is absent on purpose: the slug is derived from the Russian name on
    create and never changes afterwards, so a rename cannot orphan the module
    lines that reference it.
    """

    names: dict[str, str]
    aliases: list[str] = Field(default_factory=list)
    kcal_per_100g: DecimalStr
    protein_per_100g: DecimalStr
    yield_factor: DecimalStr
    yield_source: YieldSource = "as_purchased"
    package_size: DecimalStr | None = None
    package_unit: PackageUnit | None = None
    shop_section: ShopSection = "other"
    is_staple: bool = False


class IngredientPatch(BaseModel):
    """Every field optional; absent means unchanged."""

    names: dict[str, str] | None = None
    aliases: list[str] | None = None
    kcal_per_100g: DecimalStr | None = None
    protein_per_100g: DecimalStr | None = None
    yield_factor: DecimalStr | None = None
    yield_source: YieldSource | None = None
    package_size: DecimalStr | None = None
    package_unit: PackageUnit | None = None
    shop_section: ShopSection | None = None
    is_staple: bool | None = None
