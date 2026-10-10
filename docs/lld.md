# Ration — Low-Level Design

> Detail level: enough that an engineer who has not been in these conversations can implement a
> task from this plus the issue. Owns schema, signatures, endpoints, and the test plan.
> *What* and *why* are in [`product-spec.md`](product-spec.md); boundaries in [`hld.md`](hld.md).

## 1. Repository layout

```
backend/
  src/ration/
    domain/              PURE — no I/O, no framework (HLD AD-1)
      types.py             frozen dataclasses
      nutrition.py         totals
      validation.py        the eight checks
      shopping.py          cooked → raw → merge → round → group
      prep.py              batch cook sessions
      substitution.py      ranked candidates
      units.py             gram/ml handling, no cross-dimension conversion
    repositories/        SQLAlchemy models + mappers to domain types
    api/
      routers/
      schemas/           Pydantic request/response models
      deps.py            auth, db session
      ws.py              per-plan hub
    extractors/          RecipeExtractor protocol + implementations
    seed/                reference plan loader
    config.py
  migrations/            Alembic
  tests/
    unit/                domain only, no database
    integration/         API + real database
frontend/
  src/
    api/                 GENERATED — do not hand-edit
    features/planner/
    features/follower/
    components/
    lib/
  tests/
openapi.yaml             the contract (HLD AD-2)
```

## 2. Database schema

Database-agnostic: no Postgres-only types. All timestamps are UTC. All ids are UUID stored as
`CHAR(36)` for SQLite/Postgres portability.

### Identity

```sql
users (
  id            CHAR(36) PK,
  email         VARCHAR(255) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  display_name  VARCHAR(100) NOT NULL,
  role          VARCHAR(16)  NOT NULL,   -- planner | follower
  created_at    TIMESTAMP    NOT NULL
)

profiles (
  id                    CHAR(36) PK,
  name                  VARCHAR(100) NOT NULL,
  planner_user_id       CHAR(36) NOT NULL REFERENCES users(id),
  follower_user_id      CHAR(36)     NULL REFERENCES users(id),
  daily_kcal_target     INTEGER  NOT NULL,
  daily_kcal_tolerance  INTEGER  NOT NULL DEFAULT 50,
  daily_protein_min     INTEGER  NOT NULL,
  daily_protein_target  INTEGER  NOT NULL,
  locale                VARCHAR(8) NOT NULL DEFAULT 'ru',
  created_at            TIMESTAMP NOT NULL
)

slot_budgets (
  id           CHAR(36) PK,
  profile_id   CHAR(36) NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  slot         VARCHAR(16) NOT NULL,   -- breakfast|lunch|snack|dinner|treat
  kcal_min     INTEGER NOT NULL,
  kcal_max     INTEGER NOT NULL,
  protein_min  INTEGER NOT NULL,
  protein_max  INTEGER NOT NULL,
  UNIQUE (profile_id, slot)
)
```

### Catalog

```sql
ingredients (
  id                 CHAR(36) PK,
  kcal_per_100g      NUMERIC(7,2) NOT NULL,
  protein_per_100g   NUMERIC(6,2) NOT NULL,
  yield_factor       NUMERIC(4,3) NOT NULL DEFAULT 1.000,  -- cooked ÷ raw, (0,2]
  package_size       NUMERIC(8,2)     NULL,
  package_unit       VARCHAR(8)       NULL,                -- g | ml | pcs
  shop_section       VARCHAR(24)  NOT NULL,
  is_staple          BOOLEAN NOT NULL DEFAULT FALSE,
  created_at         TIMESTAMP NOT NULL
)

ingredient_names (
  ingredient_id CHAR(36) NOT NULL REFERENCES ingredients(id) ON DELETE CASCADE,
  locale        VARCHAR(8) NOT NULL,
  name          VARCHAR(120) NOT NULL,
  PRIMARY KEY (ingredient_id, locale)
)
-- INDEX ON ingredient_names (locale, name)

ingredient_aliases (
  id            CHAR(36) PK,
  ingredient_id CHAR(36) NOT NULL REFERENCES ingredients(id) ON DELETE CASCADE,
  locale        VARCHAR(8) NOT NULL,
  alias         VARCHAR(120) NOT NULL,
  UNIQUE (locale, alias)
)
```

