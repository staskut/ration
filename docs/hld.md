# Ration — High-Level Design

> Companion to [`product-spec.md`](product-spec.md), which is the PRD and owns *what* and *why*.
> This document owns *how*, at the level of components and boundaries. Detailed schema, signatures,
> and endpoints are in [`lld.md`](lld.md).

## 1. Shape of the system

```
┌─────────────────────────────┐   ┌─────────────────────────────┐
│  Planner UI (desktop)       │   │  Follower UI (mobile)       │
│  catalog · modules · plan   │   │  today · shopping · rate    │
│  builder · validation       │   │                             │
└──────────────┬──────────────┘   └──────────────┬──────────────┘
               │                                 │
               └──────────────┬──────────────────┘
                              │
                 ┌────────────▼────────────┐
                 │   api/client (generated │   one module, generated from
                 │   from openapi.yaml)    │   the contract, drift-checked
                 └────────────┬────────────┘
                              │  HTTPS + WebSocket
                 ┌────────────▼────────────┐
                 │   FastAPI               │
                 │   routers · schemas     │   HTTP, auth, serialisation
                 │   · ws hub              │
                 └────────────┬────────────┘
                              │
            ┌─────────────────┼─────────────────┐
            │                 │                 │
   ┌────────▼───────┐ ┌───────▼────────┐ ┌──────▼────────┐
   │ domain/        │ │ repositories/  │ │ extractors/   │
   │ PURE           │ │ SQLAlchemy     │ │ LLM + fallback│
   │ no I/O         │ │ Alembic        │ │ behind a port │
   └────────────────┘ └───────┬────────┘ └───────────────┘
                              │
                     ┌────────▼────────┐
                     │ SQLite (dev)    │
                     │ Postgres (prod) │
                     └─────────────────┘
```

Two UI surfaces, one API, one generated client, one database. The load-bearing boundary is the
one around `domain/`.

## 2. Components

| Component | Responsibility | Must not |
|---|---|---|
| `domain/` | Nutrition totals, validation, shopping list, prep plan, substitution. Pure functions over frozen dataclasses. | Import FastAPI, SQLAlchemy, or anything that touches I/O |
| `repositories/` | Load aggregates out of the database into domain types; persist changes | Contain business rules |
| `api/` | HTTP, auth, request/response schemas, WebSocket fan-out | Contain arithmetic |
| `extractors/` | Turn pasted text into a draft module | Write to the database directly |
| `frontend/src/api/` | The only place a network call is made | Be hand-written |
| `frontend/src/features/` | Planner and follower screens | Call `fetch` |

## 3. Architectural decisions

Each records what was chosen, why, and what was rejected — so a later change reads as a
deliberate reversal.

### AD-1 — The domain core is pure and framework-free

Validation, shopping list, prep plan, and substitution are functions from frozen dataclasses to
frozen dataclasses. No ORM objects cross into `domain/`; repositories map at the edge.

*Why:* this is where all the value and nearly all the bugs live. Pure functions let the heaviest
test suite in the project run with no database, no fixtures, and no HTTP — milliseconds per case,
so the awkward cases actually get written.

*Rejected:* computing totals in SQL, or hanging methods off ORM models. Both are faster to write
and make the arithmetic untestable without a database, which is how the arithmetic ends up wrong.

*Enforced by:* an import-linter contract in CI — `domain` may not import `api`, `repositories`,
`sqlalchemy`, or `fastapi`.

### AD-2 — `openapi.yaml` is the contract, and drift is a build failure

The spec is written and committed first. The backend is implemented against it; the frontend's
client is generated from it.

*Why:* criterion 5 of the course rubric asks that OpenAPI be *used as the contract*, not merely
present. A generated client that CI regenerates and diffs makes that structurally true.

*Rejected:* generating `openapi.yaml` from FastAPI decorators. That inverts the dependency — the
contract becomes a description of whatever the code does, and can never be violated, which also
means it can never catch anything.

*Enforced by:* `make check-client` regenerates the TypeScript client and fails on a diff.

### AD-3 — Cooked weight is canonical; raw weight is derived

Module lines store cooked grams. `yield_factor` converts to raw inside the shopping engine only.

*Why:* cooked grams are what the follower weighs when packing containers, so it is the number
that must be exact. Raw weight matters only when shopping.

*Rejected:* storing both. Two numbers that must agree will eventually disagree.

### AD-4 — Database-agnostic persistence, SQLite in dev, Postgres everywhere else

SQLAlchemy 2 with Alembic migrations. No database-specific SQL, no Postgres-only column types in
the MVP schema.

*Why:* Module 2 ends on SQLite, Module 3 swaps to Postgres. If that swap is a rewrite, it eats a
week.

*Rejected:* Postgres-only from day one (slower local loop, Docker required for every test run);
SQLite in production (no concurrent writers, and realtime assumes two).

### AD-5 — One deployable image

A multi-stage Dockerfile builds the frontend to static assets and serves them from the same
FastAPI process that serves the API.

*Why:* one deploy, one URL, no CORS, and — most importantly — `docker-compose.yml` then describes
the thing that is actually deployed. A compose file that doesn't match production is a lie in the
README.

*Rejected:* separate frontend hosting (Lovable, Vercel, a second Fly app). Two pipelines, a CORS
surface, and a compose file that no longer represents the system.

*Cost accepted:* frontend and backend cannot be scaled independently. At this size that is not a
cost.

### AD-6 — Realtime is a per-plan broadcast of invalidation, not of state

