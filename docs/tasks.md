# Ration — Backlog

> [!IMPORTANT]
> **The GitHub issues are the source of truth.** Every task below exists as an
> issue at https://github.com/staskut/ration/issues with the same number, groomed
> to the four-section template in [`task-template.md`](task-template.md):
> goal, checkable acceptance criteria, out of scope with links, and constraints.
>
> This file is the planning snapshot that produced them. It is kept for the
> record and is not updated as work proceeds — read the issue, not this.

Tasks are worked one at a time ([`process.md`](process.md)). Each is sized for a
single session and written to be handed to someone who has read `AGENTS.md` and
the documents a task names, but not the other tasks.

Scope and rationale live in [`product-spec.md`](product-spec.md) (PRD),
[`hld.md`](hld.md), and [`lld.md`](lld.md). A task never re-argues a decision
made there; it links to it.

## What grooming changed

Grooming all 52 surfaced three acceptance criteria that were wrong because they
were written before the data they described existed:

- `yield_factor` was bounded to `(0, 2]`, which assumes cooking only ever removes
  water. Rice noodles are about 2.85. Now `(0, 5]`.
- The golden shopping tolerance was 5%, which is unachievable against a list that
  says "about 30 g" and "at least 125 ml". Now 15%, with staples compared on
  presence rather than quantity.
- The module count was 14, taken from section 14's feedback table, which groups
  the shakes and the overnight oats. Section 8 has 19.

The lesson is recorded here because it will recur: **grooming a data-dependent
task before looking at the data produces confident, wrong criteria.** Transcribe
first, then write the criteria.

---

## 1. Empty backend project with a passing test
Status: see the issue

### Goal
A backend project that installs, lints, and runs one passing test on a clean checkout.

### Acceptance criteria
- [ ] `cd backend && uv sync` completes from a fresh clone with no manual steps
- [ ] `uv run pytest` reports at least one passing test and zero failures
- [ ] `uv run ruff check .` exits zero
- [ ] `uv run ruff format --check .` exits zero
- [ ] `pyproject.toml` requires Python 3.12 and names the package `ration`
- [ ] The test imports `ration` — proving the package is installed, not merely present on disk
- [ ] `make test` and `make lint` from the repository root run the backend checks
- [ ] `backend/src/ration/` contains only `__init__.py`; no application code

### Out of scope
- Frontend scaffold → #2
- CI workflow → #3
- Import-linter contract → #4
- Any domain code → #5

### Constraints
- Files: `backend/`, plus a `Makefile` at the repository root
- `uv` for dependency management. Not poetry, not pip-tools
- `ruff` for both linting and formatting. No separate black or isort
- src layout (`backend/src/ration/`), so an uninstalled package fails loudly rather than importing from the working directory
- Dependencies beyond `pytest` and `ruff` need asking first (AGENTS.md)

---

## 2. Frontend scaffold with a passing test
Status: see the issue

### Goal
A frontend project that builds, typechecks, and runs one passing test.

### Acceptance criteria
- [ ] `cd frontend && npm install` completes from a fresh clone
- [ ] `npm run build` produces a production build with no errors
- [ ] `npm test` runs Vitest with at least one passing component test
- [ ] `npm run typecheck` exits zero with TypeScript `strict: true`
- [ ] `make test` and `make lint` from the root also run the frontend checks
- [ ] No router, no network calls, no application screens

### Out of scope
- CI wiring → #3
- Generated API client → #35
- The import rule banning direct `src/api/` use → #36
- Any screen → #38 onward

### Constraints
- Files: `frontend/`
- Vite + React 18 + TypeScript; Vitest + Testing Library
- `strict: true` from the first commit — retrofitting it later is a day of work
- Tailwind may be added here or in #38, but no component library without asking

---

## 3. CI pipeline for lint and tests
Status: see the issue

### Goal
Every pull request runs lint, typecheck, and tests for both projects, and fails when they fail.

### Acceptance criteria
- [ ] A workflow runs on pull requests and on pushes to `main`
- [ ] It runs, as separate named steps: ruff check, ruff format check, pytest, tsc, Vitest
- [ ] A deliberately failing test makes the run red — demonstrated once and noted in the PR, then reverted
- [ ] Python and Node dependencies are cached between runs
- [ ] The whole workflow finishes in under five minutes on an empty project
- [ ] No deploy, publish, or release steps

