# Release process

From a commit to production, and back again.

```
  push to main
       │
       ▼
  ┌─────────────────────────────────────────────┐
  │ CI    backend · frontend · postgres ·        │
  │       image · e2e · contract                 │   red ──▶ stop
  └─────────────────────────────────────────────┘
       │ green
       ▼
  ┌─────────────────────────────────────────────┐
  │ Deploy   build image                         │
  │          alembic upgrade head  (release)     │   fail ──▶ old release stays up
  │          roll machines behind /health        │
  │          scripts/smoke-test.sh               │
  └─────────────────────────────────────────────┘
       │
       ▼
  https://ration-plan-staging.fly.dev
       │
       │   manual run — Actions ▸ Deploy ▸ production
       ▼
  https://ration-plan.fly.dev
```

## The gate

`Deploy` is triggered by `workflow_run` on CI, which fires when CI
**finishes** — success *or* failure. So the job's condition is doing real
work:

```yaml
if: github.event.workflow_run.conclusion == 'success'
```

Without it this would deploy red builds, which is worse than having no
pipeline: a gate that always opens still looks like a gate.

Two details that are easy to get wrong and are deliberate here:

- **The checkout pins `workflow_run.head_sha`.** A `workflow_run` job checks
  out the default branch by default — not the commit CI tested. On a busy
  branch that deploys a tree nothing ever verified.
- **`cancel-in-progress` is off.** A cancelled deploy mid-rollout is worse
  than a queued one.

### Demonstrating that red blocks

Run once, on purpose:

1. Commit a deliberately failing test to `main`.
2. CI goes red.
3. `Deploy` appears and is **skipped** — the condition is false, so no step
   runs and nothing reaches Fly.
4. Revert.

**Exercised 2026-10-14**, on commit `2fe7163`: a unit test asserting `1 == 2`
was pushed to `main`. CI reported `failure` and the Deploy workflow reported
**`skipped`** — not `success`, and with no step executed. Reverted in
`2ec3c09`.

That distinction is the one worth checking if you ever change the condition.
A workflow that runs and exits 0 without deploying looks identical in a
green-tick list to one that deployed.

## What runs where

| Trigger | Target |
|---|---|
| Push to `main`, CI green | staging, automatically |
| **Run workflow** → `staging` | staging |
| **Run workflow** → `production` | production |

Production is never reached by merging. Green CI on `main` ships to staging
and stops there; releasing to the people using the app is a second decision,
made by a person, and the Actions log carries the name of whoever made it.

Merging a pull request is a judgement about code. Shipping is a judgement
about timing — whether staging has been looked at, whether anyone is around
if it goes wrong. Collapsing the two means the second is never actually made.

The `deploy` job declares `environment: production` for a production run, so
with required reviewers configured on that environment in repository settings
the job waits for an approval before it touches Fly. Without that setting the
choice is still manual, but nothing blocks a single person from making it —
the environment must be configured for the gate to have teeth.

## Credentials

`FLY_API_TOKEN` is a repository secret. It is never in a workflow file, never
in `fly.toml`, and never echoed — GitHub masks it in logs, which is a backstop
rather than the plan.

**One token per app**, each scoped to the app it deploys:

```bash
fly tokens create deploy --app ration-plan --name github-actions --expiry 8760h
gh secret set FLY_API_TOKEN

fly tokens create deploy --app ration-plan-staging --name github-actions-staging --expiry 8760h
gh secret set FLY_API_TOKEN_STAGING
```

An org-wide token would be one secret instead of two and would let a leak
from either environment reach the other. These cannot: the staging token is
unauthorized for production and vice versa.

That is not theoretical here — the first staging deploy through the pipeline
failed with `unauthorized`, because `fly tokens create deploy` run in this
directory scopes itself to the app in `fly.toml`. The fix was a second token,
not a broader one.

If one leaks, `fly tokens revoke` and set a new one; nothing else changes.

## The smoke test

