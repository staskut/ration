# Runbook: 5xx on the shopping list

**Alert:** `ShoppingListServerErrors` — three or more server errors on
`GET /api/plans/{plan_id}/shopping-list` in five minutes.

**What the person affected sees:** the follower, standing in a shop, opens the
shopping list and gets an error. There is no cached copy and no offline mode
(PRD §7), so for them the system is simply down.

**Before you start:** the telemetry contains no dietary data at all — no
ingredient, no plan, no target (HLD §8). You will be able to tell *which stage*
of the pipeline is failing and *on which release* without ever seeing what
anybody eats. Finding the specific row is step 5, and it is a human step for
that reason.

---

## 1. Read the alert

```bash
cat observability/alerts/latest.json
```

Take the **release** (`labels.version`), the **environment**, the **observed
count** and the **`tempo_query`** annotation. If `version` reads `dev`, the
release was built without being told its version — note it and carry on; the
deploy workflow sets it, so `dev` in a deployed environment is itself a finding.

## 2. Gather the evidence

```bash
python3 observability/incident/gather_evidence.py observability/alerts/latest.json
```

It prints an incident id and writes `bundle.json` and `summary.md`. Read the
summary. It reads telemetry only — no database — and records a missing signal
as missing rather than guessing.

## 3. Find the failing stage

In the summary, or in Grafana → Explore → Tempo with the alert's `tempo_query`.

The shopping list runs as eight spans, one per pipeline stage of HLD §4
(`backend/src/ration/observability/names.py` lists them in order). Exactly one
will carry ERROR, and the stages before it will have completed. That tells you
where the failure is without reading any code:

| Failing stage | What it means |
|---|---|
| `shopping_list.load_catalog` · `.load_plan` | the database, not the engine |
| `shopping_list.expand_entries` | a plan entry references a module that is not there |
| `shopping_list.convert_yield` | the raw-weight conversion — a yield factor or a **unit** the system does not model |
| `shopping_list.merge_ingredients` · `.round_packages` | arithmetic on a catalog value; look at `ration.items_in` against `items_out` |
| `shopping_list.group_sections` · `.merge_checked` | assembly or the follower's check-off state |

Note the `exception.type` on the failing span. The exception's **message is not
recorded anywhere** — it names the catalog row that failed, and telemetry
carries no dietary data. That is by design, not a gap in the evidence.

## 4. Decide whether it is the release

In the dashboard, switch the **Release** picker, or run:

```promql
sum by (service_version, http_response_status_code) (
  increase(http_server_request_duration_seconds_count{http_route="/api/plans/{plan_id}/shopping-list"}[30m])
)
```

If the 5xx start exactly when `service_version` changes, it is the release.
**Roll back first and diagnose afterwards** — see `docs/release-process.md`. A
follower in a shop is not a good audience for a careful investigation.

If the failures span two releases, it is data or a dependency, not the deploy.

## 5. Find the bad row — a human step, against the database

Only now, and only a person. The agent may not do this (autonomy policy, F2).

For `UnrecognisedUnitError` out of `shopping_list.convert_yield`, the cause is
an ingredient whose `package_unit` is not one of `g`, `ml`, `pcs` or null. The
API's schema refuses anything else, so such a row got in some other way — a
migration, a seed, or somebody fixing data by hand:

```sql
SELECT slug, package_unit FROM ingredients
WHERE package_unit IS NOT NULL AND package_unit NOT IN ('g', 'ml', 'pcs');
```

Locally that is:

```bash
docker compose -f observability/compose.yaml exec -T db \
  psql -U ration -d ration -c \
  "SELECT slug, package_unit FROM ingredients WHERE package_unit IS NOT NULL AND package_unit NOT IN ('g','ml','pcs');"
```

Fix the row to a unit the system models — and note that `openapi.yaml` and the
request schema were the only thing standing between the catalog and this
failure. Closing that gap properly (a column constraint, or validating in the
seed loader) is
[#70](https://github.com/staskut/ration/issues/70).

## 6. Confirm it is over

```bash
curl -s -o /dev/null -w '%{http_code}\n' \
  -b <(printf '') "$BASE/api/plans/$PLAN/shopping-list"
```

and watch the error-rate panel drop to zero. Alertmanager sends a `resolved`
payload to the sink, which lands in `observability/alerts/` beside the firing
one — that file is what tells you the alert cleared rather than was forgotten.

## 7. Write it down

Append to the incident record under `observability/incident/records/`, and run
the checker:

```bash
python3 observability/incident/check_record.py observability/incident/records/<id>.json
```

---

## The awkward cases

**The alert fired but there is no usable trace.** Tempo keeps seven days, but a
trace only exists if telemetry was on when the request failed — and it is off
locally and absent on Fly (#62). The metrics still tell you the route, the
release, the count and the time of the first failure, which is enough to decide
on a rollback. Record the trace as missing; `gather_evidence.py` already does.
Do not substitute a trace from a different window.

**One bad row fails more than one route.** The catalog is shared, so an
ingredient that breaks the shopping list also breaks the prep plan
(`GET /plans/{id}/prep-plan`), which has no alert on it — only the shopping
list is instrumented (HLD §7). After fixing the row, check the other derived
endpoints by hand rather than assuming the alert clearing means the system is
well.

**The alert is firing in production and you cannot reach the telemetry.**
Nothing ships signals off a Fly machine yet (#62). `GET /health` returns the
release, `fly logs` shows the structured lines, and the decision — roll back or
not — can be made from those two alone.
