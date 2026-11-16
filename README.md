# Ration

A weekly nutrition planner for two people: one who **builds** the plan and one
who **eats** it.

It replaces a Markdown document. A family member needed a structured eating
plan, so one was written by hand after an interview — seven days, every meal,
with calorie and protein budgets, a shopping list and a batch-cooking
schedule. It worked, and it was unmaintainable. Swapping one dinner meant
recomputing that day's totals, re-checking the week's fish-twice rule, editing
the shopping list, and re-deriving raw weights from cooked ones. Each edit was
an opportunity to get the arithmetic quietly wrong.

This system does that arithmetic. The planner keeps a library of reusable
meal **modules** and arranges them into days; the system computes totals,
validates them against the planner's budgets and dietary rules, and derives
the shopping list and the prep plan. The follower opens one screen, sees
today, and taps to rate a meal.

> **Not medical advice.** The system never computes a nutrition target and
> never labels anything "healthy", "safe" or "balanced". It stores the
> planner's targets and reports whether a plan meets them. That is the whole
> of its opinion.
>
> [`docs/sample-plan-6-days.md`](docs/sample-plan-6-days.md) is **de-identified
> demo data**. No real plan is in this repository.

## What it computes

Four engines, all pure functions in [`backend/src/ration/domain/`](backend/src/ration/domain/):

| | |
|---|---|
| **Totals** | line → entry → slot → day, in `Decimal` throughout |
| **Validation** | calorie and protein budgets, frequency rules, unplanned slots — as codes with parameters, never sentences |
| **Shopping** | cooked grams → raw, via per-ingredient yield factors, merged by ingredient id |
| **Prep** | which batches to cook, when, and how long they last |

Four of the design decisions behind those are load-bearing and non-obvious:

- **Cooked weight is stored; raw weight is derived.** Recipes describe what
  ends up on the plate. The shopping list is what you buy. A `yield_factor`
  converts, inside the shopping engine only — 170 g of cooked chicken is about
  243 g raw. Storing both lets them disagree.
- **`batch_portions` never multiplies the shopping list.** A lunch cooked once
  for three days appears as three plan entries, one per day. Multiplying by
  the batch size as well triple-counts it.
- **Protein is a floor, not a band.** Exceeding a calorie target defeats the
  goal; exceeding a protein target does not.
