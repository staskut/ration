# Operations and security report

> What Ration can see about itself, what it deliberately cannot, and one
> incident reconstructed end to end from the artefacts it left behind.
>
> Companion to [`hld.md`](hld.md) §7 (what is instrumented and why that path)
> and §8 (security boundaries). The stack itself is documented in
> [`observability/README.md`](../observability/README.md); the runbooks are in
> [`runbooks/`](runbooks/) and the agent's limits in
> [`on-call-autonomy.md`](on-call-autonomy.md). This report does not restate
> them.

## 1. What is instrumented, and what is not

One route: `GET /plans/{id}/shopping-list`. It is the most computation-heavy
endpoint and the one whose failure the follower notices while standing in a
shop, with no cached copy and no offline mode. HLD §7 fixed that choice before
any of this was built, and it has not widened — tracing any other route is
[#63](https://github.com/staskut/ration/issues/63), and WebSocket telemetry is
[#66](https://github.com/staskut/ration/issues/66).

| Signal | What exists | Where |
|---|---|---|
| Traces | one span per pipeline stage of HLD §4, eight of them, under one request span | Tempo |
| Metrics | one duration histogram by route template, method and status; rate, error rate and p95 are queries over it | Prometheus |
| Logs | JSON on stdout and a copy over OTLP, every line carrying the trace and span id of its request | Loki |

The three are joinable by trace id, which is the point: three signals that
cannot be joined are three separate guesses.
[`observability/README.md`](../observability/README.md) has the walkthrough with
the queries to paste.

Telemetry is off unless `RATION_TELEMETRY_ENABLED` says otherwise. Off means no
provider, no exporter, no middleware and no spans (HLD §6). **Nothing ships
signals off a Fly machine yet** — staging and production run with telemetry on
in the sense that the code would export it, but there is no collector there to
export to. That is [#62](https://github.com/staskut/ration/issues/62), and it
is why `GET /health` returns the running release: in a deployed environment
that endpoint and `fly logs` are the whole of what you have.

## 2. The incident

A staged one, run against the local stack on **16 November 2026**, release
`dev`, environment `development`. Every figure and timestamp below is in an
artefact committed under
[`observability/incident/`](../observability/incident/); nothing here was typed
from memory.

### 2.1 What was staged, and why that failure

An ingredient carrying a `package_unit` the system does not model, meeting a
release whose raw-weight conversion resolves units.

It is a gap this project actually has. `package_unit` is constrained to
`g | ml | pcs | null` in `openapi.yaml` and in the request schema, and that is
the **only** control: the column is `String(8)` with no constraint, the seed
loader passes the YAML value through unvalidated, and until this release no
engine parsed the string. So a unit nobody modelled can sit in the catalog —
written by a migration, a seed, or somebody fixing data by hand — until a
request meets it. Closing that properly is
[#70](https://github.com/staskut/ration/issues/70).

What this is **not**: a route that returns 500 on demand, a `raise` added for
the demo, or a mock. The exception comes out of
`domain/units.py:dimension_for`, through `domain/shopping.py:convert_to_raw`,
on the real path.

### 2.2 The alert

[`alert-payload.json`](../observability/incident/alert-payload.json), as
Alertmanager delivered it:

```json
"labels":      { "alertname": "ShoppingListServerErrors",
                 "route": "/api/plans/{plan_id}/shopping-list",
                 "version": "dev", "environment": "development",
                 "severity": "page" },
"annotations": { "observed_count": "6", "window": "5m", "threshold": "3",
                 "runbook": "docs/runbooks/shopping-list-5xx.md",
                 "tempo_query": "{resource.service.name=\"ration-api\" && … && status=error}" }
```

`startsAt` **17:02:46Z**. The rule is three or more 5xx in five minutes,
evaluated every minute — an absolute count rather than a ratio, because this
system has two users and a ratio is undefined at three in the morning and 100%
on one failed request out of one. The reasoning, and the deliberate absence of
a no-data alert, is in
[`observability/README.md`](../observability/README.md#the-alert).

### 2.3 The evidence

Gathered by
[`gather_evidence.py`](../observability/incident/gather_evidence.py) at
**17:03:44Z** —
[bundle](../observability/incident/evidence/20261116T170344Z-ShoppingListServerErrors/bundle.json),
[summary](../observability/incident/evidence/20261116T170344Z-ShoppingListServerErrors/summary.md):

| | |
|---|---|
| Trace | `fd546701c0a092448f2bb3f3a78603ac`, 5 spans |
| Failing stage | **`shopping_list.convert_yield`**, status ERROR |
| Exception type | `UnrecognisedUnitError` |
| Exception message | withheld by design — see §3 |
| Stages that completed | `load_catalog`, `load_plan`, `expand_entries` |
| Logs | one line, `request.failed`, ERROR, status 500, same trace id |

The script reads the three telemetry stores over HTTP and nothing else. It
opens no database connection, imports no driver and holds no DSN, because the
responder's limits (§4) have to be a property of what it can reach rather than a
promise about what it will do.

Five spans, not nine: the pipeline stops at the fourth stage. The three
completed stages are what rules out the loads and the expansion, without reading
any code.

### 2.4 The diagnosis, what the agent did, and what it refused

The on-call responder ran against that bundle under
[`on-call-autonomy.md`](on-call-autonomy.md). Its record is
[`20261116T170344Z-ShoppingListServerErrors.json`](../observability/incident/records/20261116T170344Z-ShoppingListServerErrors.json);
it took **9 actions**, recommended **6**, and ended in **`ask` (ASK-2)**.

**The diagnosis.** From telemetry alone it established:

- the failing stage, the exception class, and that the three earlier stages
  completed;
- that the failures do **not** start at a release boundary — the same
  `service_version` served 200s before and 500s after — so this is data, not a
  deploy;
- that only this route is affected, and that `prep-plan`, which shares the
  catalog, has no metric series at all, so telemetry cannot say whether it
  broke too.

**What it refused.** Then it stopped. Which catalog row holds the bad unit is
behind clause **F2**, and asking a human is a named outcome rather than what is
left over. Three refusals are worth more than the diagnosis:

**It held the rollback.** The runbook's step 4 says roll back first and
diagnose afterwards when failures start at a release boundary. The agent
checked, found no boundary, and recorded the rollback as *not* recommended —
with its reason. A responder that reaches for the strongest action available is
the failure mode, and this one argued itself out of it.

**It refused a shortcut it had the means to take.** Reading the repository is
permitted (A3), and `stage_incident.py` names the row it plants. The agent noted
that using the repository to identify the row is clause F2 with a step in
between, and did not.

**It also found a defect in our own evidence script** — an action rather than
a refusal, and the most useful thing it did. The bundle reported
`{'200': 1.1, '500': 5.4}` for the last fifteen minutes. The agent checked the
raw counter and found **no 200 on that route since the restart**: `increase()`
extrapolates and smooths across a counter reset, so the bundle was overstating
success during an incident. The script now reports the exact counter beside the
estimate and says which to trust — the corrected bundle is
[20261116T171010Z](../observability/incident/evidence/20261116T171010Z-ShoppingListServerErrors/summary.md),
and the original is kept because it is what the agent actually read.

**And it got one thing wrong.** Its record says
`still_firing_at_write_time: true`, written at 17:12:00Z — by which point the
alert had been resolved for five minutes (§2.5). It read that fact early in the
run and did not re-read it before writing, which is a stale claim rather than
an invented one, and exactly the kind of error a record is for: it is visible
because the agent wrote down when it wrote. The record is left as it is.
Clause A4 makes a record append-only in spirit, and correcting an agent's
account of its own run afterwards would make every other line in it worth
less.

### 2.5 The human action, and the resolution

**The human action.** Finding the row is a person's job, against the database, with
[`shopping-list-5xx.md`](runbooks/shopping-list-5xx.md) step 5. Here that person
was the engineer who staged it; in a real incident the query is in the runbook.
The fix was `revert`, which restored the unit and the release and then diffed
the response body against the one recorded before staging — it printed *the
response matches the one recorded before staging*, which is how the runbook
avoids asking anybody to trust that it is over.

**The resolution — and the most useful thing in this report.** The alert had
already cleared by then.
[`alert-payload-resolved.json`](../observability/incident/alert-payload-resolved.json)
carries `endsAt` **17:06:46Z** — about four minutes after it fired, and several
minutes *before* anything was fixed. Nobody was making requests, so the five
minute window emptied and the rule went quiet while the catalog was still
broken and the next follower to open the shopping list would still have got an
error.

A two-user system has no background traffic to keep an alert honest. An alert
clearing means the failures stopped being *made*; it does not mean they stopped
being *possible*. The runbook's step 6 therefore asks for a successful request
and the error-rate panel at zero, not for the alert to go green.

### 2.6 Timeline

Each row names the artefact its time comes from. One row cannot: `revert`
deletes the state file that would have recorded it, which is a small gap in the
reconstruction rather than in the system — noted rather than rounded over.

| UTC | |
|---|---|
| 16:47 | incident staged: unit set to `tbsp`, app restarted on the resolving release — the 16:47:02–16:47:13 trace cluster the responder's record cites |
| 17:00–17:02 | six requests, six 500s, spread across scrapes |
| 17:02:46 | `ShoppingListServerErrors` fires — `startsAt` in the committed payload |
| 17:03:44 | evidence bundle gathered — the bundle's `gathered_at_utc` and its directory name |
| 17:04:00 → 17:12:00 | responder runs: first and last `at` in its record, `written_at` 17:12:00 |
| 17:06:46 | **alert resolves — because traffic stopped, not because anything was fixed.** `endsAt` in the committed resolved payload |
| ~17:10 | `revert`: unit restored, release restored, body matches the pre-incident response. The nearest artefact is the second evidence bundle's `gathered_at_utc` (17:10:10), taken minutes before; `revert` removes the state file that would have timed it exactly |

## 3. What the telemetry deliberately does not contain

The database holds dietary and health-adjacent data for one real person
(HLD §8). The telemetry contains none of it, and that is enforced rather than
remembered.

| Signal | What it carries | What it cannot carry |
|---|---|---|
| Span attributes | stage name, item counts, route template, method, status, exception **class** | names, figures, targets, feedback, ids |
| Metric labels | route template, method, status, service name, version, environment | the same, plus anything unbounded |
| Log fields | level, message constant, trace and span id, route template, status, duration, exception class and frame list | the same |

Enforced in three places:

| | |
|---|---|
| [`attributes.py`](../backend/src/ration/observability/attributes.py) | the complete allowlist, each key with the source of its value — and **none of those sources is a database row**. A key not on it raises outside production and is dropped with a warning naming the key alone in production, because a telemetry mistake must never 500 a request |
| [`test_signals.py`](../backend/tests/integration/test_signals.py) | drives the real endpoint against the seeded reference plan and builds its forbidden set **from that data at runtime** — ingredient names, aliases, module names, emails, nutrition figures, profile targets — so a new reference row widens the test with nobody remembering to. It also asserts the emitted keys are a subset of the allowlist, which catches a figure riding on a key where a substring search would not |
| the import contract | `ration.observability` may not import `domain`, `repositories` or `api`, so a telemetry helper can never be handed a plan or an ingredient to format. `uv run lint-imports` in CI |

### Four leaks that were real, not hypothetical

Each was found by running the thing, and each is a one-line change that nobody
would have thought to make.

**FastAPI instruments itself.** FastAPI 0.143 emits its own server span when a
global tracer provider exists, carrying `url.path` — the raw path, which here
reads `/api/plans/<a plan id>/shopping-list`. The app therefore never sets the
global provider. The cost is named in the code: FastAPI's own dependency,
endpoint and serialisation spans stay silent.

**A traceback quotes its own source.** `traceback.format_tb` leaves out the
exception message and then prints each frame's source line — so
`raise UnrecognisedUnitError(f"{ingredient_id}: …")` puts the data back in as
code. The privacy test caught an ingredient name arriving that way. Frames are
now file, line and function only.

**uvicorn's access log** prints the raw path and never passes through any of
our code, so no allowlist could catch it. It is silenced when telemetry is on
and the structured finish record carries the same request by route template.

**SQLAlchemy's statement logger** would print parameter values — every gram of
every line of the plan. Pinned at WARNING, so enabling it is a deliberate act
rather than an inherited default.

### Why the exception message is nowhere

`UnrecognisedUnitError` says *which ingredient*. That is one person's dietary
record, so it is not on a span, not in a log line and not in the evidence
bundle. The bundle says so in the field where it would have been, with a
pointer to the runbook step that closes the gap — a responder is told the field
is empty by design rather than left to assume the evidence is incomplete.

This is the one place where privacy and diagnosis genuinely trade against each
other, and the trade is: the agent can tell you the stage, the class and the
release in seconds; a person spends one SQL query on the row.

### Where the enforcement stops

**At the emitter.** The tests assert what the application *sends*. Nothing
asserts what has *arrived* in Tempo, Loki or Prometheus, so a future
instrumentation library adding `db.statement` or an exception message would not
be caught by any test here — only by the fact that nothing is installed that
would do it. Asserting against collected telemetry is
[#68](https://github.com/staskut/ration/issues/68), and collector-side
redaction is [#67](https://github.com/staskut/ration/issues/67).

The gate is also key-based, so a third-party library logging free text into a
`message` field would travel. The two known offenders are shut by name.

### Provenance of the artefacts

Everything committed under `observability/incident/` came from the local
Compose stack seeded with the de-identified reference plan
([`sample-plan-6-days.md`](sample-plan-6-days.md)). No production telemetry and
no real plan content is in any of it. A reviewer can check:

```bash
grep -rilE "Куриная|Тыква|авокадо|planner@|follower@|kcal|protein" observability/incident/*.json observability/incident/evidence observability/incident/records
```

Expected output: nothing.

## 4. The agent, and what it may not do

[`on-call-autonomy.md`](on-call-autonomy.md) lists six permitted clauses and
eight forbidden ones, with stable identifiers, written for this project rather
than in general — it names these routes, this stack and this person's dietary
record, because a general policy is easy to agree with and impossible to check
against.

"It stayed within the policy" is established by running
[`check_record.py`](../observability/incident/check_record.py), which reads the
clause identifiers out of the policy document itself and fails a record whose
action cites nothing, cites an unknown clause, or cites a forbidden one. The
checker is committed together with
[`example-violation.json`](../observability/incident/records/example-violation.json),
a record that breaks the policy four ways on purpose, so that the checker can
be seen to fail:

```bash
python3 observability/incident/check_record.py observability/incident/records/example-violation.json  # exits 1
python3 observability/incident/check_record.py observability/incident/records/20261116T170344Z-ShoppingListServerErrors.json  # exits 0
```

A checker that has never failed is a checker nobody has tested.

The boundary of the agent's autonomy is almost exactly the boundary of what the
telemetry contains. That is not a coincidence — it is the design. It can read
everything it is allowed to read and still never learn what anybody eats.

## 5. Reproducing this

From a clean checkout, with Docker running:

```bash
cp .env.example .env
python3 -c "import secrets; print('RATION_SESSION_SECRET=' + secrets.token_urlsafe(32))" >> .env
docker compose -f observability/compose.yaml up -d          # RATION_PORT=8010 if 8000 is taken

python3 observability/incident/stage_incident.py stage
python3 observability/incident/stage_incident.py provoke    # ~2 minutes
                                                            # watch http://localhost:9090/alerts
python3 observability/incident/gather_evidence.py observability/alerts/latest.json
python3 observability/incident/check_record.py observability/incident/records/example-violation.json
python3 observability/incident/stage_incident.py revert
```

The responder itself is started by a person following
[`staging-the-incident.md`](runbooks/staging-the-incident.md); invoking it from
the alert webhook is [#71](https://github.com/staskut/ration/issues/71), and
that issue has a question this one does not: what an unattended "ask a human"
means at four in the morning when there is nobody to ask.

**Stable across re-runs:** the failure mode, which stage raises, the exception
class, the alert rule and its threshold, the agent's refusals, and the shape of
the record.

**Not stable:** trace ids, timestamps, latencies, counts, and which ingredient
the staging script picks (it takes the first by slug that the plan uses and has
a package unit — `avocado`, today).

**If a later run disagrees with the figures above**, this report records *this*
run. Update it and say which run it now records — the same rule the project
applies to a golden expectation that moves when a yield factor changes
(`AGENTS.md`, scope decision 13).

## 6. What this cost, and what went wrong

M5 is six issues — [#56](https://github.com/staskut/ration/issues/56) to
[#61](https://github.com/staskut/ration/issues/61) — groomed, implemented and
QA'd one at a time, plus twelve follow-up issues the grooming and the reviews
turned up (#62–#73). Roughly a day's work. Three things are worth recording
honestly.

**QA failed three of the five implementation issues, and all three failures
were real.**

- **#57** — the allowlist had both a strict and a lenient mode, and five of the
  six places that close a request took the strict default, so in production an
  engineer adding one forbidden key would have turned every request into a 500
  for the one person using the app. QA did not report this; QA removed a key
  from the allowlist, drove the endpoint, and showed it.
- **#59** — the deployed version had no unit test. Writing one found that
  `RATION_VERSION=""` produced an empty label rather than `dev`, and an empty
  label disappears in a PromQL query, taking the alert's one actionable field
  with it.
- **#58** — the criterion was wrong, not the code. It forbade any change under
  `backend/`, but #57 had delivered JSON on stdout and nothing that ships it, so
  Loki would stay empty and #58's own goal was unreachable. The PM amended the
  criterion in the open, bounded it to two named files, and added a criterion
  requiring a test for the filtering on that new path. The underlying defect was
  in #57's criteria, which never said the logs leave the process.

**Four bugs were found by running things rather than by reading them**, and all
four are invisible in a diff:

| | |
|---|---|
| The release flag was never wired | `Settings` had the field, the container said `true`, `settings()` returned `False` — an earlier edit had moved the line the patch anchored to. Nothing failed; the staged incident simply did not happen |
| The seed undoes the staging | the app's start command runs `ration-seed`, which is idempotent and restores the catalog, so writing the bad row before the restart looked like it worked |
| A burst of failures is invisible to `increase()` | metrics were exported once a minute, so six failures in six seconds arrived as one flat sample; the alert stayed silent while the metric sat there with the right number on it |
| The rule tests passed at the wrong resolution | `increase()` extrapolates, so at one-minute resolution three real errors evaluate to 2.5 and a rule written `>= 3` does not fire on the third failure |

The third and fourth are the same mistake from two directions, and together
they are the lesson of this milestone: **a monitoring system can be wrong in a
way that looks like nothing happening.** A broken feature shows you an error. A
broken alert shows you silence, which is indistinguishable from health.

**What the telemetry did not show.** The alert cleared four minutes after it
fired, while the fault was still in place, because nobody was making requests
(§2.5). The agent also could not tell whether `prep-plan` was broken by the same
row, because that route has no metric series — HLD §7 instruments one path, and
the cost of that choice is that a shared-catalog failure is only visible on the
route that happens to be watched.

**What went right and therefore was not exercised.** The responder reached a
correct diagnosis on its first run, so this report cannot tell you what it does
with ambiguous evidence. ASK-1 (missing or contradictory evidence) and
`inconclusive` are written down and untested. Nor was a real rollback exercised:
the agent correctly determined there was no release boundary, so the branch of
the runbook that matters most in a real incident is the branch this run did not
take.

## 7. What is still convention rather than enforcement

| | |
|---|---|
| Telemetry privacy is asserted at the emitter, not against what reaches the stores | [#68](https://github.com/staskut/ration/issues/68) |
| No collector-side redaction, sampling or retention policy | [#67](https://github.com/staskut/ration/issues/67) |
| Nothing ships telemetry off a Fly machine; staging and production are blind | [#62](https://github.com/staskut/ration/issues/62) |
| Nothing in CI checks that the stack still receives all three signals — a renamed span would pass | [#64](https://github.com/staskut/ration/issues/64) |
| `package_unit` is only constrained at the API boundary; the column and the seed loader accept anything | [#70](https://github.com/staskut/ration/issues/70) |
| The responder is started by a person; the alert does not invoke it | [#71](https://github.com/staskut/ration/issues/71) |
| The alert payload is recorded, not delivered to a human channel | [#73](https://github.com/staskut/ration/issues/73) |
| No availability or latency alert; the no-data case is deliberately foreclosed | [#72](https://github.com/staskut/ration/issues/72) |
| No CI check that every document is in both indexes — four had already drifted before M5 | [#65](https://github.com/staskut/ration/issues/65) |
| M5's own issues have not been audited against their criteria the way the MVP's were | [#69](https://github.com/staskut/ration/issues/69) |

## Documents M5 added

| | |
|---|---|
| `docs/operations-and-security-report.md` | this report |
| `docs/on-call-autonomy.md` | what the on-call agent may and may not do unattended, by clause |
| `docs/runbooks/README.md` | the runbook index, and the two conventions both follow |
| `docs/runbooks/shopping-list-5xx.md` | responding to server errors on the shopping list |
| `docs/runbooks/staging-the-incident.md` | staging the unrecognised-unit failure, and putting it back |
| `observability/README.md` | the stack, the walkthrough, the dashboard and the alert |
| `.claude/agents/on-call-responder.md` | the responder's task definition |
| `observability/incident/` | the artefacts of the run reconstructed above: both alert payloads, the evidence bundles, the responder's record, and the scripts |

The two generated evidence summaries inside the incident directory are
artefacts of that one run rather than documents. They are covered by the
directory row above and are deliberately not listed separately in either index,
which would turn a list of documents into a log of incidents — a judgement
call, and the only path produced by M5 that is not named in both indexes in its
own right.
