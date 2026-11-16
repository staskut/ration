# Observability stack

The whole system with telemetry attached: the application and Postgres exactly
as the root `docker-compose.yml` describes them, plus the chain
[HLD §5](../docs/hld.md) fixes.

```
app --OTLP/HTTP--> collector --> Prometheus   metrics
                             --> Loki         logs
                             --> Tempo        traces
                                     |
                                  Grafana, provisioned from this directory
```

The application is not restated here. `compose.yaml` pulls in the root compose
file with Compose's `include:` and overrides one thing — the app's telemetry
environment — in `telemetry.yaml`. There is one definition of the app and one of
the database, so the two stacks cannot drift into being different systems.

## Run it

From the repository root, with a `.env` as the [root README](../README.md)
describes:

```bash
docker compose -f observability/compose.yaml up
```

Then **<http://localhost:3000>** for Grafana. No login: the stack is local, and
a credential in the repository is a credential that eventually reaches a
deployment.

| | URL | What it is |
|---|---|---|
| App | <http://localhost:8000> | the thing being observed |
| Grafana | <http://localhost:3000> | all three signals |
| Prometheus | <http://localhost:9090> | metrics, and the alert rules |
| Alertmanager | <http://localhost:9093> | where a firing alert goes |
| Alert sink | <http://localhost:9099/latest> | the payload that was delivered |
| Loki | <http://localhost:3100> | logs |
| Tempo | <http://localhost:3200> | traces |
| Collector | <http://localhost:4318> | OTLP/HTTP, for an app run from source |

Every published port has an override: `RATION_PORT`, `GRAFANA_PORT`,
`PROMETHEUS_PORT`, `LOKI_PORT`, `TEMPO_PORT`, `OTEL_HTTP_PORT`,
`OTEL_METRICS_PORT`, `ALERTMANAGER_PORT`, `ALERT_SINK_PORT`.

**If port 8000 is already taken** — most likely by `docker compose up` from the
root, which publishes the same port, or by an app you are running from source —
the app container will fail to start with `address already in use`, or worse,
it will start and your requests will quietly reach the *other* thing. Set
`RATION_PORT` in `.env` or on the command line:

```bash
RATION_PORT=8010 docker compose -f observability/compose.yaml up
```

That failure is worth knowing in this exact form, because it does not look like
a port problem: the app answers, and nothing it answers appears in Grafana.

## Walkthrough: one request, three signals

Make a request worth looking at. Log in as the planner, take the seeded plan,
and ask for its shopping list — the instrumented path (HLD §7):

```bash
curl -s -c /tmp/ration.jar -X POST http://localhost:8000/api/auth/login \
  -H 'content-type: application/json' \
  -d '{"email":"planner@ration.example","password":"correct-horse-battery"}'
PLAN=$(curl -s -b /tmp/ration.jar http://localhost:8000/api/plans \
  | python3 -c "import sys,json;print(json.load(sys.stdin)[0]['id'])")
curl -s -b /tmp/ration.jar "http://localhost:8000/api/plans/$PLAN/shopping-list" >/dev/null
```

Prometheus scrapes every 15 seconds, so wait that long before the first panel
has anything in it.

### 1. Metrics — Grafana → Explore → Prometheus

```promql
sum by (http_route, http_response_status_code) (
  rate(http_server_request_duration_seconds_count{http_route="/api/plans/{plan_id}/shopping-list"}[5m])
)
```

The label is the route **template**. Two different plan ids land on one series,
because a raw path carries a plan id and a plan id is one real person's dietary
record (HLD §8).

The deployed version is on every series, not only on `target_info`:

```promql
sum by (service_version) (http_server_request_duration_seconds_count)
```

That works because the collector's Prometheus exporter is configured with
`resource_to_telemetry_conversion`. Without it, `service.name`,
`service.version` and `deployment.environment` stay in a separate `target_info`
series and a query by version returns nothing at all — which looks exactly like
"this release has had no traffic".

### 2. Trace — Grafana → Explore → Tempo → Search

