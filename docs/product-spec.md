# Ration — Product Specification

> Status: draft v1. Written before any code. Changes to this document should precede
> changes to `openapi.yaml`, the schema, or the UI.

## 1. Problem

A planner builds a structured nutrition plan for one other person. The plan is not a list of
recipes — it is a set of **budgets and rules** that every day must satisfy: a daily calorie
target split across meal slots, a daily protein floor, a list of excluded foods, a list of
foods that are tolerated only in small amounts, and frequency limits such as "liver at most
once a week" or "wine only on a day with no training, duty, or driving."

Today that plan lives in a long Markdown document. It works exactly once. Every subsequent
change is manual and error-prone:

- Swapping one dinner means recomputing that day's calories and protein by hand, then checking
  the result against the slot budget and the weekly frequency rules.
- Changing a portion means recomputing the batch-cooking quantities for a three-day lunch.
- Any change to the week means regenerating the shopping list: converting cooked weights back
  to raw weights, merging the same ingredient across six days, and rounding up to package sizes.
- The follower's feedback ("the squid portion was too large", "bloating 2 after the noodles")
  has nowhere to live, so it is lost between weeks.

Every one of those steps is deterministic arithmetic over a small, well-defined data model,
and every one of them is currently done by a human who will eventually make a silent mistake.
A wrong shopping list is worse than no shopping list, because it is trusted.

**Ration replaces the document with a system**: the planner maintains a library of reusable
meals, assembles a week from them, and the system computes validation, the shopping list, the
prep plan, and substitution options. The follower sees only what to eat today, what to pack,
what to buy, and a two-tap way to say how it went.

The reference input — a complete six-day plan with a fictional profile — is
[`sample-plan-6-days.md`](sample-plan-6-days.md). It defines the data model's
required expressiveness and serves as the project's primary test fixture.

## 2. Users

| | **Planner** (author) | **Follower** (subject) |
|---|---|---|
| Who | Builds and maintains the plan | Eats it |
| Device | Desktop | Phone |
| Session | Weekly, ~30 min | Daily, ~30 sec |
| Mode | Create and edit | Read, plus two taps |
| Screens | Catalog, modules, targets, plan builder, validation | Today, shopping list, feedback |

There is exactly one follower per plan. There is no multi-client tenancy, no organization, no
invitation flow beyond a single pairing.

### 2.1 The adoption constraint

**The follower's daily interaction must stay under 30 seconds, and feedback must cost at most
two taps.** This is a hard requirement, not a nicety. The system it replaces is a document the
follower can already read in ten seconds. Any screen that asks the follower to type, maintain
state, or navigate more than one level will be abandoned, and the feedback loop in §6.5 dies
with it.

Corollary: the follower never performs data entry. Nothing in the system depends on the
follower keeping anything up to date.

## 3. Domain model

### 3.1 Ingredient

The canonical food item. Curated by the planner — roughly 100–200 entries — not imported from
a public nutrition database, because the values must match what is actually on the shelf.

| Field | Notes |
|---|---|
| `id` | |
| `names` | one per locale (`ru`, `en`); drives search and display |
| `aliases` | so "зеленый лук" and "лук-порей" resolve correctly |
| `kcal_per_100g`, `protein_per_100g` | as purchased, verified against the package label |
| `yield_factor` | cooked weight ÷ raw weight, e.g. 0.67 for turkey thigh. `1.0` for items not cooked |
| `package_size`, `package_unit` | for shopping list rounding |
| `shop_section` | meat / dairy / produce / grains / oils / treats / other |
| `flags` | `excluded`, `caution` (bloating risk), `staple` |

`yield_factor` is the field that makes the shopping list correct, and the one most likely to be
wrong. It must be editable and visible, never inferred.

### 3.2 Module

A reusable meal. The unit the planner thinks in.

| Field | Notes |
|---|---|
| `id`, `name` | |
| `slot` | `breakfast` \| `lunch` \| `snack` \| `dinner` \| `treat` |
| `role` | `main` \| `side` — a slot holds one `main` and any number of `side`s (§3.6) |
| `lines[]` | `{ingredient_id, grams_cooked, size_is_critical}` (§6.7) |
| `kcal`, `protein_g` | **computed** from lines; never entered by hand |
| `batch_portions` | 1 = cooked per serving; 3 = cooked once for three days |
| `tags` | `fish`, `liver`, `salted_fish`, `alcohol`, `home_only`, … — these drive frequency rules |
| `prep_notes` | free text, shown in the prep plan |