- **Nutrition values are reference figures, never tuned to make a plan pass.**
  This one cost a day to get right and is the most important thing in the
  repository — see [below](#what-went-wrong).

## Try it

**<https://ration-plan-staging.fly.dev>** — the demo, carrying the
de-identified reference plan.

| Role | Email | Password | Sees |
|---|---|---|---|
| Planner | `planner@ration.example` | `correct-horse-battery` | plan board, module library, validation, shopping list |
| Follower | `follower@ration.example` | `correct-horse-battery` | today, and a tap to rate |

Open the two in separate browser profiles to watch a planner's edit land on
the follower's screen over the WebSocket.

The planner's board expects a desktop viewport; the follower's screens are
designed for a phone and tested at 375px.

Production is at **<https://ration-plan.fly.dev>** and is **deliberately
empty** — it holds one real person's dietary information, so the demo
credentials do not work there and the reference plan is never seeded into
it. The release command runs migrations on both and the seed only outside
production.

Both machines suspend when idle, so the first request after a quiet spell
takes about a second.

## Status

| | |
|---|---|
| Backend, frontend, database, containerisation, CI/CD | done |
| Deployed | staging and production, on Fly.io with Neon Postgres |
| Issues | 50 of 54 closed; the rest are [#54](https://github.com/staskut/ration/issues/54) (needs a kitchen scale) and the three deployment ones now being verified |

## Run it yourself

### Docker

`.env` is gitignored, so a fresh clone needs one. The session secret has no
committed default on purpose — a default in the repository is a default that
eventually reaches a deployment.

```bash
cp .env.example .env
python3 -c "import secrets; print('RATION_SESSION_SECRET=' + secrets.token_urlsafe(32))" >> .env
docker compose up --build
```

Then <http://localhost:8000>. If something else already holds port 8000, set
`RATION_PORT` in `.env`. Postgres starts first, the app waits on its
health check, migrations run, and the reference plan is seeded.

**Demo accounts** — both seeded, both with the password
`correct-horse-battery` (override with `RATION_DEV_PASSWORD`):

| Role | Email | Sees |
|---|---|---|
| Planner | `planner@ration.example` | the plan board, module library, validation, shopping list |
| Follower | `follower@ration.example` | today, and a tap to rate |

Open the two in separate browser profiles to watch a planner's edit land on
the follower's screen over the WebSocket.

The seeded password exists only because `RATION_DEV_PASSWORD` was set. Without
it the accounts get an unusable placeholder hash — so a deployment that
happens to run the seed cannot hand out a known password. Production refuses
to seed at all.

### With telemetry

```bash
docker compose -f observability/compose.yaml up
```

The same stack plus OpenTelemetry Collector, Prometheus, Loki, Tempo and a
Grafana at <http://localhost:3000> that needs no login. One request to the
shopping list produces metrics, a trace whose spans are the pipeline stages,
and log lines carrying the same trace id.
[`observability/README.md`](observability/README.md) walks through all three
with the queries to paste.

### From source

Prerequisites: **Python 3.12+** with [uv](https://docs.astral.sh/uv/),
**Node 20+**, and Postgres if you want it (SQLite is the default).

```bash
# backend
cd backend
uv sync
uv run alembic upgrade head
RATION_DEV_PASSWORD=correct-horse-battery uv run ration-seed
uv run uvicorn ration.api.app:application --reload
```

```bash
# frontend, in a second terminal
cd frontend
npm install
npm run dev
```

The frontend dev server proxies `/api` to port 8000, so use the Vite URL it
prints.

## Tests

```bash
make test-unit                  # domain only, no database       ~3 s
make test-integration           # API and repositories, SQLite   ~50 s
make test-integration-postgres  # the same suite, on Postgres
make test-e2e                   # two browsers, compose stack    ~20 s
make lint                       # ruff, import contract, oxlint, tsc, client drift
```

| Layer | Count | Proves |
|---|---|---|
| Backend unit | 317 | the arithmetic and the rules |
| Backend integration | 279 | the API matches the contract |
| Frontend unit | 100 | the client's own logic |
| End-to-end | 8 | two people, two browsers, one stack |

Three of the unit tests are **golden**: their expected values were written by
a person, in the reference plan document, before the code existed. The oracle
can disagree with the implementation, which is the only arrangement in which
agreement means anything.

[`docs/testing.md`](docs/testing.md) covers the layers and what each has
actually caught.

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│ React 19 · TypeScript · Vite · TanStack Query · Tailwind     │
│                                                              │
│   features/  ──▶  lib/queries.ts  ──▶  src/api/  GENERATED   │
└──────────────────────────────────────────────────────────────┘
                            │  HTTP + WebSocket
┌──────────────────────────────────────────────────────────────┐
│ FastAPI · Python 3.12                                        │
│                                                              │
│   api/  ──▶  repositories/  ──▶  SQLAlchemy  ──▶  Postgres   │
│     │                                                        │
│     └──▶  domain/     PURE — no framework, no I/O            │
└──────────────────────────────────────────────────────────────┘

Docker multi-stage  →  one image, ~250 MB, non-root
GitHub Actions      →  six parallel jobs, then a gated deploy
```

Three boundaries are enforced by CI rather than by convention, because a
boundary nobody checks is a preference:

- **`domain/` is pure.** An import-linter contract fails the build if it
  imports `fastapi`, `sqlalchemy`, `api` or `repositories`. All arithmetic
  lives there, as functions from frozen dataclasses to frozen dataclasses.
- **[`openapi.yaml`](openapi.yaml) is hand-written and comes first.** It is
  the contract, not a description of the code. The TypeScript client is
  generated from it and CI fails if the committed client differs from a fresh
  generation.
- **No component imports `src/api/` directly.** They use hooks from
  `lib/queries.ts`, so refetching and cache invalidation exist in one place.

One more that is a convention and matters as much: **`Decimal` everywhere, never
`float`.** A test walks the AST of the domain package looking for float
literals. Rounding drift in a shopping list destroys trust in the whole output.

## What went wrong

Written up properly in [`docs/ai-usage-report.md`](docs/ai-usage-report.md);
the short version, because it is the most useful part of this repository.

**The catalog was fitted to the plan.** Nutrition values had been adjusted —
by me, incrementally, each change defensible on its own — until every dish
matched the figure the source document stated for it. The suite was green.
That was the problem: the instrument had been bent until it agreed with the
thing it was measuring, and a plan that *cannot* fail validation cannot be
validated.

Replacing them with reference values turned the reference week from clean into
2 errors and 11 warnings. All true. And it surfaced something no self-consistent
fixture could have: **the plan feeds least on the two days that end with
resistance training.**

The related temptation — adjusting the profile's *budgets* until the plan
passed — was explicitly refused. It is the same circularity moved one table
across.

**Three acceptance criteria were wrong**, all written before the data they
described existed, all corrected in the open rather than quietly implemented
around. [`docs/acceptance-audit.md`](docs/acceptance-audit.md) audits all 184
criteria of the closed issues.

**A green suite was consistent with a feature being entirely absent.** No
WebSocket broadcast had ever fired — a synchronous FastAPI handler runs in a
threadpool worker with no event loop, and a `suppress` swallowed the error.
238 integration tests passed. None of them observed a socket.

## Documents

| | |
|---|---|
| [`docs/product-spec.md`](docs/product-spec.md) | the PRD. What and why. Owns scope |
| [`docs/hld.md`](docs/hld.md) | architecture and eight numbered decisions |
| [`docs/lld.md`](docs/lld.md) | schema, domain signatures, endpoints |
| [`docs/testing.md`](docs/testing.md) | the three layers, and what they caught |
| [`docs/deployment.md`](docs/deployment.md) | Fly and Neon, secrets, rollback |
| [`docs/release-process.md`](docs/release-process.md) | commit to production, and back |
| [`docs/decisions.md`](docs/decisions.md) | D1–D10, closed during implementation, with their cost |
| [`docs/acceptance-audit.md`](docs/acceptance-audit.md) | every closed issue against its own criteria |
| [`docs/ai-usage-report.md`](docs/ai-usage-report.md) | how this was built with AI, including the failures |
| [`docs/process.md`](docs/process.md) | the PM / Engineer / QA split and why it is strict |
| [`AGENTS.md`](AGENTS.md) | the context file agents read first |

## Licence

Unlicensed; a course project. The reference plan is de-identified demo data.
