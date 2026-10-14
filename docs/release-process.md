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
  https://ration.fly.dev
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

```bash
fly tokens create deploy --name github-actions --expiry 8760h
gh secret set FLY_API_TOKEN
```

Scope it to deploy, not to the whole account. If it leaks, `fly tokens revoke`
and set a new one; nothing else needs to change.

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
fly releases --app ration
fly deploy --app ration --image <image-ref>
scripts/smoke-test.sh https://ration.fly.dev
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

The workflow exists and its gate is live. Deploy steps are skipped with a
visible warning until `FLY_API_TOKEN` is set, so a push to `main` does not
report a false green or a false red. See #50.