Service `ration-api`, span name `GET /api/plans/{plan_id}/shopping-list`. Open
the newest result. Under the request span are the eight pipeline stages of
HLD §4, in order:

```
shopping_list.load_catalog
shopping_list.load_plan
shopping_list.expand_entries
shopping_list.convert_yield
shopping_list.merge_ingredients
shopping_list.round_packages
shopping_list.group_sections
shopping_list.merge_checked
```

Each carries `ration.items_in` and `ration.items_out`, so "this stage is slow"
can be read against "this stage had 114 rows".

Copy the trace id from the top of the view.

### 3. Logs — Grafana → Explore → Loki

```logql
{service_name="ration-api"} | trace_id=`PASTE_THE_TRACE_ID`
```

One line comes back: `request.finished`, with that request's route template,
status code and duration.

`| trace_id=` and not `|= "trace_id"`. The line body is the message constant;
everything else travels as an OTLP attribute, which Loki 3 keeps as structured
metadata rather than in the text. A line filter searching the body finds
nothing.

The same thing without leaving the trace: in Tempo, the **Logs for this span**
button runs that query for you, and in Loki each line's `TraceID` field links
back. That is the correlation of HLD §7, clickable.

## The dashboard

**Shopping list — the instrumented path**, in the Ration folder, provisioned
from `grafana/dashboards/shopping-list.json`. Request rate, error rate and p95
latency for the one instrumented route, with a release picker, and a panel
breaking requests down by status code.

p95 is computed by the query from the histogram's buckets. The application
reports buckets and never a percentile: a percentile computed per process and
per scrape interval cannot be summed with another one, so an app that reports
its own p95 reports a number nobody can aggregate.

The bucket boundaries are set explicitly, and that detail decides whether the
panel means anything. The SDK's defaults — 0, 5, 10, 25, … — suit a histogram
measured in milliseconds; against a duration in seconds every request this
service serves falls into the first bucket, and `histogram_quantile` over one
bucket can only answer "somewhere between 0 and 5 seconds". That is a panel
that is always wrong and never obviously wrong. With the semantic convention's
boundaries the same traffic reads p95 ≈ 17 ms.

## The alert

One rule, in `prometheus/rules.yml`: **three or more 5xx on
`/api/plans/{plan_id}/shopping-list` in five minutes**, evaluated every minute,
no pending period, carrying the deployed version.