Quantities are stored as **cooked weight**, because that is what the follower weighs when
packing containers. Raw weight is derived for shopping and never stored on the module.

### 3.3 Profile

The targets and rules. Owned by the planner, applies to one follower.

```
daily_kcal_target        1700
daily_kcal_tolerance     ±50
daily_protein_min        105
daily_protein_target     110
slot_budgets[]           slot → {kcal_min, kcal_max, protein_min, protein_max}
excluded_ingredients[]
caution_ingredients[]    with a per-ingredient gram threshold
frequency_rules[]        see §3.5
```

### 3.4 Day template

A day's shape. Sets slot times and gates context-dependent rules.

| Template | Slot times | Gates |
|---|---|---|
| `normal` | 06:00 / 11:30 / 15:45 / 18:00 | — |
| `long_shift` | 06:00 / 11:30 / 16:30 / 21:00 | — |
| `training` | 06:00 / 11:30 / 16:00 / 18:00 | blocks `alcohol` |
| `duty_24h` | continuous; two main containers | blocks `alcohol` |

A `duty_24h` day has no separate packing output. The Today screen renders it as what it is —
one breakfast, two main containers, one snack — and the follower reads the same screen as on
any other day. Splitting the second container across evening and night is the follower's
decision, not the system's.

### 3.5 Frequency rules

Weekly constraints over module tags. Data, not code — the planner edits them.

```
{tag: "liver",        max_per_week: 1}
{tag: "salted_fish",  max_per_week: 2}
{tag: "treat",        max_per_week: 3}
{tag: "alcohol",      blocked_on_templates: ["training", "duty_24h"]}
```

### 3.6 Plan

```
Plan            → name, profile_id, start_date, status
  PlanDay       → date, day_template, notes          (exactly 7 per plan)
    PlanEntry   → slot, module_id, portion_factor (default 1.0), position
```

**A slot holds several entries.** Dinner in the pilot was assembled as a protein plus a side,
with the side swapped freely — baked pumpkin one day, baked pepper the next — while the protein
stayed on plan. Modelling a dinner as one module forces a module edit to change the side, and
multiplies the library by every protein × side combination.

So a slot holds at most one `main` entry and any number of `side` entries. **Budgets, totals,
and validation all apply to the slot's sum, never to an individual entry.** Everything in §4
sums over entries within a slot before comparing to anything.

**A plan is exactly seven days.** Planning is ongoing and iterates weekly: week N+1 is created
from week N, the planner swaps what the feedback says to swap, and the previous week stays as
a record. Fixed length keeps "per week" unambiguous — frequency rules (§3.5) scope to exactly
one plan, with no rolling-window arithmetic anywhere in the engines.

A day may be unplanned, and a slot may be empty. Validation reports these as `info`, never as
errors — an in-progress week is the normal state, not a broken one.

`portion_factor` scales a module without editing it — the follower's 0.8× dinner on a day with
no appetite, without forking the module.

### 3.7 Feedback

One record per plan entry, written by the follower.

```
status       not_tried | tried              default not_tried
rating       liked | neutral | disliked     the primary axis
bloating     0–3                            optional
satiety      too_little | right | too_much  optional
note         optional free text
```

**This model was corrected against the real pilot feedback** (§14 of the reference document),
which did not fit the first draft. That draft led with `bloating` and `satiety`; across a whole
pilot week neither was reported even once. What the follower actually reported was, for every
module, whether he had tried it and whether he liked it — and roughly half the library had not
been tried at all.

So `status` and `rating` carry the signal and are the only required fields. `bloating` and
`satiety` stay, because the profile's caution list in §3.3 exists to be tested, but they are
optional and secondary.

`not_tried` is a first-class state, not a null. "Nine of fourteen modules untried" is the most
actionable fact in the pilot, and a model that represents it as missing data cannot say it.