Exclusions and cautions are **per profile**, not properties of an ingredient — the same catalog
could serve a second profile with different rules:

```sql
profile_ingredient_rules (
  profile_id         CHAR(36) NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  ingredient_id      CHAR(36) NOT NULL REFERENCES ingredients(id) ON DELETE CASCADE,
  rule               VARCHAR(16) NOT NULL,   -- excluded | caution
  caution_threshold_g NUMERIC(7,2) NULL,     -- required when rule = caution
  PRIMARY KEY (profile_id, ingredient_id)
)
```

### Modules

```sql
modules (
  id             CHAR(36) PK,
  name           VARCHAR(120) NOT NULL,
  slot           VARCHAR(16)  NOT NULL,
  role           VARCHAR(8)   NOT NULL DEFAULT 'main',  -- main | side
  batch_portions SMALLINT     NOT NULL DEFAULT 1,       -- 1..7
  prep_notes     TEXT             NULL,
  archived       BOOLEAN      NOT NULL DEFAULT FALSE,
  created_at     TIMESTAMP    NOT NULL
)

module_lines (
  id               CHAR(36) PK,
  module_id        CHAR(36) NOT NULL REFERENCES modules(id) ON DELETE CASCADE,
  ingredient_id    CHAR(36) NOT NULL REFERENCES ingredients(id),
  grams_cooked     NUMERIC(7,2) NOT NULL CHECK (grams_cooked > 0),
  size_is_critical BOOLEAN NOT NULL DEFAULT FALSE,       -- PRD §6.7
  position         SMALLINT NOT NULL,
  UNIQUE (module_id, position)
)

module_tags (
  module_id CHAR(36) NOT NULL REFERENCES modules(id) ON DELETE CASCADE,
  tag       VARCHAR(32) NOT NULL,
  PRIMARY KEY (module_id, tag)
)
```

`modules.kcal` and `modules.protein_g` are **not columns**. They are computed from lines on read
(PRD §3.2). A library of ~100 modules makes caching premature.

### Rules

```sql
frequency_rules (
  id                   CHAR(36) PK,
  profile_id           CHAR(36) NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  tag                  VARCHAR(32) NOT NULL,
  max_per_week         SMALLINT     NULL,
  blocked_on_templates VARCHAR(255) NULL,   -- comma-separated; no JSON column (AD-4)
  UNIQUE (profile_id, tag)
)
```

### Plans

```sql
plans (
  id         CHAR(36) PK,
  profile_id CHAR(36) NOT NULL REFERENCES profiles(id),
  name       VARCHAR(120) NOT NULL,
  start_date DATE NOT NULL,
  status     VARCHAR(16) NOT NULL DEFAULT 'draft',  -- draft|active|archived
  created_at TIMESTAMP NOT NULL
)

plan_days (
  id           CHAR(36) PK,
  plan_id      CHAR(36) NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
  day_index    SMALLINT NOT NULL CHECK (day_index BETWEEN 0 AND 6),
  date         DATE NOT NULL,
  day_template VARCHAR(16) NOT NULL,   -- normal|long_shift|training|duty_24h
  notes        TEXT NULL,
  UNIQUE (plan_id, day_index)
)

plan_entries (
  id             CHAR(36) PK,
  plan_day_id    CHAR(36) NOT NULL REFERENCES plan_days(id) ON DELETE CASCADE,
  slot           VARCHAR(16) NOT NULL,
  module_id      CHAR(36) NOT NULL REFERENCES modules(id),
  portion_factor NUMERIC(3,2) NOT NULL DEFAULT 1.00 CHECK (portion_factor BETWEEN 0.5 AND 1.5),
  position       SMALLINT NOT NULL,
  UNIQUE (plan_day_id, slot, position)
)
```

Exactly seven `plan_days` per plan, created with the plan (PRD §3.6). One `main` entry per slot
is enforced in the service layer, not by a constraint — SQLite cannot express a partial unique
index portably.

### Feedback and shopping state

