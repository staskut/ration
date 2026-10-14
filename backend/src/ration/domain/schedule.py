"""When each slot happens, by day template.

Data rather than a chain of ifs, for the same reason frequency rules are data:
a long shift moving dinner to 21:00 is a fact about the follower's week, not a
branch somebody has to find.
"""

from __future__ import annotations

from ration.domain.types import SLOTS, Slot, Template

SLOT_TIMES: dict[Template, dict[Slot, str]] = {
    "normal": {
        "breakfast": "06:00",
        "lunch": "11:30",
        "snack": "15:45",
        "dinner": "18:00",
        "treat": "19:30",
    },
    "long_shift": {
        "breakfast": "06:00",
        "lunch": "11:30",
        "snack": "16:30",
        "dinner": "21:00",
        "treat": "21:30",
    },
    "training": {
        "breakfast": "06:00",
        "lunch": "11:30",
        "snack": "16:00",
        "dinner": "18:00",
        "treat": "19:30",
    },
    # A duty day runs from waking to the next sleep, so the usual
    # "last meal at 18:00" does not apply. Times are indicative only.
    "duty_24h": {
        "breakfast": "06:00",
        "lunch": "12:00",
        "snack": "17:00",
        "dinner": "21:00",
        "treat": "22:00",
    },
}


def slot_time(template: Template, slot: Slot) -> str:
    return SLOT_TIMES[template][slot]


def ordered_slots() -> tuple[Slot, ...]:
    return SLOTS
