"""Quantities with a dimension, and the refusal to convert between dimensions.

Grams and millilitres never merge. Converting between them needs a per-ingredient
density, which the project deliberately does not model (PRD 6.2). Refusing is the
specified behaviour, not a gap to work around: silently treating 200 ml of milk
as 200 g would corrupt a shopping list in a way nobody would notice.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class Dimension(StrEnum):
    """What a quantity measures. Mass and volume are not interchangeable."""

    MASS = "g"
    VOLUME = "ml"
    COUNT = "pcs"


class UnrecognisedUnitError(ValueError):
    """A quantity carries a unit this system does not model.

    Grams, millilitres and pieces are the three dimensions Ration models
    (PRD §6.2). A catalog row carrying anything else — `kg`, `tbsp`, a typo —
    cannot be converted, and guessing would corrupt a shopping list in a way
    nobody would notice.

    The message names the ingredient, which is why it never reaches telemetry:
    an ingredient id is part of one real person's dietary record (HLD §8). The
    span and the log line carry `exception.type` and the failing stage; the row
    is found against the database, by a human, with a runbook.
    """

    def __init__(self, unit: str, ingredient_id: str) -> None:
        super().__init__(
            f"{ingredient_id}: {unit!r} is not a unit this system models. "
            f"Expected one of {', '.join(d.value for d in Dimension)}."
        )
        self.unit = unit
        self.ingredient_id = ingredient_id


class DimensionMismatchError(TypeError):
    """Raised when quantities of different dimensions are combined."""

    def __init__(self, left: Dimension, right: Dimension) -> None:
        super().__init__(
            f"Cannot combine {left.value} and {right.value}: converting between them "
            f"would need a per-ingredient density, which Ration does not model."
        )
        self.left = left
        self.right = right


@dataclass(frozen=True, slots=True)
class Quantity:
    """An amount with a dimension. Immutable; arithmetic returns new instances."""

    amount: Decimal
    dimension: Dimension

    def __post_init__(self) -> None:
        if self.amount < 0:
            raise ValueError(f"Quantity cannot be negative: {self.amount}")

    def __add__(self, other: Quantity) -> Quantity:
        self._require_same_dimension(other)
        return Quantity(self.amount + other.amount, self.dimension)

    def __sub__(self, other: Quantity) -> Quantity:
        self._require_same_dimension(other)
        return Quantity(self.amount - other.amount, self.dimension)

    def scaled_by(self, factor: Decimal) -> Quantity:
        """Multiply the amount, keeping the dimension."""
        return Quantity(self.amount * factor, self.dimension)

    def divided_by(self, divisor: Decimal) -> Quantity:
        """Divide the amount, keeping the dimension. Used for yield conversion."""
        if divisor == 0:
            raise ZeroDivisionError("Cannot divide a quantity by zero")
        return Quantity(self.amount / divisor, self.dimension)

    def _require_same_dimension(self, other: Quantity) -> None:
        if self.dimension is not other.dimension:
            raise DimensionMismatchError(self.dimension, other.dimension)

    def __str__(self) -> str:
        return f"{self.amount} {self.dimension.value}"


def grams(amount: Decimal | int | str) -> Quantity:
    """Build a mass quantity. Accepts str/int so binary rounding never enters a value."""
    return Quantity(Decimal(amount), Dimension.MASS)


def millilitres(amount: Decimal | int | str) -> Quantity:
    """Build a volume quantity."""
    return Quantity(Decimal(amount), Dimension.VOLUME)


def pieces(amount: Decimal | int | str) -> Quantity:
    """Build a count quantity, for things sold by the item."""
    return Quantity(Decimal(amount), Dimension.COUNT)


def dimension_for(unit: str | None, ingredient_id: str) -> Dimension | None:
    """The dimension a unit names, or None when there is no unit.

    Raises `UnrecognisedUnitError` for a unit outside the three this system
    models. Refusing is the specified behaviour rather than a gap to work
    around: a unit nobody has defined has no conversion, and inventing one is
    how a shopping list becomes confidently wrong.
    """
    if unit is None:
        return None
    try:
        return Dimension(unit)
    except ValueError:
        raise UnrecognisedUnitError(unit, ingredient_id) from None
