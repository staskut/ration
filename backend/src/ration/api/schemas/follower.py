"""Feedback and the Today view.

Feedback leads with `status` and `rating` because that is what a real pilot
produced: bloating and satiety went unreported for a whole week (PRD §3.7).
`status` is inferred from a rating and never submitted.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from ration.api.schemas.common import DecimalStr

Slot = Literal["breakfast", "lunch", "snack", "dinner", "treat"]
Template = Literal["normal", "long_shift", "training", "duty_24h"]
Rating = Literal["liked", "neutral", "disliked"]
Satiety = Literal["too_little", "right", "too_much"]


class FeedbackInput(BaseModel):
    rating: Rating
    bloating: int | None = Field(default=None, ge=0, le=3)
    satiety: Satiety | None = None
    note: str | None = None


class FeedbackResponse(BaseModel):
    plan_entry_id: str
    status: Literal["not_tried", "tried"]
    rating: Rating | None = None
    bloating: int | None = None
    satiety: Satiety | None = None
    note: str | None = None


class TodayEntry(BaseModel):
    entry_id: str
    module_id: str
    module_name: str
    portion_grams: DecimalStr
    kcal: DecimalStr
    protein_g: DecimalStr
    home_only: bool
    critical_notes: list[str] = Field(default_factory=list)
    feedback: FeedbackResponse | None = None


class TodaySlot(BaseModel):
    slot: Slot
    time: str
    entries: list[TodayEntry]
    kcal: DecimalStr
    protein_g: DecimalStr


class TodayView(BaseModel):
    plan_id: str
    date: date
    day_index: int
    day_template: Template
    slots: list[TodaySlot]
    kcal: DecimalStr
    protein_g: DecimalStr
