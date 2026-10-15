# Deployment

Two Fly.io apps from one image and one `fly.toml`, each with its own Neon
Postgres database.

| | Staging | Production |
|---|---|---|
| App | `ration-plan-staging` | `ration-plan` |
| URL | `https://ration-plan-staging.fly.dev` | `https://ration-plan.fly.dev` |
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
fly apps create ration-plan
fly apps create ration-plan-staging
```

`fly launch` is not used: it rewrites `fly.toml` from its own guesses about the
repository, and this one is written deliberately.

### 3. The secrets

Never in `fly.toml`, never in the repository, never in a workflow file.

```bash
# Production
fly secrets set --app ration-plan \
  RATION_DATABASE_URL="postgresql+psycopg://...neon.tech/ration?sslmode=require" \
  RATION_SESSION_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"

# Staging
fly secrets set --app ration-plan-staging \
  RATION_ENV=staging \
  RATION_DATABASE_URL="postgresql+psycopg://...neon.tech/ration_staging?sslmode=require" \
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
fly deploy --app ration-plan-staging
fly deploy --app ration-plan
```

## What a deploy does

1. Builds the image from `Dockerfile` — frontend build, backend venv, then a
   slim runtime with neither toolchain. Non-root, uid 10001.
2. Runs `alembic upgrade head` as the **release command**: once, before any new
   machine takes traffic. A migration in the start command races itself as soon
   as there is more than one machine.
3. Boots the new machine **alongside** the old one, waits for `GET /health`
   to pass, then moves traffic and destroys the old machine.

A release that fails migration never starts. A machine that fails its health
check never receives traffic, and the previous version keeps serving. **A
broken deploy leaves the site up.**

That last sentence is why the strategy is `bluegreen` rather than `rolling`.
With one machine, rolling updates it *in place* — so a release that fails its
check has already replaced the one that worked, and the guarantee is the
opposite of the one claimed. The distinction only appears at a single
machine, which is exactly the size this app runs at.

Production is never seeded. It starts empty and the planner creates the real
plan through the UI.

## Rolling back

Fly keeps every released image.

```bash
fly releases --app ration-plan              # find the last good version
fly deploy --app ration-plan --image <image-ref-from-that-release>
```

Verify, always against the real URL rather than the dashboard:

```bash
scripts/smoke-test.sh https://ration-plan.fly.dev
```

### Rolling back a migration

This is the part a rollback usually forgets. Redeploying the old image does
**not** undo a migration — the schema stays where the failed release left it.
An old image against a new schema is only safe when the migration was additive.

If it was not, downgrade first, then deploy:

```bash
fly ssh console --app ration-plan -C "alembic downgrade -1"
fly deploy --app ration-plan --image <previous>
```

Every migration in this repository has a tested `downgrade`; CI runs the full
up-and-down cycle. That is what makes this paragraph more than a hope.

## Cost

Checked against Fly's and Neon's published prices on 2026-10-14, not from
memory. **There is no Fly free allowance** — new organisations are
pay-as-you-go, with no monthly platform fee.

| | |
|---|---|
| Fly `shared-cpu-1x` / 512 MB, **always on** | $3.69/mo per machine (cheapest regions) |
| The same machine **suspended** | $0.15/GB/mo of rootfs — pennies |
| Outbound data | $0.02/GB in NA and Europe; inbound free |
| Neon Free | $0 — 100 CU-hr and 1 GB per project, 10 branches |

Two users, two apps, with machines suspending when idle: **about $0.50/month**
— roughly $0.35 production compute at ~60 machine-hours, $0.03 staging, and
$0.08 rootfs. The same two apps left always-on: **about $8.50/month**, which
is the entire difference and all of it avoidable.

Compute dominates storage about 4:1, so the figure scales with **hours
running**, not with anything in this file. The machine costs ~$0.006/hour;
even continuously it is $4.25. Fly bills a stopped machine by its *image*
size, not a fixed disk, and this image is ~250 MB.

`auto_stop_machines = "suspend"` idles a machine that has had no requests, and
`min_machines_running = 0` lets it actually do so. Resume is about a second.
If you want production warm, scale that one app — do not set
`min_machines_running` in this file, because both apps read it:

```bash
fly scale count 1 --app ration-plan     # ~$3.69/mo more, staging unaffected
```

Stockholm (`arn`) is not one of the cheapest regions; Fly's own figures put
Frankfurt about 15% above Ashburn, so expect a similar premium. Moving
`primary_region` to `iad` would shave a few cents and add latency.

**Neon Free is genuinely sufficient**, not a trial: storage here is kilobytes
against a 1 GB allowance, and compute scales to zero after 5 minutes idle, so
two people checking a meal plan will not approach 100 CU-hours. Staging is a
branch of the same project, also free.

## What is deliberately not here

- **Canary or progressive delivery.** Two users. The rollout strategy is
  "roll forward or roll back".
- **Auto-rollback.** A machine failing its health check already fails the
  deploy. Deciding to revert a release that is *up but wrong* needs a person.
- **Observability.** `fly logs` is the whole story so far.

## Status

**Deployed**, 2026-10-15.

| | |
|---|---|
| Production | <https://ration-plan.fly.dev> — empty, never seeded |
| Staging | <https://ration-plan-staging.fly.dev> — carries the reference plan |

`ration` was taken globally on Fly by someone else, hence `ration-plan`.

Both run one `shared-cpu-1x` 512 MB machine. Fly creates two per app by
default for high availability; both were scaled to one, since two users do
not need it and it doubles compute. Rerun `fly scale count 1` if a future
deploy reintroduces the second.
