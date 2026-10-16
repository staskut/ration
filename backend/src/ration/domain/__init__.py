"""Pure business logic: nutrition totals, validation, shopping list, prep plan.

Everything here is a function from frozen dataclasses to frozen dataclasses. No
I/O, no database, no HTTP, no framework imports — see docs/hld.md AD-1. The
import-linter contract in pyproject.toml enforces it, so a stray `import
fastapi` fails CI rather than quietly coupling the layers.

This is where the arithmetic lives, which makes it where the bugs would live.
Keeping it pure is what lets the heaviest test suite in the project run in
milliseconds without fixtures.
"""
