"""Module request and response shapes.

Totals are response-only. A module's calories are derived from its lines, so
accepting them would let a client submit a module whose stated energy disagrees
with its ingredients — and the shopping list would then be computed from one
number while the planner read another.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ration.api.schemas.common import DecimalStr

Slot = Literal["breakfast", "lunch", "snack", "dinner", "treat"]
Role = Literal["main", "side"]


class ModuleLineIO(BaseModel):
    ingredient_id: str
    grams_cooked: DecimalStr
    size_is_critical: bool = False
    yield_factor_override: DecimalStr | None = None


class ModuleResponse(BaseModel):
    id: str
    name: str
    slot: Slot
    role: Role
    batch_portions: int
    lines: list[ModuleLineIO]
    tags: list[str]
    prep_notes: str | None = None
    kcal: DecimalStr
    protein_g: DecimalStr


class ModuleInput(BaseModel):
    name: str = Field(min_length=1)
    slot: Slot
    role: Role = "main"
    batch_portions: int = 1
    lines: list[ModuleLineIO]
    tags: list[str] = Field(default_factory=list)
    prep_notes: str | None = None


class ModulePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    slot: Slot | None = None
    role: Role | None = None
    batch_portions: int | None = None
    lines: list[ModuleLineIO] | None = None
    tags: list[str] | None = None
    prep_notes: str | None = None
