# Ration — MVP Plan

> Delivery plan. Each task becomes a GitHub issue, groomed with
> [`task-template.md`](task-template.md) before implementation, per [`process.md`](process.md).
> Scope and rationale: [`product-spec.md`](product-spec.md) · [`hld.md`](hld.md) · [`lld.md`](lld.md).

## 1. What MVP means here

**MVP is reached when the planner builds week 2 in Ration instead of editing Markdown, and the
follower opens Today instead of the document.** That is PRD §9's adoption test, and it is the only
definition that matters — a feature that doesn't move it is not in the MVP.

Concretely, the MVP covers PRD stories **S1–S9a**. Substitution (S10), prep plan (S11), and module
import (S12) are deliberately out, for reasons in §5.

## 2. Sequencing principle

**Domain core first, before any HTTP or database.** It holds the arithmetic, all the risk, and
nearly all the value. It is also the only part that can be fully tested in milliseconds, so
getting it right before anything is built on it is the cheapest possible ordering.

The golden tests (LLD §6) come with it, which means by the end of M1 the hardest question —
*does this compute the right shopping list?* — is answered against a human-written expected
result, with no framework in the way.

```
M0 foundations → M1 domain core → M2 contract & API → M3 frontend → M4 ship
                                                                      ↓
                                                    M5 observability → M6 agent pack
```

M5 and M6 are course modules 4 and 5. They are not MVP, but they are project deliverables and
are planned here so the MVP doesn't get built in a way that makes them awkward.

## 3. Backlog

Sizes: **S** ≈ half a day · **M** ≈ a day · **L** ≈ two or more.

### M0 — Foundations

| # | Task | Size | Depends on |
|---|---|---|---|
| 1 | Repo skeleton: `uv` + `pyproject.toml`, ruff, pytest, Vite + TS scaffold, Makefile | S | — |
| 2 | `AGENTS.md`: architecture, commands, conventions, and PRD §6 scope decisions as durable agent context | S | 1 |
| 3 | CI skeleton — lint + test on PR, no deploy yet | S | 1 |
| 4 | Import-linter contract enforcing AD-1 (`domain` imports nothing framework) | S | 1 |

**Done when:** `make test` and `make lint` pass on an empty project, and CI runs them on a PR.

### M1 — Domain core

| # | Task | Size | Depends on |
|---|---|---|---|
| 5 | `domain/types.py` — frozen dataclasses, Decimal throughout | S | 4 |
| 6 | `domain/units.py` — gram/ml handling; no cross-dimension conversion (PRD §6.2) | S | 5 |
| 7 | `domain/nutrition.py` — line → module → entry → slot → day totals | M | 5 |
| 8 | **Reference fixture**: transcribe `sample-plan-6-days.md` to seed YAML — ingredients, yields, 14 modules, profile, 7-day plan, §14 feedback | L | 5 |
| 9 | `domain/shopping.py` — cooked → raw → merge → round → group | M | 7, 8 |
| 10 | `test_golden_shopping_list` against §12 of the reference | M | 9 |
| 11 | `domain/validation.py` — all 11 codes in LLD §3 | L | 7, 8 |
| 12 | `test_golden_validation_clean` + every case in LLD §6 | M | 11 |

**Done when:** the golden shopping list matches the reference document line for line, validation
is clean on the reference plan, and the whole suite runs without a database.

> Task 8 is the one most likely to be under-estimated. It is manual transcription of ~40
> ingredients with nutrition values and yield factors, and it is the foundation of every golden
> test. Budget it honestly and do it carefully — an error here looks like an engine bug forever
> after.

### M2 — Contract and API

| # | Task | Size | Depends on |
|---|---|---|---|
| 13 | `openapi.yaml` — every MVP endpoint in LLD §4, written before the handlers (AD-2) | L | 11 |
| 14 | SQLAlchemy models + initial Alembic migration (LLD §2) | L | 13 |
| 15 | Repositories: load a plan aggregate into domain types, persist entries | M | 14 |
| 16 | Auth: session cookies, two roles, `/auth/*` | M | 14 |
| 17 | Seed command from the task-8 YAML, idempotent | M | 14, 8 |
| 18 | Ingredient + module endpoints, alias-aware search | M | 15, 16 |
| 19 | Profile, budget, and rule endpoints | S | 15, 16 |
| 20 | Plan endpoints — create (7 days), days, entries, one-`main`-per-slot conflict | L | 15, 16 |
| 21 | Derived endpoints — validation, shopping list, check-off state | M | 20, 9, 11 |
| 22 | Feedback endpoint — upsert, infers `tried` | S | 20 |
| 23 | WebSocket hub — per-plan invalidation (AD-6) | M | 20 |
| 24 | Integration tests: every endpoint, both role boundaries, migrations | L | 18–23 |

**Done when:** the API serves the reference plan, integration tests pass against real Postgres,
and no handler contains arithmetic.

### M3 — Frontend