An absolute count rather than a ratio, because this system has two users: a
ratio is undefined at three in the morning when the denominator is zero, and
100% when one request out of one fails. Three rather than one, because one 500
is a blip and the failure this exists to catch — an unrecognised unit reaching
the raw-weight conversion ([#60](https://github.com/staskut/ration/issues/60))
— fails every request for the affected plan and clears three in seconds.

There is deliberately **no no-data alert**. `fly.toml` runs
`min_machines_running = 0`, so an idle app genuinely emits nothing for hours,
and paging about a quiet Tuesday teaches whoever carries this to ignore it. The
availability case is [#72](https://github.com/staskut/ration/issues/72).

### Test the rule

Against the same file the stack loads, not a copy of the expression:

```bash
docker compose -f observability/compose.yaml exec prometheus \
  promtool test rules /etc/prometheus/rules_test.yml
```

Four cases: three failures fire; two do not; no traffic at all does not; a
stream of successful requests does not. They run at 15s, the scrape interval
`prometheus.yml` uses, and that is load-bearing — `increase()` extrapolates
from the samples in the range, and at a coarse resolution three real errors
evaluate to 2.5 and the rule would not fire on the third error.

### Watch it fire

```bash
python3 observability/fire_alert.py
```

About a minute and a half: it reports 5xx points for the route to the collector,
raising the counter one step at a time with a real pause between steps, because
Prometheus *scrapes* — a counter that arrives already at four looks flat and
`increase()` over five minutes is zero.

Then <http://localhost:9090/alerts> shows the rule firing, and the delivered
payload is in `observability/alerts/latest.json`, also readable at
<http://localhost:9099/latest> and as one line in
`docker compose -f observability/compose.yaml logs alert-sink`.

This exercises the rule, the routing and the payload — the alert that fires is
the one the stack loaded. It does **not** exercise the application failing:
there is no route in the image that can be made to return 500 on demand, because
a deployable artefact with a break-glass endpoint in it is a worse idea than a
slow demo. The real pipeline failing is #60's staged incident.

### The payload, field by field

It is the interface #60's responder consumes, so it is documented rather than
merely produced.

| Field | | |
|---|---|---|
| `labels.alertname` | `ShoppingListServerErrors` | which rule |
| `labels.route` | `/api/plans/{plan_id}/shopping-list` | route **template** |
| `labels.version` | e.g. `a1b2c3d` | the release that is failing |
| `labels.environment` | `development` · `staging` · `production` | where |
| `labels.severity` | `page` | |
| `annotations.observed_count` | e.g. `4` | how many 5xx |
| `annotations.window` · `threshold` | `5m` · `3` | over what, against what |
| `annotations.tempo_query` | TraceQL | the failing traces, scoped to that route and release |
| `annotations.runbook` | `docs/runbooks/shopping-list-5xx.md` | what to do |
| `annotations.summary` | one sentence | all of the above, for a human |

`version` is `dev` when the build was not told which release it is — never
blank, never missing. The deploy workflow passes the short SHA of the commit CI
tested, so the version in an alert is something that can be checked out and
rolled back, and `GET /health` returns the same string for any environment you
can reach.

There is no plan id, profile id, ingredient, target or feedback value anywhere
in it, and there cannot be: every field is a route template, a release, a count
or a constant.

## What is deliberately not in here

No ingredient name, module name, calorie or protein figure, nutrition target,
rating, feedback value or email reaches any of these three stores, and no
entity id does either — not the plan id, not even an opaque one. The complete
list of keys telemetry may carry is
[`backend/src/ration/observability/attributes.py`](../backend/src/ration/observability/attributes.py),
each with the source of its value, and every key is set through a gate that
raises outside production. A test exercises the real endpoint against the
reference plan and fails if any emitted attribute or log field contains catalog
or profile content.

The enforcement is at the emitter. Nothing here inspects what *arrives* in
Tempo, Loki or Prometheus — that is
[#68](https://github.com/staskut/ration/issues/68).

## When the collector is down

```bash
docker compose -f observability/compose.yaml stop collector
```

The application keeps serving: `GET /plans/{id}/shopping-list` still returns 200
with the same body, in the same handful of milliseconds (9 ms observed with the
collector up, 9 ms with it stopped). Export happens on the SDK's own batch
thread, so a request never waits on it and never fails because of it.

Start the collector again and the signals from *new* requests appear. The app
does not need restarting; what was emitted while the collector was down is lost,
which is the trade a batch exporter makes and the reason telemetry is not a
place to put anything you must not lose.

## Retention and disk

Seven days in all three stores, and Prometheus is additionally capped at 512 MB.
A laptop stack with unbounded storage is a surprise nobody asked for, and three
signals that expire at different times cannot be correlated at the edges.

Each store writes to a named volume, so `docker compose -f
observability/compose.yaml down` keeps the data and `down -v` discards it.

## Files

| | |
|---|---|
| `compose.yaml` | the stack; includes the root compose file |
| `telemetry.yaml` | the app's telemetry environment, and nothing else |
| `collector/config.yaml` | receive OTLP, fan out to the three stores |
| `prometheus/prometheus.yml` | scrape the collector |
| `prometheus/rules.yml` | alert rules ([#59](https://github.com/staskut/ration/issues/59)) |
| `loki/loki.yaml` · `tempo/tempo.yaml` | single-binary, filesystem storage |
| `grafana/provisioning/` | data sources and the dashboard loader |
| `grafana/dashboards/` | the dashboards themselves ([#59](https://github.com/staskut/ration/issues/59)) |