### Out of scope
- Import-linter step → #4 (adds itself to this workflow)
- Integration tests against Postgres → #34
- Client drift gate → #35
- Deployment → #50, #51

### Constraints
- Files: `.github/workflows/ci.yml`
- One workflow file; separate jobs for backend and frontend so a failure names the side it came from
- Pin action versions to a major tag

---

## 4. Domain purity guard
Status: see the issue

### Goal
CI fails if the domain layer imports a framework, so HLD AD-1 is enforced rather than hoped for.

### Acceptance criteria
- [ ] An import-linter contract forbids `ration.domain` from importing `fastapi`, `sqlalchemy`, `ration.api`, and `ration.repositories`
- [ ] `uv run lint-imports` exits zero on the current tree
- [ ] Temporarily adding `import fastapi` to a module under `ration.domain` makes it exit non-zero — demonstrated in the PR description, then reverted
- [ ] The check runs in the CI workflow from #3 and can fail the build
- [ ] `backend/src/ration/domain/__init__.py` exists so the contract has something to check

### Out of scope
- The ESLint rule for the frontend's `api/` boundary → #36
- Any domain implementation → #5

### Constraints
- Files: `backend/.importlinter` (or the `pyproject.toml` section), `backend/src/ration/domain/__init__.py`, the CI workflow
- `import-linter` is the one new dependency this task introduces
- The contract lists forbidden modules explicitly rather than allow-listing — a new framework dependency should fail by default

---

## 5. Domain types and unit handling
Status: see the issue

### Goal
The frozen dataclasses and unit handling that every engine operates on.

### Acceptance criteria
- [ ] `domain/types.py` defines `Slot`, `Role`, `Template`, `Level`, `Ingredient`, `ModuleLine`, `Module`, `PlanEntry`, `PlanDay`, `Plan`, `Profile`, `SlotBudget`, `Totals`, and `Catalog` as specified in `lld.md` §3
- [ ] Every dataclass is `frozen=True`; collection fields are `tuple` or `frozenset`, never `list` or `set`
- [ ] Every nutrition, weight, and factor field is `Decimal` — `grep -rn "float" domain/` returns nothing
- [ ] `domain/units.py` models a quantity with a gram or millilitre dimension
- [ ] Adding quantities of different dimensions raises; adding the same dimension returns the sum
- [ ] Tests cover: constructing each type, that assignment to a field raises `FrozenInstanceError`, and that cross-dimension addition raises
- [ ] `uv run lint-imports` still passes

### Out of scope
- Any computation over these types → #6
- Loading them from YAML → #9
- Loading them from a database → #20

### Constraints
- Files: `backend/src/ration/domain/types.py`, `units.py`, and their unit tests
- Pure standard library plus `decimal`. No pydantic in `domain/` — it is an API-layer concern
- No conversion between grams and millilitres, ever (PRD §6.2). Refusing is correct behaviour, not a limitation to work around

---

## 6. Nutrition totals
Status: see the issue

### Goal
Calories and protein computed from a single module line up to a whole day.

### Acceptance criteria
- [ ] `line_totals`, `module_totals`, `entry_totals`, `slot_totals`, and `day_totals` exist with the signatures in `lld.md` §3
- [ ] `entry_totals` multiplies the module's totals by `portion_factor`
- [ ] `slot_totals` sums across **several entries** in the slot — one `main` plus any `side`s
- [ ] `day_totals` sums every slot in the day
- [ ] An empty slot and an unplanned day both return zero totals rather than raising
- [ ] Rounding happens only when a total is produced, to one decimal place, half-up
- [ ] A test asserts a hand-computed module total matches to the decimal
- [ ] A test asserts `portion_factor = 0.5` halves a module's totals
- [ ] A test asserts two entries in one slot sum
- [ ] `uv run lint-imports` still passes

### Out of scope
- Comparing totals against budgets → #12
- Converting cooked weight to raw → #10

### Constraints
- Files: `backend/src/ration/domain/nutrition.py` and its unit tests
- `Decimal` throughout; never round intermediate values, only results
- No database and no fixture file — tests construct types directly, so this task does not wait on #7–#9

---

## 7. Reference fixture: ingredient catalog
Status: see the issue

### Goal
Every ingredient in the reference plan, as checked-in fixture data with nutrition and yield factors.