The dropped `convenience` field is not a loss: the one convenience problem in the pilot — a
roll that would not wrap — was caused by buying 45 g flatbreads for a module specified at 75 g.
That is an ingredient-specification failure, not a property of the module. See §6.7.

## 4. The engines

Four pure functions over the model above. No I/O, no framework, no database. This is where the
system's value and the bulk of its tests live.

### 4.1 Validation

`validate(plan, profile) → Report`

Produces findings at three levels — `error`, `warning`, `info`:

| Check | Level | Example |
|---|---|---|
| Daily kcal within target ± tolerance | error | "Day 3: 1810 kcal, target 1700 ± 50" |
| Daily protein ≥ minimum | error | "Day 5: 98 g, minimum 105 g" |
| Slot total within budget | warning | "Day 2 dinner: 530 kcal across 2 entries, budget 470–495" |
| Module contains an excluded ingredient | error | "Day 4 lunch contains chicken breast" |
| Caution ingredient over threshold | warning | "Day 6: 180 g hummus, threshold 60 g" |
| Frequency rule exceeded | error | "salted_fish used 3× this week, max 2" |
| Template gate violated | error | "Day 4 is a training day; wine is blocked" |
| Batch module not on consecutive days | warning | "Lunch A on days 1, 2, 5 — batch is 3 consecutive" |

### 4.2 Shopping list

`shopping_list(plan) → List`

```
plan entries
  → module lines scaled by portion_factor and batch_portions   (cooked grams)
  → ÷ ingredient.yield_factor                                   (raw grams)
  → merge by ingredient_id across the whole plan
  → round up to package_size                                    (packages + remainder)
  → group by shop_section
```

Each line shows the computed need, the rounded purchase, and the overage — so the planner can
see that 70 g of whey protein means buying a 500 g tub.

### 4.3 Prep plan

`prep_plan(plan) → Sessions[]`

Groups modules with `batch_portions > 1` into cook sessions, emits total quantities per session
and the per-container breakdown. For the reference plan this must produce the two sessions in
§10–11 of the sample document.

### 4.4 Substitution

`substitutes(plan_entry, profile, library) → ranked Module[]`

Candidates for the same slot **and the same role** within ±`kcal_tolerance` and
±`protein_tolerance`, excluding any module that would introduce an excluded ingredient or
breach a frequency rule given the rest of the week. Ranked by closeness to the entry being
replaced.

Matching on role is what makes this useful: "another side for this dinner" is the question the
pilot actually raised, and a search that returned proteins for it would be noise.

This is the feature that decisively beats the document: §14 of the sample asks for a
substitution table to be *maintained by hand*. Here it is computed.

## 5. User stories

Format: `As a <role>, I want <capability>, so that <outcome>.` Each has acceptance criteria
that are directly testable.

### MVP

**S1 — Catalog.** As a planner, I want to add an ingredient with its nutrition, yield factor,
and package size, so that modules can be costed automatically.
- Creating an ingredient requires `names.ru`, kcal, protein, yield factor, package size, section.
- Yield factor must be in `(0, 2]`; values outside are rejected with a message.
- Searching by alias returns the canonical ingredient.

**S2 — Module.** As a planner, I want to compose a module from ingredient lines in cooked
grams, so that its calories and protein are computed rather than estimated.
- Module kcal and protein are derived from lines; both are read-only in the UI.
- Changing an ingredient's nutrition updates every module that uses it.
- A module whose slot is `lunch` may set `batch_portions` of 2 or 3.

**S3 — Profile.** As a planner, I want to set daily and per-slot budgets, exclusions, and
frequency rules, so that validation has something to check against.
- Slot budgets must sum to within the daily target's tolerance, or a warning is shown.
- The system never computes a target. All values are entered by the planner. *(See §7.)*

**S4 — Build a plan.** As a planner, I want to assign modules to day/slot positions, so that a
week exists as data.
- A day has a template; changing it re-evaluates that day's gates.
- An entry may set `portion_factor` between 0.5 and 1.5.

**S5 — Validate.** As a planner, I want to see every rule violation in one report, so that I
can fix the week before the follower sees it.
- All eight checks in §4.1 are implemented.
- The report groups by day and sorts errors before warnings.
- An empty report renders as an explicit "no findings" state, not a blank panel.

