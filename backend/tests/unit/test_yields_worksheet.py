"""The yield worksheet runs and reports what it should."""

from decimal import Decimal

import pytest

from ration.seed import load_reference
from ration.seed.yields import cooked_requirements, main, what_if, worksheet

REFERENCE = load_reference()


def test_the_worksheet_lists_every_factor_needing_review() -> None:
    text = worksheet(REFERENCE)
    for slug in ("turkey_thigh", "white_fish", "shrimp", "squid", "rice_noodles"):
        assert slug in text


def test_the_worksheet_omits_things_used_as_bought() -> None:
    """Thirty-odd ingredients at 1.0 would bury the handful that matter."""
    text = worksheet(REFERENCE)
    assert "banana" not in text
    assert "olive_oil" not in text


def test_cooked_requirements_do_not_depend_on_yield() -> None:
    """The plan needs what it needs; the factor only decides what to buy."""
    cooked = cooked_requirements(REFERENCE)
    # Three lunches at 120 g of cooked turkey each.
    assert cooked["turkey_thigh"] == Decimal(360)


def test_what_if_reports_the_change_in_one_direction(capsys) -> None:  # type: ignore[no-untyped-def]
    """A higher yield means less waste, so less to buy."""
    text = what_if(REFERENCE, {"turkey_thigh": Decimal("0.72")})
    assert "turkey_thigh" in text
    assert "-" in text  # the requirement goes down


def test_what_if_on_an_unknown_ingredient_says_so() -> None:
    with pytest.raises(KeyError, match="Unknown ingredient"):
        what_if(REFERENCE, {"not_a_food": Decimal("0.5")})


def test_the_command_runs(capsys) -> None:  # type: ignore[no-untyped-def]
    assert main([]) == 0
    assert "Yield factors needing review" in capsys.readouterr().out


def test_the_command_rejects_an_impossible_factor() -> None:
    with pytest.raises(SystemExit):
        main(["--what-if", "turkey_thigh=9"])