### Acceptance criteria
- [ ] `backend/src/ration/seed/ingredients.yaml` contains every ingredient appearing in §9 or §12 of `sample-plan-6-days.md`
- [ ] Each entry has: `slug`, `names.ru`, `kcal_per_100g`, `protein_per_100g`, `yield_factor`, `package_size` and `package_unit` (or explicit null), `shop_section`
- [ ] `yield_factor` is `1.0` for anything eaten as purchased, and less than 1 only for items cooked before weighing
- [ ] Yield factors for turkey thigh, chicken thigh, white fish, shrimp, and squid are consistent with the raw quantities in §12 against the cooked quantities in §10 — within one percentage point
- [ ] `shop_section` values reproduce the grouping used by §12
- [ ] Numeric values are written so they parse as exact decimals, not binary floats
- [ ] A test asserts the file parses, that every entry has all required fields, that `yield_factor` is in `(0, 2]`, and that slugs are unique
- [ ] Items sold by count (cucumbers, bananas, kiwi, herb bunches) use `package_unit: pcs` with a gram weight per piece

### Out of scope
- Modules → #8
- Profile, plan, feedback → #9
- Loading into domain types → #9
- Loading into a database → #21

### Constraints
- Files: `backend/src/ration/seed/ingredients.yaml` and one validation test
- Data only. No loader code in this task
- Source of truth is `docs/sample-plan-6-days.md`. Do not substitute values from a nutrition database — the document's numbers are the oracle for every golden test
- Load numbers as strings or integers and convert with `Decimal`; a YAML float silently loses precision

---

## 8. Reference fixture: modules
Status: see the issue

### Goal
The reference plan's fourteen meal modules as fixture data whose computed totals match the document.

### Acceptance criteria
- [ ] `backend/src/ration/seed/modules.yaml` contains every module named in §8 of `sample-plan-6-days.md`
- [ ] Each has `slug`, `name`, `slot`, `role`, `batch_portions`, `tags`, and `lines` of `{ingredient, grams_cooked}`
- [ ] Every `ingredient` reference resolves to a slug in `ingredients.yaml` — asserted by a test
- [ ] The two lunch modules have `batch_portions: 3`; everything else is `1`
- [ ] Tags are applied where they drive rules: `fish`, `salted_fish`, `alcohol`, `treat`, `home_only`
- [ ] A test computes each module's totals via #6 and asserts they fall within 5% or 20 kcal of the figures stated in §9, whichever is larger
- [ ] Any module outside that tolerance is reconciled by correcting the transcription, and the discrepancy is noted in the PR

### Out of scope
- Splitting dinners into protein + side modules → follow-up, not now. The document states dinners as single dishes; transcribe them as `role: main`
- Profile and plan → #9

### Constraints
- Files: `backend/src/ration/seed/modules.yaml` and its tests
- Quantities are **cooked** grams, exactly as the document states them (PRD §6.1)
- The 5% tolerance exists because §9's figures are explicitly approximate. It is not licence to accept a transcription error — a line that is simply wrong will miss by far more

---

## 9. Reference fixture: profile, rules, plan, and feedback — with a loader
Status: see the issue

### Goal
The remaining reference data as fixtures, loadable into the domain types from #5.

### Acceptance criteria
- [ ] `profile.yaml` carries the targets and tolerance from §1 and §5, the five slot budgets, the excluded and caution ingredients from §4, and the frequency rules from §7
- [ ] `plan.yaml` describes seven days: days 0–5 filled from §8, day 6 left unplanned
- [ ] Day templates match the document: `training` on days 0 and 3, `long_shift` on day 2, `normal` on days 1, 4, and 5
- [ ] `feedback.yaml` carries §14's per-module outcome as `status` and `rating`
- [ ] A loader returns a `Catalog`, a `Profile`, and a `Plan` built from the frozen types in #5
- [ ] A test asserts the loaded plan has exactly seven days, six of them with entries
- [ ] A test asserts every numeric field on the loaded objects is a `Decimal`
- [ ] A test asserts nine modules load as `not_tried` and five as `tried`, matching §14

### Out of scope
- Writing any of this to a database → #21
- Validating the plan against the rules → #12–#16

### Constraints
- Files: `backend/src/ration/seed/*.yaml`, `backend/src/ration/seed/loader.py`, and tests
- The loader produces domain types and imports nothing from `api` or `repositories` — `lint-imports` must still pass
- Treat frequency rules as data: `{tag, max_per_week, blocked_on_templates}`. Do not encode "liver once a week" in Python

