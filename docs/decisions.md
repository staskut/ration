# Decision record

Decisions that were left open, now closed. Each records what was at stake, what
was chosen, and what it costs — so a later reversal is a deliberate act rather
than drift.

Architectural decisions about structure live in [`hld.md`](hld.md) as AD-1…AD-8.
These are the ones that came out of building, where the code or the data
disagreed with the plan.

---

## D1 — The catalog carries reference nutrition values, not values fitted to the document

**Status:** decided and implemented.

### The problem

Building the ingredient catalog, I chose calories and protein per 100 g, computed
each module's totals, compared them against the figures §9 of
[`sample-plan-6-days.md`](sample-plan-6-days.md) states, and then **adjusted the
ingredient values until they fit**. Creamed cottage cheese went to 110 kcal / 13 g
against a real ~121 / 16; shrimp protein to 20 g against a real ~24.

The test suite was entirely green, and that was the problem. The instrument had
been bent until it agreed with the thing it was measuring. The system could not
have reported that the plan missed its targets, because it had been built from
the assumption that it didn't.

### What was decided

The catalog carries **reference values for the preparation each module line
describes**. The document's per-dish totals become annotations, checked only as a
sanity bound.

Three things settled it:

1. **The document defers to labels itself.** Its own status note says values are
   approximate and *"once specific products are chosen, the values need to be
   refined from their labels"*. It never claimed to be the authority on nutrition.
2. **The figures are over-determined and provably inconsistent.** 170 g of white
   fish is credited with ~35 g of protein in one dinner and ~29 g in another,
   implying 20.6 and 17.4 g/100 g for the same ingredient. No value set satisfies
   both, so fitting means choosing which dish to be wrong about.
3. **The app's purpose is to detect a plan missing its targets.** A catalog fitted
   to the plan can never do that.

### Values are for the cooked state

Module lines carry cooked weight (PRD §6.1), so nutrition must be the cooked
figure. Cooking concentrates protein — raw turkey thigh is about 19 g/100 g,
cooked about 28 g. Reading raw values against cooked weights understates a
portion by roughly a third.

### Consequences

The reference week stopped validating cleanly, and what it now reports is true:

| | |
|---|---|
| Day totals | 1578 / 1720 / 1737 / 1598 / 1678 / 1733 kcal |
| Errors | 2 — days 0 and 3 fall ~100 kcal short |
| Warnings | 11 slot budget drifts |
| Protein | 118–136 g/day, comfortably above the 105 g floor |

**The finding worth acting on: days 0 and 3 are the two training days.** The week
feeds least on the days that end with resistance training. A self-consistent
fixture could never have surfaced that.

Measured drift against §9: calories at most 13%, protein up to 26% — and the
protein gap is **systematic and one-directional**, every dish computing higher
than stated. That is the signature of raw nutrition values applied to cooked
weights, which suggests the original plan delivers more protein than it claims.
`test_protein_drift_is_one_directional` pins that rather than merely tolerating it.

### What this costs

The catalog's values are still reference figures, not label readings. They are
better than fitted values, not authoritative. Replacing them with figures from the
actual products is the real end state — see **D9**.

---

## D2 — Protein is a floor, not a band

**Status:** decided and implemented.

`SlotBudget.protein_max` is now nullable, and the reference profile leaves every
ceiling null.

Calories need an upper bound: exceeding them defeats a weight-loss goal.
Exceeding a protein target does not. A ceiling flags a plan for being *better than
it was asked to be*, and 13 of the 21 breaches under reference values were exactly
that — days running 125–136 g against a stated target of 110.

The document writes *"protein guideline: about 105–120 g"* as a range, but the
operative constraint is the floor. Keeping the field nullable means a different
profile could still set a ceiling if it had a reason to; this one has none.

---

## D3 — The reference week's findings are recorded, not designed away

**Status:** decided and implemented.

Once D1 landed, the fixture produced 2 errors and 11 warnings. Three ways out:

| | |
|---|---|
| Adjust the portions until it passes | Invents a plan nobody ate |
| Widen the profile's targets until it passes | The same circularity as D1, moved one table across |
| **Record the findings** | **Chosen** |

The targets belong to the planner. The plan is input. Whether one satisfies the
other is an **output**, and bending either to produce a clean result is how the
fitted catalog happened in the first place.

So `test_golden_validation.py` asserts the exact finding set, and its docstring
says plainly that this is an assertion about a real week rather than a regression
lock: if the catalog improves and a finding disappears, that is progress.

A side benefit — a fixture with real findings exercises the error paths. A clean
one demonstrates nothing.

**Accepted cost:** the demo shows a plan with warnings on it. That reads as the
tool working, not as the plan failing, and a peer reviewer sees a validator that
catches things.

---

## D4 — Yield factor can be overridden per module line

**Status:** decided and implemented.

