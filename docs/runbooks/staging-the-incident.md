# Runbook: staging and reverting the unrecognised-unit incident

A deliberate failure, so that the alert, the runbook and the responder can be
exercised against something real rather than demonstrated against a mock.

**What is staged:** an ingredient in the local catalog gets a `package_unit`
that the system does not model, and the app is restarted on a release whose
raw-weight conversion resolves units. Every request for a plan that touches
that ingredient then fails in `shopping_list.convert_yield` — the real pipeline
stage of HLD §4, raising a real exception, from the real engine.

**Why that failure and not an injected one.** `package_unit` is constrained to
`g | ml | pcs | null` in `openapi.yaml` and in the request schema, and that is
the *only* control: the column is `String(8)` with no constraint, the seed
loader passes the YAML value through unvalidated, and until this release no
engine parsed the string. A unit the system does not model can therefore sit in
the catalog, written by a migration or by somebody fixing data by hand, until a
request meets it. That is a gap this project actually has; closing it is
[#70](https://github.com/staskut/ration/issues/70).

## Before you start

The observability stack must be up, because the point is to watch it:

```bash
RATION_PORT=8010 docker compose -f observability/compose.yaml up -d
```

(`RATION_PORT` only if something already holds 8000 — see
`observability/README.md`.)

## Stage it

```bash
python3 observability/incident/stage_incident.py stage
```

It prints what it changed. In order, it:

1. refuses unless the target is a local stack — see **Refusals** below;
2. picks an ingredient the seeded reference plan actually uses and records its
   current unit in `observability/incident/.staged.json`;
3. restarts the app with `RATION_RESOLVE_PACKAGE_UNITS=true`, which is the
   release under which the conversion resolves units;
4. **then** sets the unit to `tbsp`.

Steps 3 and 4 are in that order on purpose, and getting it wrong is the one
mistake that looks like success. The app's start command runs `ration-seed`,
which is idempotent and therefore puts the catalog back exactly as the fixture
has it — so a row written before the restart is quietly undone by it. The
script prints a reassuring line, the endpoint answers 200, and the staged
incident simply does not happen. For the same reason, `stage` run again after
any restart of the app re-applies the row rather than reporting "already
staged", and it checks the release flag rather than assuming it.

Then make it fail, six times over about two minutes, to clear the alert's
threshold of three:

```bash
python3 observability/incident/stage_incident.py provoke
```

The spacing matters as much as the count. The app exports its metrics every
15 seconds and Prometheus scrapes every 15 seconds, and `increase()` measures a
*rise* across samples: six failures inside a few seconds reach Prometheus as a
single flat sample, `increase()` over it is zero, and the alert does not fire
while the metric sits there with the right number on it. That is the most
misleading shape a monitoring failure can take, and it is why the app's export
interval is 15 seconds rather than the SDK's default minute.

Within about two and a half minutes of starting:

- `GET /api/plans/{id}/shopping-list` returns **500**;
- the trace in Tempo shows `shopping_list.convert_yield` in ERROR with
  `exception.type = UnrecognisedUnitError`, and the three stages before it
  completed;
- `ShoppingListServerErrors` fires and the payload lands in
  `observability/alerts/latest.json`.

## Respond to it

That is the point of staging it. Follow
[`shopping-list-5xx.md`](shopping-list-5xx.md), or start the responder agent:

```
claude --agent on-call-responder "ShoppingListServerErrors is firing. Respond to it."
```

It works under [`docs/on-call-autonomy.md`](../on-call-autonomy.md) and leaves a
record in `observability/incident/records/`.

## Revert it

```bash
python3 observability/incident/stage_incident.py revert
```

It restores the ingredient's original unit from the state file and restarts the
app without the release flag. The endpoint answers 200 again, with the same body
it returned before staging — `stage` saves a copy of that response so `revert`
can diff against it and say so rather than asking you to trust it.

Alertmanager then sends a `resolved` payload to the sink.

## Refusals

Staging writes to a database and restarts a service. Both are refused unless
the target is unmistakably local, **in code** rather than by convention, the
way `ration-seed` refuses to run in production:

| Refused when | Because |
|---|---|
| the app's `RATION_ENV` is `production` | the same mechanism aimed at the real deployment |
| the API base URL is not `localhost` or `127.0.0.1` | a staging or production host is not a target |
| the compose project is not the local observability stack | a remote Docker context would otherwise be reached |
| the database URL names a non-local host | including a Neon DSN that happens to be in the environment |

Each exits non-zero and names the target it refused. `tests/unit/
test_incident_staging.py` asserts all four, and it is the one part of this
runbook worth reading the tests for: a staging mechanism that *could* fire at
production is worse than no staged incident at all.

## Running it twice, and reverting without staging

Both are safe and say what they did. `stage` twice is a no-op with a note that
the incident is already staged — it does not overwrite the saved original unit,
which would make `revert` restore `tbsp`. `revert` with nothing staged exits 0
and says there was nothing to do.

`status` reports which it is:

```bash
python3 observability/incident/stage_incident.py status
```