---

## 10. Shopping list engine
Status: see the issue

### Goal
A plan becomes a grouped, package-rounded shopping list in raw weights.

### Acceptance criteria
- [ ] `shopping_list(plan, catalog)` returns `ShoppingLine`s as specified in `lld.md` §3
- [ ] Cooked grams are scaled by `portion_factor`
- [ ] **`batch_portions` is not applied.** A batch module appears once per planned day, and each appearance is one portion
- [ ] Raw grams are cooked grams divided by `yield_factor`
- [ ] Quantities merge across the whole plan by `ingredient_id`, never by name
- [ ] `packages = ceil(needed / package_size)`, with `purchase_amount` and `overage_g` reported
- [ ] An ingredient with no `package_size` reports `packages: None` and zero overage
- [ ] A need that is an exact multiple of the package size yields exactly that many packages and zero overage — no spurious extra package
- [ ] A line is marked critical if any contributing module line has `size_is_critical`
- [ ] Lines are grouped by `shop_section` and sorted within a group by Russian name
- [ ] A test named `test_shopping_batch_not_double_counted` exists and fails if `batch_portions` is multiplied in
- [ ] Tests cover: `yield_factor = 1.0` is identity; two modules sharing one ingredient merge into one line; an exact package multiple does not round up

### Out of scope
- The follower's check-off state → #29
- Prep plan generation → deferred from MVP (`mvp-plan.md` §5)
- Comparing output against the reference document → #11

### Constraints
- Files: `backend/src/ration/domain/shopping.py` and its unit tests
- `Decimal` throughout; `ROUND_CEILING` for package counts only
- No grams↔millilitres conversion (PRD §6.2)
- Tests construct small plans directly. The reference fixture is used in #11, so this task is not blocked on #7–#9

---

## 11. Golden test: shopping list
Status: see the issue

### Goal
Prove the engine reproduces the shopping list a human wrote before the code existed.

### Acceptance criteria
- [ ] A test generates the shopping list from the reference plan and compares it to §12 of `sample-plan-6-days.md`
- [ ] Expected values are typed into the test from the document — never captured from running the code
- [ ] Every line in §12 has a matching generated line
- [ ] Any generated line absent from §12 fails the test
- [ ] Mass and volume quantities match within 5%; items counted in pieces match exactly
- [ ] Where §12 is genuinely ambiguous, the test records the interpretation in a comment rather than silently picking one
- [ ] A discrepancy is resolved by correcting the fixture or the engine, never by relaxing an expected value

### Out of scope
- Validation golden test → #16
- Prep plan comparison against §10–§11 → deferred with the prep engine

### Constraints
- Files: `backend/tests/unit/test_golden_shopping.py`
- Depends on #7, #8, #9, #10
- §12 covers six days and mixes grams with counts ("3 medium cucumbers", "1 bunch"). The 5%/exact split above handles this; if a line cannot be compared either way, document why instead of dropping it
- If this test is hard to make pass, the most likely cause is a transcription error in #7 or #8, not an engine bug. Check the fixture first

---

## 12. Validation: daily and slot budgets
Status: see the issue
Goal: Days and slots are checked against the profile's budgets.
Description: Implement the budget checks in `domain/validation.py` — daily calories within target and tolerance, daily protein at or above the minimum, and each slot's summed total within its budget. Emit findings with stable codes and parameters, never formatted sentences.

## 13. Validation: ingredient exclusions and cautions
Status: see the issue
Goal: Excluded and over-threshold ingredients are reported.
Description: Add the ingredient checks — any excluded ingredient in any module line is an error; a caution ingredient whose total across a whole day exceeds its threshold is a warning. Rules come from the profile, not from the ingredient.

## 14. Validation: frequency rules and template gates
Status: see the issue
Goal: Weekly limits and day-type restrictions are enforced.
Description: Add the rule checks — a tag used more than its weekly maximum across the plan is an error, and a tag blocked on a day's template is an error. Frequency counts scope to exactly one seven-day plan.

## 15. Validation: structural findings
Status: see the issue
Goal: Structural problems and incomplete weeks are reported at the right level.
Description: Add the remaining checks — a batch module on non-consecutive days, more than one main entry in a slot, an empty slot, and an unplanned day. Empty slots and unplanned days are informational, never errors.

## 16. Golden test: validation on the reference plan
Status: see the issue
Goal: The reference plan validates cleanly.
Description: Assert that validating the reference plan produces no errors and no warnings, and exactly the informational findings expected for the unplanned seventh day.