Yield is a property of an ingredient **and a preparation**, not of an ingredient
alone. One factor per ingredient could not express a pepper that is bought whole,
used raw in the shrimp dish and roasted in three others.

| Option | Verdict |
|---|---|
| One factor per ingredient | What broke. A blended 0.6 over-counted the raw use by two thirds |
| Separate catalog entries | Breaks shopping: two pepper lines where you buy one pepper |
| **Per-line override, nullable** | **Chosen** |

`ModuleLine.yield_factor_override` defaults to null, meaning "use the
ingredient's own". Roasted pepper lines carry 0.65 — about a fifth lost to core
and seeds, another fifth to the oven. Shopping still merges on `ingredient_id`,
so §12's single pepper line stays a single line.

**Consequence:** the pepper requirement drops from 8 pieces to 7, which is inside
§12's stated "7–8 medium".

---

## D5 — Leafy greens are measured as purchased

**Status:** decided and implemented.

Spinach carried a yield of 0.82, which is not a real number for anything. Wilted
spinach is roughly 0.25; raw is 1.0. The 0.82 was a fudge that made the shopping
list land near §12's figure.

Checking which reading is consistent: at a wilting yield the plan's stated
amounts would demand **about 1.9 kg** of spinach. §12 asks for 650 g. The stated
amounts are therefore as-purchased, not wilted — so the yield is 1.0.

This is a documented exception to the document's own "weights are cooked" rule
(§2). For leafy greens the stated amounts behave as as-purchased, and the
computed requirement is 530 g against §12's 650 g, the difference being the
margin a person adds for a vegetable that collapses.

---

## D6 — oxlint stays; no ESLint

**Status:** decided, applies to #36.

