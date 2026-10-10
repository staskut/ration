"""The package is installed and importable, not merely present on disk."""

import ration


def test_package_exposes_a_version() -> None:
    assert ration.__version__ == "0.1.0"
