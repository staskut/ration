"""Units refuse to convert between dimensions, which is the specified behaviour."""

from decimal import Decimal

import pytest

from ration.domain.units import (
    Dimension,
    DimensionMismatchError,
    Quantity,
    grams,
    millilitres,
    pieces,
)


def test_same_dimension_quantities_add() -> None:
    assert grams(300) + grams("1000") == grams(1300)


def test_mass_and_volume_refuse_to_combine() -> None:
    with pytest.raises(DimensionMismatchError) as exc:
        grams(200) + millilitres(200)
    assert exc.value.left is Dimension.MASS
    assert exc.value.right is Dimension.VOLUME


def test_mismatch_message_explains_why_rather_than_just_failing() -> None:
    with pytest.raises(DimensionMismatchError, match="density"):
        millilitres(100) - grams(50)


def test_counts_are_their_own_dimension() -> None:
    with pytest.raises(DimensionMismatchError):
        pieces(3) + grams(300)


def test_scaling_keeps_the_dimension() -> None:
    assert grams(100).scaled_by(Decimal("1.5")) == grams("150.0")


def test_dividing_converts_cooked_weight_to_raw() -> None:
    # 360 g cooked turkey at a 0.67 yield is about 537 g raw.
    raw = grams(360).divided_by(Decimal("0.67"))
    assert raw.dimension is Dimension.MASS
    assert raw.amount == pytest.approx(Decimal("537.3"), abs=Decimal("0.1"))


def test_dividing_by_zero_is_refused() -> None:
    with pytest.raises(ZeroDivisionError):
        grams(100).divided_by(Decimal(0))


def test_negative_quantities_are_refused() -> None:
    with pytest.raises(ValueError, match="negative"):
        grams(-1)


def test_quantities_are_frozen() -> None:
    q = grams(100)
    with pytest.raises(AttributeError):
        q.amount = Decimal(200)  # type: ignore[misc]


def test_string_input_avoids_float_precision_loss() -> None:
    assert Quantity(Decimal("0.1"), Dimension.MASS).amount + Decimal("0.2") == Decimal("0.3")