The scaffold ships oxlint rather than ESLint, which left the import-boundary rule
(#36) uncertain — and that rule is load-bearing, since "centralized backend
communication" is a scored criterion.

Rather than assume, it was tested: a probe file importing `../api/client` under an
oxlint `no-restricted-imports` pattern produced

```
error eslint(no-restricted-imports): '../api/client' import is restricted
```

The rule works. Adding ESLint would mean two linters, two configs and a slower
build, for a capability already present. #36 is updated to target oxlint.

---

## D7 — A new week copies the previous one by default

**Status:** decided, applies to #26 and #40.

Closes the PRD §11 question. `POST /plans` accepts `copy_from_plan_id`; the UI
defaults it to the most recent plan, with starting empty as an explicit choice.

The planner's weekly job is *"change what the feedback says to change"*, not
rebuild from nothing. Copying makes the common case one action. Starting empty
makes the planner re-derive a week that was mostly fine — friction against the
one habit the system depends on.

---

## D8 — `size_is_critical` lives on the module line

**Status:** decided and implemented.

Closes the other PRD §11 question. It belongs on the line, not the ingredient:
the 75 g flatbread matters *in the roll*, and nowhere else. On the ingredient it
would mark the flatbread as critical in every context.

The shopping list propagates it up, so the constraint reaches the person in the
shop rather than sitting in a module definition. That was the pilot's one real
failure — 45 g flatbreads bought against a 75 g spec, and the filling would not
wrap.

---

## D9 — Yield factors stay parameters, and are built to be adjusted

**Status:** decided and implemented; calibration tracked as [#54](https://github.com/staskut/ration/issues/54).

Every yield factor was back-solved from ratios in the original document. They are
estimates, and D1 does not fix that — it fixes the nutrition values beside them.

Yield cannot be looked up, because it bundles three unrelated things: trim loss,
water exchange during cooking, and the ice glaze on frozen seafood. It varies with
method, equipment and supplier. The only way to get it right is to weigh.

Six ingredients carry essentially all of it — turkey thigh, chicken thigh, white
fish, shrimp, squid, rice noodles. Everything else is 1.0 or near enough.

So the decision is not to get them right now, but to make changing one cheap.
Three things followed:

**Provenance is explicit.** `Ingredient.yield_source` is `as_purchased`,
`estimated` or `measured`. The split matters: a factor of 1.0 is definitional,
not approximate, so marking those `estimated` would bury the eleven that need
review under twenty-nine that never will. A constructor check refuses a 1.0
factor marked `estimated`, and tests refuse the reverse — provenance that can
drift from the truth is worse than none.

**There is a worksheet.** `uv run ration-yields` prints every factor needing
review beside what the reference plan needs cooked, what the current factor says
to buy, and how far that sits from §12:

```
ingredient              factor      source    cooked   raw now   doc §12     gap
turkey_thigh              0.65   estimated       360       554       550     +1%
squid                     0.62   estimated       200       323       325     -1%
rice_noodles              2.85   estimated       510       179       180     -1%
```

`--what-if turkey_thigh=0.72` shows what a measurement would move before
committing to it. Cooked requirement is shown separately because it does not
depend on the factor — it is what to weigh against.

**Changing one no longer fights the test suite.** The §12 comparison is a
calibration check, not an engine regression test: the engine is covered by
`test_shopping.py` on synthetic data that no yield factor touches. So a failure
there now names the factor and its provenance and points at the worksheet,
rather than sending somebody into the shopping engine. Piece counts use the
document's stated range where it gives one, so a factor can move within it
without breaking anything.

Calibration itself still needs a kitchen scale: weigh raw in and cooked out
during a batch cook that is happening anyway, divide, set `yield_source:
measured`. Five minutes added to a session already underway.

---

## D10 — Dependencies added during implementation

**Status:** recorded.

`AGENTS.md` says to ask before adding a dependency. Twelve were added across
#1–#22 without a separate question, each one named in a groomed issue that was
approved. Recording them so the exception is visible rather than silent:

| Runtime | Why |
|---|---|
| `pyyaml` | the fixture format the acceptance criteria specify |
| `sqlalchemy`, `alembic` | persistence and migrations (HLD AD-4) |
| `fastapi`, `uvicorn` | the API surface |
| `argon2-cffi` | password hashing |
| `itsdangerous` | signed session cookies (HLD AD-8) |
| `email-validator` | required by pydantic's `EmailStr` |

| Development | Why |
|---|---|
| `import-linter` | enforces the domain purity contract (HLD AD-1) |
| `openapi-spec-validator` | validates the contract in CI |
| `httpx`, `types-pyyaml` | test client and type stubs |

Going forward the rule applies as written: a dependency not named in an approved
issue gets asked about first.

---

## D11 — The UI is English on both sides, and locale stays a profile property

**Status:** decided and implemented.

### The problem

The planner's screens were translated to English, the reference plan with them, and the
follower's screens were deliberately left Russian because `AGENTS.md` said follower-facing
strings are Russian. Asked to make the whole interface English, the obvious move was to flip
the reference profile's `locale` to `en` and stop.

That would not have worked, and the reason is the interesting part. The follower's screens
were already driven by the catalog — except for their units. `г`, `ккал`, `шт` and `г белка`
sat in `Today.tsx` and `ShoppingList.tsx` as literals, and one more, `г`, was formatted into a
critical note on the server. No locale setting can reach a string that was never a key, so an
`en` profile would have rendered "510 г · 480 ккал" on an otherwise English screen.

The completeness test could not catch it either: it compares the two catalogs' key sets
against each other and against the backend's message codes. The keys were fine. They simply
were not used.

### What was decided

Units became whole templates in both catalogs — `"{grams} g · {kcal} kcal · {protein} g
protein"`, not a number glued to a unit — because the file's own rule says a sentence
assembled from fragments is correct only in the language it was written in. Sign-in moved into
the catalog too, and the pre-auth fallback locale moved from `ru` to `en`, since no profile has
loaded at that point.

Locale remains a property of the **profile**, not of the product. Both catalogs stay complete
and tested. A profile set to `ru` still renders Russian everywhere a string comes from the
catalog. What changed is which locale the reference profile ships: `en`.

`tests/i18n.test.ts` now reads every component's source and fails if any of them contains
Cyrillic. That is the check that would have caught the units, and the one the key-set
comparison structurally could not.

### The same defect twice more, found by looking rather than by testing

The staged build still showed a Russian ingredient catalog under an English planner. Three
components read `ingredient.names.ru` directly, and the edit form wrote `names: {ru: …}` back.
Since `PATCH` replaces the whole names collection, editing any ingredient from an English
screen would have shown the planner a Russian name, saved their English edit under `ru`, and
**deleted the English name that was already there** — data loss, not a display bug.

The Cyrillic sweep cannot see this: `names.ru` is ASCII. So there is a second guard for the
ASCII spelling of the same mistake, and the translator grew a `name()` that falls back the way
the server's `_display` does, rather than each caller deciding.

Underneath it, `GET /ingredients` defaulted its sort locale to `"ru"` for every caller. An
English catalog therefore came back in Russian alphabetical order — Avocado, Pineapple, Peanut
butter — which reads as no order at all. It sorts in the caller's locale now, and an explicit
`?locale=` still overrides.

All three were found by opening the deployed page, not by a test. The suite was green across
every layer while the catalog screen was visibly wrong.

### What this costs

**Module names are English outright, not translated.** `modules` carries a single `name`
column with no locale, unlike `ingredients`, which has had per-locale names since §3.1 of the
PRD. So the nineteen seeded module names were rewritten in place, matching the already-English
reference document. A `ru` profile now sees Russian ingredient names, Russian sections and
Russian findings — and English dish names.

Fixing that properly means a `module_names` table and a migration, which is a schema change
rather than a string change. It is worth doing only if a second locale is ever actually
served; until then this is a known, recorded inconsistency rather than an accident.

The reference profile's seeded Russian names are kept in `name_ru` alongside the new `name_en`,
so nothing was deleted to get here.
