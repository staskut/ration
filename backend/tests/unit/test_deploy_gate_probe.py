"""TEMPORARY: proves a red suite blocks the deploy (#51). Reverted immediately."""


def test_this_fails_on_purpose() -> None:
    assert 1 == 2, "deliberate failure to prove the deploy gate holds"