On a write, the API publishes `{plan_id, changed: [...]}` to subscribers of that plan. Clients
refetch what changed. Messages carry no payload.

*Why:* the alternative is keeping a CRDT or an op-log consistent between two clients, for a
feature whose actual requirement is "the follower never acts on a stale plan". Refetch-on-signal
delivers that in a fraction of the code.

*Rejected:* full state push (every message carries the plan, and the shapes must stay in sync
with the REST responses); operational transform (vastly more machinery than two users need).

### AD-7 — Model extraction sits behind a port

`RecipeExtractor` is a protocol. `ClaudeExtractor` calls the API; `HeuristicExtractor` parses
structured text; `FakeExtractor` returns fixtures in tests.

*Why:* keeps one optional AI feature from making the test suite depend on a network call, an API
key, or a non-deterministic response.

*Constraint:* the draft is always reviewed by the planner before it is saved. Nothing reaches the
database without a human accepting it.

### AD-8 — Auth is session cookies, two roles, one pairing

Two users exist: planner and follower, paired to one profile. HttpOnly cookie sessions.

*Why:* the follower's 30-second budget (PRD §2.1) rules out anything that logs them out weekly.
No third party, no token refresh dance in the client.

*Rejected:* JWT in `localStorage` (XSS-exposed, and needs refresh plumbing for no benefit at two
users); OAuth (an external dependency for an audience of two).

## 4. Data flow

### Building and validating a plan

```
planner edits an entry
  → PATCH /plans/{id}/entries/{entry_id}
  → repository writes, loads the full plan aggregate
  → domain.validate(plan, profile, catalog)
  → response carries the entry AND the fresh validation report
  → ws broadcast {plan_id, changed: ["entries", "validation"]}
```

Validation is returned with the mutation rather than fetched separately. It is cheap (one plan,
in memory) and the planner should never see a plan and a stale report together.

### Generating a shopping list

```
GET /plans/{id}/shopping-list
  → load plan + catalog
  → domain.shopping_list(plan, catalog)
      entries → cooked grams (× portion_factor, × batch_portions)
              → ÷ yield_factor → raw grams
              → merge by ingredient_id
              → round up to package_size
              → group by shop_section
  → merge in the follower's check-off state
```

Check-off state is persisted server-side per plan, not in browser storage — the follower may
shop on a different device than they planned on, and §2.1 forbids anything they must maintain.

### Follower rating a meal

```
tap → PUT /plans/{id}/entries/{entry_id}/feedback {rating}
    → status inferred to "tried"
    → ws broadcast
```

One request, one tap, no form.

## 5. Technology

| Layer | Choice | Rationale |
|---|---|---|
| Backend | Python 3.12, FastAPI, Pydantic v2 | Course default; typed request/response maps onto OpenAPI |
| ORM | SQLAlchemy 2 + Alembic | Database-agnostic (AD-4); real migrations |
| Frontend | React 18, TypeScript, Vite | Course default; two surfaces in one build |
| Data fetching | TanStack Query | Cache invalidation on a WebSocket signal is a one-liner (AD-6) |
| Styling | Tailwind | Mobile-first matters more here than component breadth |
| Backend tests | pytest | Unit (domain), integration (API + real DB) |
| Frontend tests | Vitest + Testing Library | Core logic and the two critical screens |
| E2E | Playwright | Two browser contexts for the collaborative flow |
| Packaging | Multi-stage Docker, Compose | AD-5 |
| CI/CD | GitHub Actions | Lint, test, build, then deploy on green |
| Hosting | Fly.io + Neon Postgres | Managed Postgres, migrations on release, cheap staging |
| Telemetry | OpenTelemetry → Collector → Prometheus / Loki / Tempo → Grafana | Course Module 4 |

## 6. Environments

| | Local | Compose | Staging | Production |
|---|---|---|---|---|
| Database | SQLite file | Postgres container | Neon branch | Neon |
| Frontend | Vite dev server, proxied | Built into the image | Built | Built |
| Migrations | `alembic upgrade head` | On container start | On release | On release |
| Telemetry | Off | Full stack in `observability/compose.yaml` | On | On |
| Seed | Reference plan | Reference plan | Reference plan | Empty |

The reference plan from `sample-plan-6-days.md` seeds every non-production environment. It is
simultaneously the demo, the fixture, and the regression test (PRD §9).

## 7. Observability

The instrumented path is `GET /plans/{id}/shopping-list` — the most computation-heavy endpoint
and the one whose failure the follower notices, standing in a shop.

- **Metrics:** request rate, error rate, p95 latency by route.
- **Traces:** one span per pipeline stage of §4, so a slow or failing stage is visible rather
  than inferred.
- **Logs:** structured, correlated by trace ID. Never contain profile data, targets, or feedback.
- **Alert:** 5xx rate on that route over 5 minutes, carrying the deployed version in the payload.

The staged incident for Module 4 is a release in which an unrecognised unit reaches the raw-weight
conversion and raises — a real failure mode of §4's pipeline, not a synthetic one.

## 8. Security boundaries

- Every plan-scoped route authorises against the profile pairing. A follower may read the plan and
  write only feedback and shopping check-offs.
- WebSocket subscription is authorised on connect and scoped to one plan.
- The database holds dietary and health-adjacent data for one real person. It is never logged,
  never included in telemetry attributes, and never sent to the extraction model — extraction sees
  only the recipe text the planner pastes.
- No secrets in the image. Configuration via environment, `.env.example` committed, `.env` ignored.
- The de-identified reference plan is the only plan data in the repository. Real plan content
  lives in the database, never in Git.