[`scripts/smoke-test.sh`](../scripts/smoke-test.sh), as its own step so a
failure is its own red line rather than something buried in deploy output. Six
checks:

| Check | Catches |
|---|---|
| `/health` is 200 | the process is not up |
| `/` is 200 | the SPA fallback is not mounted |
| the JS bundle is 200 | a half-built image — the frontend stage did not land |
| `/api/plans` is **401** | a 500 here means the database is unreachable |
| `/api/nope` is 404 | API 404s swallowed by the SPA fallback |
| a deep link is 200 | the SPA fallback not serving client routes |

The fourth is the one worth keeping. A health endpoint that does not touch the
database reports a healthy process in front of an unreachable one; an endpoint
that must *refuse* proves the request path works end to end without needing a
session to do it.

It fails the run, loudly, with a non-zero exit and a per-check `FAIL` line.

## Is it actually out there?

The smoke test runs *inside* the deploy job, after the deploy step. When the
deploy step fails the job stops and the smoke test never runs: it validates a
release that landed, not the absence of one. That gap is how production came
to serve an Oct 15 build for a month (#78), with five failed releases behind
it and `GET /health` answering `{"status":"ok"}` the entire time.

Two checks close it from opposite sides.

**The event.** `deploy.yml` opens an issue when a deploy fails. An issue
rather than a chat message because it needs no secret and no third-party
service — and because the channel that already existed, a red workflow run,
is the one that went unread for a month.

**The condition.**
[`scripts/check-deployed-version.sh`](../scripts/check-deployed-version.sh),
run daily by `deployment-drift.yml`, compares the commit each environment
reports on `/health` against the head of `main` and fails when it has been
superseded for too long. This is the one that also catches a deploy that
never ran, that ran against the wrong app, or that someone rolled back by
hand and forgot.

It measures **age, not equality**, because the environments ship differently:

| Environment | Allowance | Why |
|---|---|---|
| staging | 2 hours | deploys automatically on green `main`; the only normal drift is a deploy in flight |
| production | 7 days | deployed by hand on purpose, so "behind `main`" is the normal state after any merge |

Alerting on mere inequality would fire on every merge and teach everyone to
ignore it, which is worse than no alert — it would look like coverage.

Run it by hand against any environment:

```bash
scripts/check-deployed-version.sh https://ration-plan.fly.dev 604800
```

It exits 0 when current, 1 when stale, unreachable, unversioned, or serving a
commit this repository does not contain.

## Rolling back

```bash
fly releases --app ration-plan
fly deploy --app ration-plan --image <image-ref>
scripts/smoke-test.sh https://ration-plan.fly.dev
```

**Check the migration before you assume you are done.** Redeploying the old
image does not undo a schema change. If the bad release migrated
destructively, `alembic downgrade -1` first —
[`deployment.md`](deployment.md#rolling-back-a-migration) has the sequence.

Roll back first, diagnose afterwards. The commit is still there.

## Not automated, on purpose

- **Auto-rollback.** A failing health check already prevents a bad release
  from taking traffic. Reverting a release that is *up but wrong* is a
  judgement call.
- **Canary.** Two users.
- **Release notes.** The commit log is conventional-commit formatted and is
  the record.

## Status

Live, 2026-10-15. `FLY_API_TOKEN` is set as a repository secret, scoped to
deploy rather than to the account.

### Rollback, exercised

On staging, 2026-10-15. `fly deploy --image` with v1's ref, which bluegreen
deployed as v3; the smoke test passed against it, and a normal deploy rolled
forward again.

One thing that exercise surfaced and a reader should know: **the release
command came from the local `fly.toml`, not from the rolled-back image.**
Config and code roll back independently. So a rollback undoes application
code and leaves `fly.toml` — release command, health check, VM size — exactly
as it is on disk. If the thing you are rolling back *is* a config change,
revert the file and deploy; `--image` alone will not do it.

That sits alongside the migration caveat above, and has the same shape: the
image is not the whole release.
