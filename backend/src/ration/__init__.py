"""Ration — a weekly nutrition planner.

The package is layered; see AGENTS.md and docs/hld.md.

    domain/        pure business logic, no I/O and no framework imports
    repositories/  database access, maps rows to and from domain types
    api/           HTTP and WebSocket surface

Nothing in ``domain`` may import a framework. CI enforces this.
"""

__version__ = "0.1.0"
