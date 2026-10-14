"""Plan, day and entry shapes."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from ration.api.schemas.common import DecimalStr

Slot = Literal["breakfast", "lunch", "snack", "dinner", "treat"]
Role = Literal["main", "side"]
Template = Literal["normal", "long_shift", "training", "duty_24h"]
Status = Literal["draft", "active", "archived"]
Level = Literal["error", "warning", "info"]


class FindingIO(BaseModel):
    """A rule violation.

    Carries a key and parameters, never a formatted sentence: the follower's
    screens are Russian and a sentence built here would be untranslatable.
    """

    level: Level
    code: str
    message_key: str
    params: dict[str, str]
    day_index: int | None = None
    slot: Slot | None = None
    entry_id: str | None = None


class ValidationReport(BaseModel):
    findings: list[FindingIO]
    error_count: int
    warning_count: int


class PlanEntryResponse(BaseModel):
    id: str
    slot: Slot
    module_id: str
    module_name: str
    role: Role
    portion_factor: DecimalStr
    position: int
    kcal: DecimalStr
    protein_g: DecimalStr


class SlotTotals(BaseModel):
    slot: Slot
    kcal: DecimalStr
    protein_g: DecimalStr


class PlanDayResponse(BaseModel):
    day_index: int
    date: date
    day_template: Template
    notes: str | None = None
    entries: list[PlanEntryResponse]
    kcal: DecimalStr
    protein_g: DecimalStr
    slot_totals: list[SlotTotals]


class PlanSummary(BaseModel):
    id: str
    name: str
    profile_id: str
    start_date: date
    status: Status


class PlanResponse(PlanSummary):
    days: list[PlanDayResponse]


class PlanCreate(BaseModel):
    name: str = Field(min_length=1)
    start_date: date
    copy_from_plan_id: str | None = None


class PlanPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    status: Status | None = None


class PlanDayPut(BaseModel):
    day_template: Template | None = None
    notes: str | None = None


class PlanEntryCreate(BaseModel):
    slot: Slot
    module_id: str
    portion_factor: DecimalStr | None = None
    position: int | None = None


class PlanEntryPatch(BaseModel):
    module_id: str | None = None
    portion_factor: DecimalStr | None = None
    position: int | None = None


class PlanDayWithValidation(BaseModel):
    day: PlanDayResponse
    validation: ValidationReport


class PlanEntryWithValidation(BaseModel):
    entry: PlanEntryResponse
    validation: ValidationReport
