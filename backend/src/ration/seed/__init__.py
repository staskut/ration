"""The reference plan as checked-in fixture data, plus its loader.

The YAML here is a transcription of docs/sample-plan-6-days.md. It does three
jobs at once: demo data, the database seed, and the oracle the golden tests
compare against. Keeping it to one artifact is what stops the demo and the
tests from drifting apart.
"""

from ration.seed.loader import ReferenceData, load_reference

__all__ = ["ReferenceData", "load_reference"]
