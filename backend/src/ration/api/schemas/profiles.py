"""Profile, budget and rule shapes.

Ration never computes a nutrition target (PRD §7). Every value here is one the
planner set; the system stores and enforces them and offers no opinion about
whether they are appropriate.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ration.api.schemas.common import DecimalStr

Slot = Literal["breakfast", "lunch", "snack", "dinner", "treat"]
Template = Literal["normal", "long_shift", "training", "duty_24h"]


class SlotBudgetIO(BaseModel):
    slot: Slot
    kcal_min: DecimalStr
    kcal_max: DecimalStr
    protein_min: DecimalStr
    # Null means no ceiling. Protein is a floor for this kind of plan: exceeding
    # a calorie target defeats the goal, exceeding a protein target does not.
    protein_max: DecimalStr | None = None
    optional: bool = False


class IngredientRuleIO(BaseModel):
    ingredient_id: str
    rule: Literal["excluded", "caution"]
    threshold_g: DecimalStr | None = None


class FrequencyRuleIO(BaseModel):
    tag: str
    max_per_week: int | None = None
    blocked_on_templates: list[Template] = Field(default_factory=list)


class ProfileResponse(BaseModel):
    id: str
    name: str
    locale: str
    daily_kcal_target: DecimalStr
    daily_kcal_tolerance: DecimalStr
    daily_protein_min: DecimalStr
    daily_protein_target: DecimalStr
    slot_budgets: list[SlotBudgetIO]
    ingredient_rules: list[IngredientRuleIO]
    frequency_rules: list[FrequencyRuleIO]


class ProfileTargetsPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    locale: str | None = None
    daily_kcal_target: DecimalStr | None = None
    daily_kcal_tolerance: DecimalStr | None = None
    daily_protein_min: DecimalStr | None = None
    daily_protein_target: DecimalStr | None = None