**S6 — Shopping list.** As a follower, I want a grouped shopping list with checkboxes, so that
I can use it in a shop on my phone.
- Quantities are raw weight, rounded up to package sizes.
- Lines are grouped by shop section and tappable to check off.
- Check state persists across reloads.

**S7 — Today.** As a follower, I want one screen showing today's meals with slot times and
container weights, so that I know what to pack without reading the plan.
- Shows the day template's times, each module, its portion weight, and its kcal/protein.
- `home_only` modules are marked so they are not packed for work.
- Loads in under two seconds on a phone connection.

**S8 — Live updates.** As a follower, I want the plan to update while I am looking at it, so
that I never act on a stale version.
- A planner's change to a plan day appears in the follower's open view without a reload.
- Changes are scoped to the plan; no cross-plan leakage.

### Next

**S9 — Feedback.** As a follower, I want to rate a meal in one tap, so that the plan improves.
- `rating` is a single tap — liked / neutral / disliked. No form, no submit button.
- `status` is inferred: rating a meal marks it `tried`. The follower never sets it directly.
- `bloating` and `satiety` are behind one optional extra tap, not on the default path.
- A rated entry shows its rating without opening anything.

**S9a — Untried modules.** As a planner, I want to see which library modules have never been
tried, so that I can tell a rejected module from an unexplored one.
- The library shows `tried` / `not_tried` per module, derived from feedback across all plans.
- Untried modules are excluded from any "disliked, consider replacing" view.

**S10 — Substitution.** As a planner, I want ranked replacements for a slot, so that I can swap
a disliked meal without breaking the budget.

**S11 — Prep plan.** As a planner, I want the batch cook sessions computed, so that I know what
to cook and how to divide it.

**S12 — Module import.** As a planner, I want to paste a recipe and get a draft module, so that
adding to the library is not pure typing.
- Extraction runs behind an interface with a deterministic fallback and a fake in tests.
- The draft is always reviewed before saving; nothing is created automatically.

## 6. Scope decisions

These are the decisions most likely to be silently reversed by a coding agent. They are
specified here so that a reviewer can catch it.

**6.1 Cooked weight is stored; raw weight is derived.** Modules carry cooked grams.
`yield_factor` converts to raw for shopping only. Never store both.

**6.2 No volume↔mass conversion.** 300 g and 2 cups of flour do not merge, because the
conversion needs per-ingredient density. Quantities in incompatible dimensions appear as
separate amounts on one line: `Flour — 500 g + 2 cups`. The catalog uses grams and millilitres
only; anything else is free text.

**6.3 Ingredient identity is explicit.** Merging happens on `ingredient_id`, never on string
match. Aliases resolve at entry time, not at merge time.

**6.4 Scaling is linear, and this is wrong.** Doubling a module doubles the salt and the oil.
The UI says so once, next to `portion_factor`. Non-linear scaling is out of scope.

**6.5 Feedback is the point of the second week.** A planner without feedback is a document with
buttons. S9 is first in line after the MVP.

**6.6 The follower never maintains state.** No pantry inventory, no logging what was eaten, no
weight tracking. Each of these fails within two weeks of real use and degrades the output when
it goes stale.

**6.7 Some ingredient sizes are structural, not just a shopping detail.** A module built on a
75 g flatbread does not work with a 45 g one — the filling will not wrap. `package_size` already
exists for shopping arithmetic (§3.1); a module line may additionally mark the size as
**critical**, which surfaces it on the shopping list and on the Today screen rather than leaving
it buried in the module definition.

This comes straight from the pilot, where exactly this substitution broke the lunch module for
three days. Note what the fix is not: the module was fine and the follower liked it. Only the
specification was under-stated.

## 7. Non-goals

- **The system never computes a nutrition target.** Daily calories and protein are entered by
  the planner. Ration stores and enforces them. It does not calculate, suggest, or validate
  whether a target is appropriate.
- **No health or safety judgments.** No "healthy", "safe", or "balanced" labels, no scores, no
  warnings about the plan's suitability for a person. Rule violations are reported against the
  planner's own configured rules, and are phrased that way.