| # | Task | Size | Depends on |
|---|---|---|---|
| 25 | Client generation from `openapi.yaml` + `make check-client` drift gate in CI | M | 13 |
| 26 | `lib/queries.ts` + the ESLint rule banning `api/` imports outside it (LLD §5) | S | 25 |
| 27 | i18n: ru/en, validation `message_key` → sentence | M | 25 |
| 28 | Planner: ingredient catalog CRUD | M | 26 |
| 29 | Planner: module editor with computed totals | L | 26, 28 |
| 30 | Planner: plan builder — 7 days × slots, several entries per slot | L | 26, 29 |
| 31 | Planner: validation panel, errors before warnings, explicit empty state | M | 27, 30 |
| 32 | **Follower: Today** — slot times, portions, `home_only` marks, under 2s on mobile | M | 26, 27 |
| 33 | Follower: shopping list — grouped, tappable, persists | M | 26, 27 |
| 34 | Follower: one-tap rating; bloating/satiety behind an optional second tap | S | 32 |
| 35 | WebSocket → query invalidation wiring | S | 26, 23 |
| 36 | Frontend unit tests — finding i18n, shopping grouping, Today assembly | M | 31–34 |

**Done when:** both surfaces work against the real API, no component calls `fetch`, and the
drift gate fails if `openapi.yaml` and the client disagree.

> Build **Today (32) before the planner screens** if time gets tight. It is the screen that
> decides adoption, and it is useless to discover problems with it in the last week.

### M4 — Ship

| # | Task | Size | Depends on |
|---|---|---|---|
| 37 | Multi-stage Dockerfile — frontend build → static, served by FastAPI (AD-5) | M | 32 |
| 38 | `docker-compose.yml` — app + Postgres, migrations on start, seeded | M | 37, 17 |
| 39 | Playwright E2E: planner edits → follower sees; follower rates → planner sees | L | 35, 38 |
| 40 | Fly.io + Neon: staging and production, migrations on release | L | 38 |
| 41 | CD gated on green CI; post-deploy smoke test | M | 40, 3 |
| 42 | `docs/testing.md`, `docs/deployment.md`, `docs/release-process.md` with a rollback path | M | 41 |
| 43 | `README.md` — problem, architecture, run/test/deploy, public URL | M | 41 |
| 44 | `docs/ai-usage-report.md` — prompts, delegation, context files, manual review, verification | M | 43 |

**Done when:** a stranger can clone, `docker compose up`, and reach a working app; merging to
main deploys after tests pass; the public URL works.

### M5 — Observability *(course module 4, not MVP)*

| # | Task | Size |
|---|---|---|
| 45 | OTel instrumentation of `GET /plans/{id}/shopping-list`, one span per pipeline stage | M |
| 46 | Collector → Prometheus / Loki / Tempo / Grafana in `observability/compose.yaml` | L |
| 47 | Dashboard + alert on 5xx rate carrying the deployed version | M |
| 48 | Staged incident: unrecognised unit reaches raw-weight conversion; evidence script, responder task, autonomy policy, runbooks | L |
| 49 | `docs/operations-and-security-report.md` reconstructing one incident end to end | M |

### M6 — Agent extension pack *(course module 5, not MVP)*

| # | Task | Size |
|---|---|---|
| 50 | MCP server: `search_modules`, `get_plan`, `plan_meal`, `get_shopping_list`, `validate_plan` | L |
| 51 | Reusable workflow: "add a module from a recipe" | M |
| 52 | Subagent: API-contract reviewer checking diffs against `openapi.yaml` | M |
| 53 | Hook: regenerate the client and block a commit on drift | S |
| 54 | `docs/agent-extension-pack.md`, `docs/permissions.md`, `docs/demo.md` | M |
| 55 | Semgrep scan, PR-Agent output, agent capability table, AI tool/data policy | L |

The MCP server (50) is the piece worth doing well. It makes the planner conversational — *"plan
dinners for next week, nothing with squid, keep Thursday light"* — which is the PRD's low-friction
thesis, not a checkbox.

## 4. Critical path

```
1 → 4 → 5 → 7 → 8 → 9/11 → 13 → 14 → 20 → 21 → 25 → 32 → 37 → 40 → 41
```

Two things sit on it that are easy to start late and expensive to rush: **task 8** (the reference
fixture — everything downstream is tested against it) and **task 13** (`openapi.yaml` — both the
backend and the generated client wait on it).

## 5. Explicitly out of MVP

| Deferred | Why |
|---|---|
| Substitution (S10) | Valuable, but needs a populated library and real preference data to rank against. Nine of fourteen modules were untried in the pilot — ranking is premature until that number drops. |
| Prep plan (S11) | The reference's two cook sessions are stable week to week; hand-copying them costs minutes. Low value until the module library grows. |
| Module import (S12) | The library is ~14 modules. Typing them is faster than building an extractor. Revisit at ~40. |
| Nutrition beyond kcal and protein | PRD §7. A schema addition later, not a redesign. |
| Multi-profile | PRD §2. One pairing. |
| Offline mode | PRD §7. |

Each is a story in the PRD with acceptance criteria already written, so none needs re-specifying
when its turn comes.

## 6. Risks

| Risk | Mitigation |
|---|---|
| Transcription errors in the reference fixture (task 8) look like engine bugs forever | Transcribe once, carefully; verify the golden shopping list against §12 by hand before trusting it as an oracle |
| `batch_portions` double-counting in the shopping list (LLD §3) | A named test exists for exactly this before the engine is written |
| Yield factors are estimates | PRD §10.2 records them as confirmed; a change is a change to expected test output, not a tweak |
| Scope creep from a rich domain | Everything beyond S1–S9a is in §5 with a reason |
| Follower doesn't adopt | Build Today (32) early; keep the 30-second budget as an acceptance criterion, not an aspiration |
| Deploy left until the end | M4 before M5/M6; the public URL is a course requirement and the usual place projects run out of time |
