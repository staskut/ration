# Deployment

Two Fly.io apps from one image and one `fly.toml`, each with its own Neon
Postgres database.

| | Staging | Production |
|---|---|---|
| App | `ration-staging` | `ration` |
| URL | `https://ration-staging.fly.dev` | `https://ration.fly.dev` |
| `RATION_ENV` | `staging` | `production` |
| Database | its own Neon branch | its own Neon project, **empty** |
| Reference plan | seeded | refused |

## Why one `fly.toml`

Two files drift. The instant staging has a healthcheck production does not,
staging has stopped being a rehearsal. So the file is shared and the two
differ only in their **secrets** — which is also the only axis on which they
*should* differ.

Fly secrets override `[env]`, so staging sets `RATION_ENV=staging` as a secret
even though it is not sensitive. That is deliberate: it keeps the structural
definition identical.

The environment name is load-bearing in two places:

- `cookies_require_https` is true for everything except `development`, so both
  deployed environments get `Secure` cookies.
- `is_production` is true only for `production`, so **staging can be seeded
  with the reference plan and production cannot** (#21). Staging is a demo;
  production holds one real person's dietary information.

## First-time setup

Both apps, once each. Replace the region if you are not near Stockholm.

### 1. The databases

Create the Neon project, then a separate branch for staging. Copy both
connection strings — Neon shows them once.

Use the **pooled** connection string. Fly machines suspend and resume, and a
direct connection pool across a suspend leaves sockets the database still
believes are open.

### 2. The apps

```bash
fly auth login
fly apps create ration
fly apps create ration-staging
```

`fly launch` is not used: it rewrites `fly.toml` from its own guesses about the
repository, and this one is written deliberately.

### 3. The secrets

Never in `fly.toml`, never in the repository, never in a workflow file.

```bash
# Production
fly secrets set --app ration \
  RATION_DATABASE_URL="postgresql+psycopg://...neon.tech/ration?sslmode=require" \
  RATION_SESSION_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"

# Staging
fly secrets set --app ration-staging \
  RATION_ENV=staging \
  RATION_DATABASE_URL="postgresql+psycopg://...neon.tech/ration-staging?sslmode=require" \
  RATION_SESSION_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
```

Two things about `RATION_SESSION_SECRET`:

- **Production refuses to start without it.** Not a warning — a `RuntimeError`
  at startup. A generated fallback would change on every restart and sign
  everyone out, and a committed default would be worse.
- **Rotating it signs out every session.** That is the correct behaviour if it
  leaks, and a reason not to rotate it casually.

The database URL needs the `postgresql+psycopg://` scheme. Neon hands out
`postgresql://`, which SQLAlchemy resolves to psycopg2 — not installed.

### 4. Deploy

```bash
fly deploy --app ration-staging
fly deploy --app ration
```

## What a deploy does

1. Builds the image from `Dockerfile` — frontend build, backend venv, then a
   slim runtime with neither toolchain. Non-root, uid 10001.
2. Runs `alembic upgrade head` as the **release command**: once, before any new
   machine takes traffic. A migration in the start command races itself as soon
   as there is more than one machine.
3. Starts machines one at a time, each gated on `GET /health`.

A release that fails migration never starts. A machine that fails its health
check never receives traffic, and the previous version keeps serving. **A
broken deploy leaves the site up.**

Production is never seeded. It starts empty and the planner creates the real
plan through the UI.

## Rolling back

Fly keeps every released image.

```bash
fly releases --app ration              # find the last good version
fly deploy --app ration --image <image-ref-from-that-release>
```

Verify, always against the real URL rather than the dashboard:

```bash
scripts/smoke-test.sh https://ration.fly.dev
```

### Rolling back a migration

This is the part a rollback usually forgets. Redeploying the old image does
**not** undo a migration — the schema stays where the failed release left it.
An old image against a new schema is only safe when the migration was additive.

If it was not, downgrade first, then deploy:

```bash
fly ssh console --app ration -C "alembic downgrade -1"
fly deploy --app ration --image <previous>
```

Every migration in this repository has a tested `downgrade`; CI runs the full
up-and-down cycle. That is what makes this paragraph more than a hope.

## Cost

| | |
|---|---|
| Fly `shared-cpu-1x`, 512 MB, 1 machine per app | free allowance, then ~$2/mo each |
| Neon free tier | 0.5 GB, enough by three orders of magnitude |
| Outbound bandwidth | negligible for two users |

`auto_stop_machines = "suspend"` idles a machine that has had no requests.
Resume is about a second — acceptable for two users, and the reason
`min_machines_running = 1` is set on production only if you dislike that
second.

## What is deliberately not here

- **Canary or progressive delivery.** Two users. The rollout strategy is
  "roll forward or roll back".
- **Auto-rollback.** A machine failing its health check already fails the
  deploy. Deciding to revert a release that is *up but wrong* needs a person.
- **Observability.** `fly logs` is the whole story so far.

## Status

Not yet deployed. `fly.toml`, the smoke test and this document are in place;
creating the apps and the databases needs an account, and is the one step in
this repository that costs money. See #50.
