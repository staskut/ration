"""Telemetry: traces now, metrics and structured logs alongside them.

Three rules hold across this package and are the reason it is a package rather
than a few lines in `api/`:

*   **Off by default.** HLD §6 — off locally, on under Compose, on in staging
    and production. Off means nothing is installed.
*   **It knows nothing about the data it observes.** An import-linter contract
    forbids this package from importing `ration.domain`, `ration.repositories`
    and `ration.api`, so no helper here can ever be handed a plan, an
    ingredient or an ORM row to format.
*   **Every key is on an allowlist.** `attributes.ALLOWED` is the whole of what
    telemetry may carry (HLD §8).
"""