- **Not a medical device, and no clinical claims.** The UI carries a short, permanent note that
  the plan is created by its author and is not medical advice.
- No multi-client tenancy, practitioner accounts, billing, or client management.
- No public recipe corpus, discovery, or scraping.
- No cost or price estimation — price data is stale the day it is entered.
- No micronutrient tracking. Calories and protein only. Expanding to fat and carbohydrate is a
  schema addition, not a redesign, but it is not in scope.
- No offline mode. The follower's screens require a connection.

## 8. Localisation

The follower's screens and the ingredient catalog must support **Russian**. The catalog stores
one name per locale from the start (§3.1) — retrofitting that is expensive, adding a locale
later is not. That requirement is what made the change below cheap: the catalogs, the
per-locale ingredient names and the `message_key` split were all already there.

UI language: **English on both sides**, as a property of the profile rather than of the
product. `profiles.locale` selects the catalog, both catalogs are complete, and a profile set
to `ru` still renders Russian throughout. The reference profile ships `en`. Documentation,
code, comments, and this specification are English.

This reverses the MVP's "Russian for the follower's screens", which held while the plan it
served was Russian. Module names are the one thing the reversal is not clean about: `modules`
carries a single `name` column with no locale, so those are English outright rather than
translated. Giving modules per-locale names is a schema change, not a string change — see D11.

## 9. Success criteria

The project succeeds on two independent tests.

**Functional:** given the reference plan from `sample-plan-6-days.md` loaded as seed data,
the system reproduces its shopping list, its two prep sessions, and a clean validation report.
The expected outputs are already written down in that document, which makes them a regression
test rather than an opinion.

The reference covers six days and a plan is seven, so it seeds as a seven-day plan with day 7
unplanned. That is deliberate: the fixture exercises the partial-week case from §3.6 at the
same time as the arithmetic.

**Adoption:** the planner builds week 2 in Ration rather than by editing Markdown, and the
follower opens the Today screen instead of the document. If either does not happen, the system
has failed regardless of its test coverage.

## 10. Resolved decisions

Recorded here with their rationale so that a later change is a deliberate reversal rather than
a quiet drift.

1. **Plan length is a fixed seven days** (§3.6). Planning iterates weekly; week N+1 is created
   from week N. Frequency rules scope to one plan. No rolling windows.
2. **Yield factors are confirmed** and may be treated as fixtures. §4.2 depends on them
   entirely, so a change to one is a change to expected test output, not a tweak.
3. **`duty_24h` needs no separate packing output** (§3.4). The Today screen covers it.
4. **The feedback model was corrected against the real pilot** (§3.7). The first draft led with
   `bloating / satiety / convenience`; the actual feedback reported none of them and instead
   reported tried/not-tried and liked/disliked for every module. The model follows the data.
   This is the check from the previous draft of this section, carried out — and it failed,
   which is the reason it was worth doing before building S9.

5. **A slot holds several entries** (§3.6), one `main` and any number of `side`s, with budgets
   applied to the slot total. Raised by §14 of the reference document: the pilot's sides were
   swapped freely while the protein stayed on plan. The alternative — one module per dinner —
   would require a library of every protein × side combination.

6. **Nutrition values are reference figures, not fitted to the document** ([`decisions.md`](decisions.md) D1),
   **protein is a floor rather than a band** (D2), and **the reference week's findings are
   recorded rather than designed away** (D3). A catalog tuned until the plan passes cannot
   report a plan that fails, which is the one thing this system exists to do.
7. **Yield may be overridden per module line** (D4). Yield is a property of an ingredient
   *and a preparation*: the same pepper is raw in one dish and roasted in another.
8. **A new week copies the previous one by default** (D7).
9. **`size_is_critical` lives on the module line** (D8), not the ingredient — the 75 g
   flatbread matters in the roll and nowhere else.

## 11. Still open

- **Yield factors are estimates**, back-solved from the document's own ratios rather than
  measured ([`decisions.md`](decisions.md) D9). Six ingredients carry nearly all of it.
  Tracked as its own issue.
- **Nutrition values are reference figures, not label readings.** Better than fitted, not
  authoritative. Replacing them with the actual products' labels is the real end state.