## 17. OpenAPI contract: auth and catalog
Status: see the issue
Goal: The contract for authentication, ingredients, and modules.
Description: Hand-write the first half of `openapi.yaml` covering the auth, ingredient, module, profile, and rule endpoints in LLD §4, with the shared error schema. Written before any handler exists.

## 18. OpenAPI contract: plans and derived resources
Status: see the issue
Goal: The contract for plans and everything computed from them.
Description: Extend `openapi.yaml` with plans, days, entries, validation, shopping list and check-off, feedback, today, and the WebSocket message shape.

## 19. Database models and initial migration
Status: see the issue
Goal: The schema exists and migrates on a clean database.
Description: Implement the SQLAlchemy models in LLD §2 and generate the initial Alembic migration. Portable types only — the same schema must run on SQLite and Postgres.

## 20. Repositories and domain mappers
Status: see the issue
Goal: Database rows become domain types and back again.
Description: Implement repositories that load a catalog and a whole plan aggregate into the frozen domain types from task 5, and persist entry changes. No business rules here.

## 21. Seed command
Status: see the issue
Goal: A command loads the reference data into a database.
Description: Add a seed command that loads the fixture YAML from tasks 7–9 into the database, keyed by stable slugs so it is idempotent and re-runnable. Available in development, compose, and tests; never in production.

## 22. Authentication and roles
Status: see the issue
Goal: A planner and a follower can sign in and are told apart.
Description: Implement session cookie authentication with the two roles, the `/auth` routes, and the dependency that authorises a request against a profile pairing. A request for another profile's data returns 404, not 403.

## 23. Ingredient endpoints
Status: see the issue
Goal: The planner manages the ingredient catalog over HTTP.
Description: Implement the ingredient routes from the contract, including alias-aware search by locale. Deleting an ingredient that a module references is refused.

## 24. Module endpoints
Status: see the issue
Goal: The planner manages the module library over HTTP.
Description: Implement the module routes, with calories and protein computed in the response rather than stored. Support filtering by slot, role, and tag.

## 25. Profile, budget, and rule endpoints
Status: see the issue
Goal: The planner edits targets, budgets, and rules.
Description: Implement the profile routes and the full-replace endpoints for slot budgets, frequency rules, and ingredient rules.

## 26. Plan and day endpoints
Status: see the issue
Goal: Plans exist over HTTP and always have seven days.
Description: Implement plan creation — which creates exactly seven days — listing, update, delete, and the day endpoint that sets a template and notes. Optionally copy from a previous plan.

## 27. Plan entry endpoints
Status: see the issue
Goal: The planner fills slots, and sees validation immediately.
Description: Implement create, update, and delete for plan entries. A second main entry in one slot is a conflict. Each mutation returns the fresh validation report alongside the entry.

## 28. Validation and shopping list endpoints
Status: see the issue
Goal: The computed outputs are available over HTTP.
Description: Implement the validation and shopping list routes, calling the domain engines and merging in the follower's check-off state. Handlers contain no arithmetic.

## 29. Shopping check-off endpoint
Status: see the issue
Goal: Ticking an item in a shop persists.
Description: Implement the check-off endpoint, writing per-plan, per-ingredient state server-side so it survives a reload and follows the follower across devices.

## 30. Feedback endpoint
Status: see the issue
Goal: The follower rates a meal in one request.
Description: Implement the feedback upsert. A rating marks the entry tried; the follower never sets status directly. Bloating and satiety are optional.

## 31. Today endpoint
Status: see the issue
Goal: One request returns everything the follower needs for today.
Description: Resolve the active plan and the current date, and return the day's slots with their times, modules, portion weights, totals, home-only marks, and any existing feedback.

## 32. WebSocket invalidation hub
Status: see the issue
Goal: A change to a plan reaches everyone watching it.
Description: Implement the per-plan WebSocket hub that broadcasts which resources changed, carrying no payload per HLD AD-6. Subscriptions are authorised on connect and scoped to one plan.

## 33. Integration tests: auth and role boundaries
Status: see the issue
Goal: The role boundaries are proven, not assumed.
Description: Add integration tests against a real database covering sign-in, session handling, every planner-only route rejecting a follower, and another profile's plan returning 404.

