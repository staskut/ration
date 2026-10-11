# Acceptance audit — issues #1–#22

An audit of every closed issue against its own acceptance criteria, rather than
against the test suite. The two are not the same question: a green suite proves
the tests agree with the code, which says nothing about whether either matches
what the issue asked for.

Run: 2026-10-11, at commit on `main` after the D1–D9 decisions.

## Result

| | |
|---|---|
| Closed issues | 22 |
| Acceptance criteria | 184 |
| Verified passing | 176 |
| **Superseded by a later decision** | **8, across 5 issues** |
| Failing for any other reason | 0 |

Nothing is quietly broken. Everything that no longer holds, no longer holds *on
purpose*, and each is now annotated on its issue.

## How it was checked

Three passes, each checking something the others could not.

**Commands** — [`backend/scripts/verify-criteria.sh`](../backend/scripts/verify-criteria.sh),
kept in the repository. 30 checks that the things an issue claims you can *run*
actually run on a clean tree: `uv sync`, both ruff checks, `lint-imports`, the
frontend build and typecheck, the migration up and down, `ration-seed` twice for
idempotency, the production refusal, and spec validation.

This is the pass worth keeping. It catches what tests cannot — a command that
works only because of state left behind by a previous one.

**Behaviour** — 50 checks against a loaded reference fixture: frozen types, the
no-float AST scan, totals composing line to day, batch portions never
multiplying, fixture shape and provenance, the shopping pipeline, and the
validator's codes and ordering.

**API and persistence** — 39 checks against a migrated, seeded database and a
live `TestClient`: table count, no `Float` nutrition column in the migrated
schema, cascade deletion, repositories returning domain types with no ORM object
escaping, the full auth and session surface, and the contract's shape.

The second and third passes were scaffolding for this audit and were not kept.
What they verify is largely restated by the test suite; their unique value was
the one-time cross-check of issue text against code, and that value is this
document.

## The eight superseded criteria

Each is now a note at the top of its issue, so a reader of the closed issue sees
it immediately rather than believing a false claim.

### #5 — `yield_factor` must be in `(0, 2]`

Now `(0, 5]`. The bound assumed cooking only ever removes water. Rice noodles are
about 2.85: 180 g dry yields 510 g cooked.

### #8 — "fourteen meal modules"

Section 8 contains **19**. The 14 came from section 14's feedback table, which
groups the shakes and the overnight oats into one row each.

### #8 — module totals "within 5% or 20 kcal" of section 9

Now 20% on calories, 35% on protein, and reframed as a sanity check rather than a
fit. The catalog carries reference nutrition values and is deliberately not tuned
to reproduce section 9's totals ([`decisions.md`](decisions.md) D1).

### #11 — shopping quantities "within 5%"

Now 15%, with staples compared on presence and piece counts against the
document's stated range. 5% is not achievable against a list that says "около
30 г" and "не менее 125 мл".

### #12 — slot protein checked as a band

`protein_max` is nullable and null means no ceiling (D2). Protein is a floor: a
ceiling flags a plan for being better than it was asked to be.

### #16 — three criteria: zero errors, zero warnings, exactly one `DAY_UNPLANNED`

The reference week now produces **2 errors, 11 warnings and 1 info**. This is the
most important entry in this document.

When #16 was implemented, the catalog carried nutrition values tuned until each
dish matched the figure section 9 states for it. Under those values the week
*could not fail*: the instrument had been bent until it agreed with the thing it
was measuring. The criterion was satisfied by construction, and satisfying it
proved nothing.

D1 replaced those with reference values. What the week reports now is true:

```
day 0   1578 kcal   100 short   training day
day 3   1598 kcal   100 short   training day
```

**The plan feeds least on the two days that end with resistance training.** No
self-consistent fixture could have surfaced that.

#16's final criterion — *"if the reference plan cannot validate cleanly, the
profile's budgets are adjusted to the document's stated ranges"* — was
deliberately **not** followed. Adjusting targets until the plan passes is the
same circularity as the fitted catalog, moved one table across (D3).

## What this says about the process

Seven of the eight superseded criteria sit in issues **#5–#16**, and all of those
were groomed before the data they describe existed. The pattern already recorded
in [`tasks.md`](tasks.md) holds under audit: grooming a data-dependent task ahead
of the data produces confident, wrong criteria.

The eighth (#12's protein band) is different and more interesting — it was wrong
about the *domain*, not the data. A protein ceiling reads as symmetric with a
calorie ceiling and is not, and only running real numbers through it made that
visible.

Both argue the same thing: criteria written before contact with reality should
be treated as provisional, and an audit like this is how the record gets
corrected instead of quietly diverging.

## What was not audited

Issues #23–#54 are open and unimplemented. Issue **#54** (yield calibration)
needs a kitchen scale, not a verification pass — every yield factor remains an
estimate back-solved from the document's own ratios, which is why every gap in
`uv run ration-yields` currently reads ±1%. That column means something only
after a real measurement.
