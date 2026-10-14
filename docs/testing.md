# Testing

Three layers, each answering a question the others cannot.

| | Where | What it proves | Database | Runtime |
|---|---|---|---|---|
| **Unit** | `backend/tests/unit/` | the arithmetic and the rules are right | none | ~3 s |
| **Integration** | `backend/tests/integration/` | the API behaves as the contract says | real | ~50 s |
| **Frontend unit** | `frontend/tests/` | the client's own logic | none | ~1 s |

```bash
make test              # everything
make test-unit         # domain only, no database
make test-integration  # API and repositories, real database
```

CI runs unit and integration as separate named steps, so a red build says which
layer broke before you open it.

## Unit tests

Pure functions over frozen dataclasses, with no database and no HTTP. That is
what keeps them in milliseconds, and what makes it affordable to write the
awkward cases rather than only the obvious ones.

The split is enforced rather than conventional: an import-linter contract stops
`ration.domain` importing `fastapi`, `sqlalchemy`, or the outer layers, so a
test of the domain cannot accidentally acquire a dependency on either.

### Golden tests

Three of these, and they are the strongest tests in the project — their
expected values were written by a person before the code existed, in
[`sample-plan-6-days.md`](sample-plan-6-days.md), so the oracle can disagree
with the implementation.

| Test | Oracle | Checks |
|---|---|---|
| `test_golden_shopping.py` | §12 | the shopping list, line for line |
| `test_golden_validation.py` | §1, §4, §5, §7 | the findings a real week produces |
| `test_golden_prep.py` | §10–§11 | the two batch cook sessions |

The validation one is worth reading before changing anything near the catalog.
It does **not** assert the reference week is clean — it asserts the week reports
2 errors and 11 warnings, all true, and the two short days are the two training
days. An earlier version asserted cleanliness and passed only because the
nutrition values had been tuned until it did. See
[`decisions.md`](decisions.md) D1 and D3.

When a golden expectation moves because a yield factor changed, update the
expectation and say so in the commit. That is data, not a regression — and
`uv run ration-yields` is the worksheet for it.

## Integration tests

Against a real, migrated database, built by running the actual Alembic
migrations rather than `metadata.create_all`, so the tests exercise the schema
that will be deployed.

State is built **through the API** wherever possible rather than by inserting
rows. A test that seeds the database directly can pass while the endpoint meant
to create that state is broken.

### Two fixtures worth knowing about

`planner` logs in **on the `api` client and returns it**. A test taking both
would get an authenticated client under the name `api` and quietly prove
nothing, so there is a separate `anonymous` fixture for the unauthenticated
case.

`cookies_for` drives one client as either role. WebSocket tests need it: each
`TestClient` runs its own event loop, the app records the loop it started on,
and a broadcast fired on one loop can never reach a socket held by another.
Production has one process and one loop, so one client switching identity is
the faithful arrangement rather than a convenience.

### The authorisation suite

`test_authorization.py` derives its route list **from the application**, so a
new endpoint is covered the moment it is added. A hand-maintained list goes
stale, and a stale authorisation test is worse than none because it reports
coverage it does not have.

It also guards the derivation: `test_the_route_list_is_not_empty` exists
because a broken walker would otherwise pass every parameterised test below it
by iterating nothing. That is not hypothetical — the first version of the
walker returned zero routes, and this caught it.

Two rules it enforces across all 33 routes:

- Every planner-only mutation answers **403** to a follower. Operations open to
  both roles are an explicit allowlist, so widening a permission takes a
  deliberate edit rather than happening by omission.
- Another profile's data is **404, never 403**. A 403 confirms the resource
  exists, which is a disclosure the API has no reason to make.

## What the tests have actually caught

Kept as a list because each one argues for a kind of test rather than for
testing in general.

- **No WebSocket broadcast had ever fired.** A synchronous FastAPI handler runs
  in a threadpool worker with no running event loop, so `get_running_loop()`
  raised and a `suppress` swallowed it. 238 integration tests passed at the
  time and none observed a socket. *A green suite was consistent with the
  feature being entirely absent.*
- **Seeding was not idempotent.** SQLAlchemy emits INSERTs before orphan
  DELETEs, so a unique constraint fired on the second run — and seeding runs on
  every container start.
- **`migrations/env.py` ignored the caller's URL**, so every integration test
  was silently migrating the default development database.
- **SQLite ignores foreign keys without a per-connection pragma**, so every
  `ON DELETE CASCADE` did nothing in development while working in Postgres.
- **SQLite's `lower()` is ASCII-only.** A SQL-side case-insensitive search
  matched Russian in Postgres and nothing in SQLite — the worst shape a bug can
  take.
- **A duplicate ingredient alias escaped as a 500.** Found by a QA pass, not by
  the 42 tests written alongside the feature: every one of them used distinct
  aliases, so the collision never occurred.

## Conventions

- A test name says what must be true, not what it calls. `test_a_second_main_in_a_slot_is_409`, not `test_create_entry_conflict`.
- Where a test exists because of a specific past failure, its docstring says so. The reason is the part that stops someone deleting it later.
- Tolerances carry their justification. The golden shopping list is 15% because §12 says "около 30 г", not because 15% felt safe.
- Integration tests stay under a minute in total. They run on every push.