```sql
feedback (
  id            CHAR(36) PK,
  plan_entry_id CHAR(36) NOT NULL UNIQUE REFERENCES plan_entries(id) ON DELETE CASCADE,
  status        VARCHAR(12) NOT NULL DEFAULT 'tried',  -- not_tried | tried
  rating        VARCHAR(12)     NULL,                  -- liked | neutral | disliked
  bloating      SMALLINT        NULL CHECK (bloating BETWEEN 0 AND 3),
  satiety       VARCHAR(12)     NULL,                  -- too_little|right|too_much
  note          TEXT            NULL,
  created_at    TIMESTAMP NOT NULL,
  updated_at    TIMESTAMP NOT NULL
)

shopping_check_state (
  plan_id       CHAR(36) NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
  ingredient_id CHAR(36) NOT NULL REFERENCES ingredients(id) ON DELETE CASCADE,
  checked       BOOLEAN NOT NULL DEFAULT FALSE,
  updated_at    TIMESTAMP NOT NULL,
  PRIMARY KEY (plan_id, ingredient_id)
)
```

An absent `feedback` row means `not_tried`. The default on insert is `tried` because a row is
only written when the follower rates something (HLD §4).

## 3. Domain types and signatures

Everything here is a frozen dataclass. No ORM objects cross this line.

```python
# domain/types.py
Slot     = Literal["breakfast", "lunch", "snack", "dinner", "treat"]
Role     = Literal["main", "side"]
Template = Literal["normal", "long_shift", "training", "duty_24h"]
Level    = Literal["error", "warning", "info"]

@dataclass(frozen=True)
class Ingredient:
    id: str
    names: Mapping[str, str]
    kcal_per_100g: Decimal
    protein_per_100g: Decimal
    yield_factor: Decimal
    package_size: Decimal | None
    package_unit: str | None
    shop_section: str

@dataclass(frozen=True)
class ModuleLine:
    ingredient_id: str
    grams_cooked: Decimal
    size_is_critical: bool

@dataclass(frozen=True)
class Module:
    id: str
    name: str
    slot: Slot
    role: Role
    batch_portions: int
    lines: tuple[ModuleLine, ...]
    tags: frozenset[str]
    prep_notes: str | None

@dataclass(frozen=True)
class Totals:
    kcal: Decimal
    protein_g: Decimal

@dataclass(frozen=True)
class Catalog:
    ingredients: Mapping[str, Ingredient]
    modules: Mapping[str, Module]
```

`Decimal` throughout, never `float`. Money-style rounding errors in a shopping list are the kind
of bug that erodes trust in the whole output.

```python
# domain/nutrition.py
def line_totals(line: ModuleLine, catalog: Catalog) -> Totals
def module_totals(module: Module, catalog: Catalog) -> Totals
def entry_totals(entry: PlanEntry, catalog: Catalog) -> Totals     # × portion_factor
def slot_totals(entries: Sequence[PlanEntry], catalog: Catalog) -> Totals
def day_totals(day: PlanDay, catalog: Catalog) -> Totals

# domain/validation.py
@dataclass(frozen=True)
class Finding:
    level: Level
    code: str                 # stable identifier, e.g. "DAY_KCAL_OUT_OF_RANGE"
    day_index: int | None
    slot: Slot | None
    entry_id: str | None
    message_key: str          # for localisation; never a formatted string
    params: Mapping[str, str | int | Decimal]

def validate(plan: Plan, profile: Profile, catalog: Catalog) -> tuple[Finding, ...]

# domain/shopping.py
@dataclass(frozen=True)
class ShoppingLine:
    ingredient_id: str
    needed_raw_g: Decimal
    packages: int | None
    purchase_amount: Decimal
    overage_g: Decimal
    size_is_critical: bool
    shop_section: str

def shopping_list(plan: Plan, catalog: Catalog) -> tuple[ShoppingLine, ...]

# domain/prep.py
def prep_plan(plan: Plan, catalog: Catalog) -> tuple[CookSession, ...]

# domain/substitution.py
def substitutes(
    entry: PlanEntry, plan: Plan, profile: Profile, catalog: Catalog,
    kcal_tolerance: Decimal = Decimal(40),
    protein_tolerance: Decimal = Decimal(4),
) -> tuple[Candidate, ...]
```

