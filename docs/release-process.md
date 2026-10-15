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
| Push to `main`, CI green | production |
| **Run workflow** → `staging` | staging |
| **Run workflow** → `production` | production, bypassing the gate |

The manual production option exists for one case: redeploying a known-good
commit when CI is broken for an unrelated reason. It is a deliberate override,
visible in the Actions log with the name of whoever pressed it.

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