## 34. Integration tests: plans and derived resources
Status: see the issue
Goal: The main workflows are covered end to end at the API level.
Description: Add integration tests for plan creation, entry mutation, validation and shopping list responses, feedback, check-off persistence, WebSocket fan-out, and migrations running on an empty database.

## 35. Generated API client and drift gate
Status: see the issue
Goal: The frontend talks to the backend through a generated client, and drift fails the build.
Description: Generate the TypeScript client from `openapi.yaml`, commit it, and add a CI step that regenerates and fails on any difference. The client is never edited by hand.

## 36. Query layer and import rule
Status: see the issue
Goal: Backend communication is centralised and the rule is enforced.
Description: Implement `lib/queries.ts` with TanStack Query hooks over the generated client, and an ESLint rule forbidding any import of `src/api/` outside that file.

## 37. Localisation
Status: see the issue
Goal: Follower-facing text is Russian, and validation findings become sentences.
Description: Add an i18n layer with Russian and English catalogs, including the mapping from validation message keys and parameters to readable sentences.

## 38. Planner: ingredient catalog screen
Status: see the issue
Goal: The planner manages ingredients in the browser.
Description: Build the catalog screen — search, create, edit, delete — with validation on yield factor and the fields the shopping list depends on.

## 39. Planner: module editor
Status: see the issue
Goal: The planner composes a module and sees its totals update.
Description: Build the module editor with ingredient line entry in cooked grams, computed calories and protein shown read-only, role, batch portions, tags, and the critical-size mark on a line.

## 40. Planner: plan builder
Status: see the issue
Goal: The planner assembles a week.
Description: Build the seven-day board with slots per day, supporting several entries in one slot, portion factor, and day templates. Changes save immediately.

## 41. Planner: validation panel
Status: see the issue
Goal: Every rule violation is visible in one place.
Description: Build the validation panel, grouping findings by day, sorting errors before warnings, and rendering an explicit no-findings state. Findings are localised through task 37.

## 42. Follower: Today screen
Status: see the issue
Goal: The follower learns what to eat and pack in seconds.
Description: Build the Today screen — the day's slot times, each module with its portion weight and totals, home-only items marked. It must be readable on a phone and load in under two seconds.

## 43. Follower: shopping list screen
Status: see the issue
Goal: The shopping list is usable in a shop.
Description: Build the shopping list screen — grouped by section, raw weights rounded to packages, critical sizes called out, each line tappable to check off with state persisting through task 29.

## 44. Follower: one-tap rating
Status: see the issue
Goal: Rating a meal costs one tap.
Description: Add the rating control to Today — liked, neutral, or disliked in a single tap with no form and no submit button. Bloating and satiety sit behind one optional extra tap.

## 45. Realtime wiring
Status: see the issue
Goal: Both surfaces update without a reload.
Description: Connect the WebSocket to the query layer so an invalidation message refetches exactly the affected queries.

## 46. Frontend unit tests
Status: see the issue
Goal: The frontend's own logic is tested.
Description: Add Vitest coverage for finding localisation, shopping list grouping and rounding display, and the Today screen's assembly of a day from the API response.

## 47. Production Dockerfile
Status: see the issue
Goal: One image serves the whole application.
Description: Write a multi-stage Dockerfile that builds the frontend to static assets and serves them from the FastAPI process, per HLD AD-5.

## 48. Docker Compose with Postgres
Status: see the issue
Goal: The full system runs with one command.
Description: Add a compose file running the application image against Postgres, applying migrations on start and seeding the reference data. Document the command in the README.

## 49. End-to-end collaborative test
Status: see the issue
Goal: The two-person workflow is proven in a real browser.
Description: Add Playwright tests with two browser contexts — a planner change appears in the follower's open view, a follower rating appears for the planner, and a shopping check-off survives a reload.

## 50. Deploy to Fly.io with Neon
Status: see the issue
Goal: The application is reachable at a public URL.
Description: Deploy the image to Fly.io with a Neon Postgres database and migrations running on release, with separate staging and production environments.

## 51. Continuous delivery
Status: see the issue
Goal: Merging to main deploys, but only when tests pass.
Description: Extend the workflow so a green pipeline builds, migrates, and redeploys, followed by a post-deploy smoke test. Document the rollback path.

## 52. README and run instructions
Status: see the issue
Goal: A stranger can clone the repository and run the system.
Description: Write the README covering the problem, the architecture, local setup, running tests, the compose command, deployment, and the public URL.
