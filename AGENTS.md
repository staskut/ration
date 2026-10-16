# Ration

A weekly nutrition planner for two people: a **planner** who builds the plan and a **follower**
who eats it. The planner maintains a library of reusable meals (modules); the system computes
validation against calorie/protein budgets and dietary rules, a shopping list, and a prep plan.
It replaces a hand-maintained Markdown document.

## Documents

Read these before changing anything they cover.

- `docs/product-spec.md` — the PRD. What and why. **Owns scope.**
- `docs/hld.md` — architecture, component boundaries, eight numbered decisions (AD-1…AD-8)
- `docs/lld.md` — schema, domain signatures, endpoints, test plan
- `docs/decisions.md` — decisions closed during implementation (D1…D10), with their cost
- `docs/acceptance-audit.md` — closed issues checked against their own criteria
- `docs/testing.md` — the three test layers, the golden tests, and what they have caught
- `docs/deployment.md` — Fly and Neon, secrets, rollback
- `docs/release-process.md` — commit to production, and back
- `docs/ai-usage-report.md` — how this was built with AI, including the failures
- `docs/mvp-plan.md` — milestones and sequencing
- `docs/tasks.md` — the backlog
- `docs/process.md` — how work is organized
- `docs/sample-plan-6-days.md` — the de-identified reference plan. Fixture, demo, and oracle.

## Commands

Backend commands run in `backend/`.

- `uv sync` — install dependencies
- `uv run pytest` — the whole suite
- `uv run pytest tests/unit` — domain tests only, no database
- `uv run pytest tests/unit/test_shopping.py` — one test file
- `uv run ruff check . && uv run ruff format --check .` — lint
- `uv run alembic upgrade head` — migrations
- `uv run ration-seed` — load the reference plan
- `uv run ration-yields` — yield factor worksheet; `--what-if slug=0.7` to preview a change

Frontend commands run in `frontend/`.

- `npm test` — Vitest
- `npm run build` — production build
- `npm run gen:client` — regenerate the API client from `openapi.yaml`

Repo root:

- `make check-client` — regenerate the client and fail on a diff
- `docker compose up` — full system with Postgres

## Architecture

```
frontend/src/features/  →  lib/queries.ts  →  src/api/ (GENERATED)
                                                    │ HTTP + WS
backend/src/ration/      api/  →  repositories/  →  database
                                   ↓
                                 domain/   PURE — no I/O
```

### Two boundaries that are enforced, not suggested

**`domain/` is pure** (HLD AD-1). It may not import `fastapi`, `sqlalchemy`, `api`, or
`repositories`. All arithmetic — totals, validation, shopping list, prep plan —
lives there, as functions from frozen dataclasses to frozen dataclasses. Handlers and
repositories contain no business rules. CI enforces this with an import-linter contract.

**`openapi.yaml` is hand-written and comes first** (HLD AD-2). It is the contract, not a
description of the code. The TypeScript client is generated from it, and CI fails if the
committed client differs from a fresh generation. Do not generate `openapi.yaml` from FastAPI
decorators.

No React component may import `src/api/` directly — components use hooks from `lib/queries.ts`.
An ESLint rule enforces this.

## Scope decisions

These are settled. They look like details and are not. If a task seems to require reversing one,
stop and ask rather than implementing the reversal — the reasoning is in `docs/product-spec.md` §6.

1. **Cooked weight is stored; raw weight is derived.** Module lines carry cooked grams.
   `yield_factor` converts to raw inside the shopping engine only. Never store both.
2. **No volume↔mass conversion.** Grams and millilitres do not merge. Quantities in incompatible
   dimensions appear as separate amounts on one line. Do not introduce a density table.
3. **Ingredients merge on `ingredient_id`, never on name.** Aliases resolve at entry time.
4. **`batch_portions` does not multiply in the shopping list.** A lunch cooked once for three
   days appears as three plan entries, one per day. Multiplying by `batch_portions` as well
   triple-counts it. See `docs/lld.md` §3.
5. **A slot holds several entries** — one `main`, any number of `side`. Budgets, totals, and
   validation apply to the slot's **sum**, never to one entry.
6. **A plan is exactly seven days.** Frequency rules scope to one plan. No rolling windows.
7. **The follower never maintains state.** No pantry inventory, no eaten-log, no weight tracking.
8. **The system never computes a nutrition target.** It stores and enforces the planner's.
   No "healthy", "safe", or "balanced" labels anywhere in the UI.
9. **The follower's daily interaction stays under 30 seconds**, and rating a meal is one tap.
   This is an acceptance criterion, not an aspiration.
10. **Nutrition values are reference figures for the preparation a line describes, never
    tuned to make a plan pass.** Meat and fish use *cooked* values, because module lines
    carry cooked weight. A catalog fitted to the plan cannot report a plan that fails,
    which is the one thing this system is for. See `docs/decisions.md` D1.
11. **Protein is a floor, not a band.** `protein_max` may be null. Exceeding a calorie
    target defeats the goal; exceeding a protein target does not (D2).
12. **Yield may be overridden per module line** (D4). Null means use the ingredient's own
    factor. Yield belongs to an ingredient *and a preparation*.
13. **Yield factors are parameters, not constants** (D9). They are expected to change as
    they get measured. `yield_source` records whether each is `as_purchased`, `estimated`
    or `measured`; keep it honest. When a golden shopping expectation moves because a
    factor changed, update the expectation and say so — that is data, not a regression.

## Conventions

- Python 3.12, type hints everywhere, `Decimal` for all nutrition and weight arithmetic. Never
  `float` — rounding drift in a shopping list destroys trust in the whole output.
- Domain validation findings carry a `message_key` and `params`, never a formatted sentence. The
  follower's UI is Russian; English strings in the domain layer are untranslatable.
- Unit tests for `domain/` touch no database. Integration tests use real Postgres.
- Tests the reference plan must satisfy are "golden" tests — their expected values come from
  `docs/sample-plan-6-days.md`, written by a human before the code existed. If a golden test
  fails, the engine is wrong until proven otherwise.
- Conventional commits. Commit regularly.
- Follower-facing UI strings are Russian; code, comments, docs, and planner UI are English.

## Rules

- Dependencies are added in `pyproject.toml` or `package.json`. **Do not add one without asking.**
- Do not edit `frontend/src/api/` by hand — it is generated.
- Do not commit real plan data. `docs/sample-plan-6-days.md` is the only plan content in the
  repo and it is de-identified. The database holds real data; Git never does.
- Do not put profile data, targets, or feedback into logs or telemetry attributes.
- Work one task at a time, from the GitHub issues. Read its acceptance criteria before starting
  and again before finishing.
- **Follow the role you are in** (`docs/process.md`, `docs/team/`). They are separate on purpose:
  - **PM** grooms before anyone implements, and is the only role that changes an acceptance
    criterion. If a criterion is wrong, comment on the issue and let it be amended — do not
    quietly implement something else and explain it in a commit message.
  - **Engineer** implements one groomed task and **does not close the issue**. Never put
    `Closes #N` in a commit: it closes the issue on merge and skips QA entirely. Reference the
    issue as `#N` and leave it open with a comment saying what was done.
  - **QA** checks each criterion against the running code, posts a PASS/FAIL verdict comment,
    changes nothing, and only a PASS closes the issue.
