# Evidence for ShoppingListServerErrors — 20261116T171010Z-ShoppingListServerErrors

Gathered 2026-11-16T17:10:10.760483+00:00 by `gather_evidence.py`, from telemetry only.

## The alert

- Route: `/api/plans/{plan_id}/shopping-list`
- Release: `dev` in `development`
- 4 server errors in 5m (threshold 3)
- Firing since: 2026-11-16T17:02:46.167Z

## Metrics

- First 5xx in the last hour: **2026-11-16T16:24:10.817000+00:00** (the alert itself started firing at 2026-11-16T17:02:46.167Z)
- Peak: 6 5xx in a 5-minute window
- Failing for 16 of the last 60 minutes
- Requests by status, counter total (exact for this process): {'500': 8}
- Requests by status, estimated over 15 minutes: {'500': 6.1, '200': 1.0} — extrapolated, and smoothed across a restart, so trust the counter above it

## Trace

- Trace `fd546701c0a092448f2bb3f3a78603ac`, 5 spans
- **Failing stage: `shopping_list.convert_yield` (ERROR)**
- Exception type: `UnrecognisedUnitError`
- Stages that completed: shopping_list.load_catalog, shopping_list.load_plan, shopping_list.expand_entries

> Exception message: withheld by design: the exception message names the catalog row that failed, and telemetry carries no dietary data (HLD §8, #57). Identifying the row is a human step against the database — see docs/runbooks/shopping-list-5xx.md, step 5.

## Logs

- 1 line(s) carrying that trace id:
  - `request.failed` — ERROR, status 500

## What is missing

Nothing — all four queries returned.

No ingredient, module, plan, target or feedback value appears above, and none
can: every field comes from a route template, a count, a status code, a span
name or an exception class (HLD §8, #57).
