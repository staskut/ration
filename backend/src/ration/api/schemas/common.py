"""Shared request and response shapes.

Decimals cross the API as **strings**. A JSON number is an IEEE-754 double, and
round-tripping one would reintroduce exactly the rounding drift the domain layer
uses ``Decimal`` to avoid — in the one place it is hardest to notice, because the
value still looks right. ``DecimalStr`` is the single point where that is
enforced, so no schema has to remember.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Annotated, Any

from pydantic import BeforeValidator, PlainSerializer


def _to_decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        raise ValueError("Send decimals as strings. A JSON number is a float and loses precision.")
    try:
        return Decimal(str(value))
    except InvalidOperation:
        raise ValueError(f"Not a decimal: {value!r}") from None


def _from_decimal(value: Decimal) -> str:
    """Render without the storage column's padding.

    NUMERIC(12,4) returns 0.78 as Decimal("0.7800"). The values are equal, but
    "0.7800" in a form field is noise, and a round-trip test comparing strings
    would fail on a difference that is not one. normalize() alone would turn 100
    into 1E+2, so an integral result is re-quantized to a plain integer.
    """
    normalized = value.normalize()
    if normalized == normalized.to_integral_value():
        return str(normalized.quantize(Decimal(1)))
    return format(normalized, "f")


DecimalStr = Annotated[
    Decimal,
    BeforeValidator(_to_decimal),
    PlainSerializer(_from_decimal, return_type=str),
]