Findings carry a `message_key` and `params`, never a formatted sentence. The follower's UI is
Russian (PRD §8); formatting English in the domain layer would make that untranslatable.

### Validation codes

| Code | Level | Trigger |
|---|---|---|
| `DAY_KCAL_OUT_OF_RANGE` | error | day total outside target ± tolerance |
| `DAY_PROTEIN_BELOW_MIN` | error | day protein < `daily_protein_min` |
| `SLOT_OUT_OF_BUDGET` | warning | slot **total** outside its budget |
| `EXCLUDED_INGREDIENT` | error | any line's ingredient has rule `excluded` |
| `CAUTION_THRESHOLD_EXCEEDED` | warning | caution ingredient over threshold **per day**, summed |
| `FREQUENCY_EXCEEDED` | error | tag count over `max_per_week` across the plan |
| `TEMPLATE_GATE_VIOLATED` | error | tag blocked on that day's template |
| `BATCH_NOT_CONSECUTIVE` | warning | `batch_portions > 1` module not on consecutive days |
| `SLOT_EMPTY` | info | slot has no entries |
| `DAY_UNPLANNED` | info | day has no entries |
| `MULTIPLE_MAIN_ENTRIES` | error | more than one `main` in a slot |

### The shopping pipeline, precisely

```python
for each plan_entry:
    for each module_line:
        cooked = line.grams_cooked * entry.portion_factor
        # batch_portions does NOT multiply here — a batch module appears once
        # per day it is planned, and each appearance is one portion.
        raw = cooked / ingredient.yield_factor
    accumulate raw by ingredient_id

for each accumulated ingredient:
    if package_size is None:
        packages = None; purchase = needed; overage = 0
    else:
        packages = ceil(needed / package_size)
        purchase = packages * package_size
        overage  = purchase - needed

group by shop_section, sort by localised name
```

The `batch_portions` note is the trap: a lunch cooked once for three days appears as three plan
entries, one per day. Multiplying by `batch_portions` as well would triple-count it. This is the
single most likely arithmetic error in the system, and `test_shopping_batch_not_double_counted`
exists specifically to catch it.

## 4. API

All routes under `/api`. Auth by session cookie. `P` = planner only, `F` = follower, `B` = both.

| Method | Path | Who | Notes |
|---|---|---|---|
| POST | `/auth/login` | — | sets session cookie |
| POST | `/auth/logout` | B | |
| GET | `/auth/me` | B | role + profile id |
| GET | `/ingredients` | B | `?q=&locale=&section=` — alias-aware search |
| POST | `/ingredients` | P | |
| GET/PATCH/DELETE | `/ingredients/{id}` | P | delete refuses if referenced |
| GET | `/modules` | B | `?slot=&role=&tag=&tried=` |
| POST | `/modules` | P | |
| GET/PATCH/DELETE | `/modules/{id}` | P | totals computed in the response |
| GET/PATCH | `/profiles/{id}` | P | |
| PUT | `/profiles/{id}/slot-budgets` | P | full replace |
| PUT | `/profiles/{id}/frequency-rules` | P | full replace |
| PUT | `/profiles/{id}/ingredient-rules` | P | full replace |
| GET | `/plans` | B | |
| POST | `/plans` | P | `{start_date, copy_from_plan_id?}` — creates 7 days |
| GET/PATCH/DELETE | `/plans/{id}` | P | GET is `B` |
| PUT | `/plans/{id}/days/{day_index}` | P | template, notes |
| POST | `/plans/{id}/days/{day_index}/entries` | P | returns entry + validation |
| PATCH/DELETE | `/plans/{id}/entries/{entry_id}` | P | returns validation |
| GET | `/plans/{id}/validation` | B | |
| GET | `/plans/{id}/shopping-list` | B | includes check state |
| PATCH | `/plans/{id}/shopping-list/{ingredient_id}` | B | `{checked}` |
| GET | `/plans/{id}/prep-plan` | B | |
| GET | `/plans/{id}/entries/{entry_id}/substitutes` | P | post-MVP |
| PUT | `/plans/{id}/entries/{entry_id}/feedback` | F | upsert; infers `tried` |
| GET | `/today` | F | resolves the active plan and today's date |
| POST | `/modules/extract` | P | post-MVP; returns an unsaved draft |
| WS | `/ws/plans/{id}` | B | invalidation only (HLD AD-6) |

