def test_deliberately_failing() -> None:
    assert 1 == 2, "deliberate failure to prove CI turns red"