### Error model

One shape for every error:

```json
{ "error": { "code": "VALIDATION_FAILED",
             "message": "Human-readable, English, for developers",
             "details": [ { "field": "yield_factor", "code": "OUT_OF_RANGE" } ] } }
```

`400` malformed · `401` unauthenticated · `403` wrong role · `404` absent or not yours ·
`409` conflict (e.g. second `main` in a slot) · `422` schema violation.

A plan belonging to another profile returns `404`, never `403` — existence is not disclosed.

### WebSocket messages

```json
{ "type": "invalidate", "plan_id": "…", "changed": ["entries", "validation"] }
```

`changed` ∈ `entries` · `validation` · `shopping_list` · `feedback` · `days`. No payload, by
AD-6. Client maps each to a TanStack Query key and invalidates.

## 5. Frontend

```
src/
  api/              GENERATED from openapi.yaml — CI fails on drift
    client.ts         typed fetch wrapper, credentials: 'include'
    types.ts
  lib/
    queries.ts        TanStack hooks; the only consumers of api/
    ws.ts             socket → query invalidation
    i18n.ts           ru/en; validation message_key → sentence
  features/
    planner/  catalog/  modules/  plan-builder/  validation-panel/
    follower/ today/    shopping/  rate/
  components/       shared primitives
```

**No component imports `api/` directly.** Components use hooks from `lib/queries.ts`. That is
the "centralized backend communication" the rubric asks for, and it is checkable with one ESLint
`no-restricted-imports` rule rather than a convention nobody enforces.

Routing splits on role at the root: planner lands on the plan builder, follower on Today.

## 6. Test plan

| Layer | Location | Covers | Database |
|---|---|---|---|
| Unit — domain | `backend/tests/unit/` | all five engines, every validation code, the rounding and yield arithmetic | none |
| Unit — frontend | `frontend/tests/` | i18n of findings, shopping grouping, Today's slot assembly | none |
| Integration | `backend/tests/integration/` | each endpoint, auth, role boundaries, migrations, WS fan-out | real Postgres |
| E2E | `e2e/` | planner edits → follower sees it; follower rates → planner sees it; shopping check-off persists | full stack |

### Golden tests

The reference plan is a fixture with known-correct outputs already written down in
`sample-plan-6-days.md`:

- `test_golden_shopping_list` — the generated list equals §12 of that document, line for line.
- `test_golden_prep_plan` — two cook sessions matching §10–11.
- `test_golden_validation_clean` — no errors, exactly two `info` findings for the unplanned
  seventh day.

These are the strongest tests in the suite because their expected values were written by a human
before the code existed, and were not derived from it.

### Cases that must exist

- Batch module not double-counted in shopping (§3 above).
- `yield_factor = 1.0` leaves the quantity untouched.
- An ingredient with no `package_size` reports no packages and zero overage.
- Two modules in one slot sum for the budget check.
- Two `main` entries in one slot are rejected.
- A frequency rule at exactly `max_per_week` passes; one more fails.
- Wine on a `training` day is blocked; the same module on `normal` passes.
- A caution ingredient split across two modules in one day sums past the threshold.
- An unplanned day yields `info`, never `error`.
- A follower cannot PATCH a plan entry (403).
- A plan from another profile yields 404, not 403.

## 7. Seeding

`ration.seed` loads the reference plan from a checked-in YAML transcription of
`sample-plan-6-days.md` — ingredients with nutrition and yield factors, 14 modules, the profile
with its budgets and rules, a 7-day plan with days 0–5 filled, and the §14 feedback.

Idempotent, keyed by stable slugs, so `seed --reset` is repeatable. Runs in dev, compose,
staging, and tests. Never in production.

The YAML is the fixture for the golden tests and the demo data for peer reviewers — one artifact,
three jobs.
