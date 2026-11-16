#!/usr/bin/env python3
"""Stage the unrecognised-unit failure on the local stack, and put it back.

    python3 observability/incident/stage_incident.py stage
    python3 observability/incident/stage_incident.py provoke
    python3 observability/incident/stage_incident.py status
    python3 observability/incident/stage_incident.py revert

See `docs/runbooks/staging-the-incident.md`. In short: an ingredient the seeded
reference plan uses gets a `package_unit` the system does not model, and the app
is restarted on a release whose raw-weight conversion resolves units. Requests
for that plan then fail in `shopping_list.convert_yield` — a real stage of
HLD §4's pipeline, raising a real exception from the real engine.

**This writes to a database and restarts a service.** Both are refused unless
the target is unmistakably local, in code rather than by convention, the way
`ration-seed` refuses to run in production. The refusals are the most important
thing in this file: a staging mechanism that could be aimed at the real
deployment is worse than having no staged incident at all.

Standard library only. The database is reached through `docker compose exec db
psql`, so there is no driver here and no connection string to point somewhere
else by accident.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

REPO = Path(__file__).resolve().parents[2]
COMPOSE = REPO / "observability" / "compose.yaml"
STATE = REPO / "observability" / "incident" / ".staged.json"

#: Not in `g | ml | pcs`, so `Dimension(unit)` raises. Something a person might
#: plausibly type into a catalog — which is the point: this is a data mistake
#: the system does not currently prevent (#70), not an injected failure.
BAD_UNIT = "tbsp"

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]"}

PLANNER = ("planner@ration.example", "correct-horse-battery")


class Refused(SystemExit):
    """The target is not a local stack. Exits non-zero, naming the target."""

    def __init__(self, reason: str, target: str) -> None:
        super().__init__(f"refused: {reason}\n  target: {target}")


# ----------------------------------------------------------------- refusals


def check_url(base_url: str) -> None:
    """Only a local API. A staging or production host is not a target."""
    host = urlparse(base_url).hostname or ""
    if host not in LOCAL_HOSTS:
        raise Refused(f"{host!r} is not a local host", base_url)


def check_environment(environment: str | None, target: str) -> None:
    """Never production, whatever else is true."""
    if (environment or "").strip().lower() == "production":
        raise Refused("the target app is running RATION_ENV=production", target)


def check_database_url(database_url: str | None, target: str) -> None:
    """Refuse a DSN that names anything but the compose database.

    A Neon connection string in the environment is the realistic way this goes
    wrong: the variable is already exported in the shell that deploys.
    """
    if not database_url:
        return
    host = urlparse(database_url).hostname or ""
    if host not in LOCAL_HOSTS | {"db"}:
        raise Refused(f"the target database is at {host!r}, which is not local", target)


def check_compose_file(path: Path) -> None:
    """Refuse a compose file that is not this repository's local stack."""
    if path.resolve() != COMPOSE.resolve():
        raise Refused("the compose file is not observability/compose.yaml", str(path))
    if not path.exists():
        raise Refused("the compose file does not exist", str(path))


# ------------------------------------------------------------------ helpers


def compose(*arguments: str, capture: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE), *arguments],
        cwd=REPO,
        capture_output=capture,
        text=True,
        check=False,
    )


def app_environment() -> dict[str, str]:
    """RATION_* as the running app container sees it."""
    result = compose("exec", "-T", "app", "env")
    if result.returncode != 0:
        raise SystemExit(
            "could not read the app container's environment — is the stack up?\n"
            f"  {result.stderr.strip()}"
        )
    found = {}
    for line in result.stdout.splitlines():
        key, _, value = line.partition("=")
        if key.startswith("RATION_"):
            found[key] = value
    return found


def psql(sql: str) -> str:
    result = compose("exec", "-T", "db", "psql", "-U", "ration", "-d", "ration", "-tAc", sql)
    if result.returncode != 0:
        raise SystemExit(f"psql failed:\n  {result.stderr.strip()}")
    return result.stdout.strip()


def guard(base_url: str) -> dict[str, str]:
    """Every refusal, in one place, before anything is changed."""
    check_compose_file(COMPOSE)
    check_url(base_url)
    environment = app_environment()
    check_environment(environment.get("RATION_ENV"), base_url)
    check_database_url(environment.get("RATION_DATABASE_URL"), base_url)
    return environment


def restart_app(*, resolve_units: bool, port: str) -> None:
    """Recreate the app container with or without the release flag."""
    env = {
        **os.environ,
        "RATION_RESOLVE_PACKAGE_UNITS": "true" if resolve_units else "false",
        "RATION_PORT": port,
    }
    result = subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE), "up", "-d", "--no-deps", "app"],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"could not restart the app:\n  {result.stderr.strip()}")


def wait_for_health(base_url: str, seconds: int = 60) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{base_url}/health", timeout=2) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
        time.sleep(2)
    raise SystemExit(f"the app did not become healthy at {base_url}")


def shopping_list(base_url: str) -> tuple[int, str]:
    """Ask for the seeded plan's shopping list, as the planner."""
    import http.cookiejar

    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    login = urllib.request.Request(
        f"{base_url}/api/auth/login",
        data=json.dumps({"email": PLANNER[0], "password": PLANNER[1]}).encode(),
        headers={"content-type": "application/json"},
    )
    try:
        opener.open(login, timeout=10).read()
        plans = json.loads(opener.open(f"{base_url}/api/plans", timeout=10).read())
        plan_id = plans[0]["id"]
        body = opener.open(f"{base_url}/api/plans/{plan_id}/shopping-list", timeout=20).read()
        return 200, body.decode()
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode()[:200]


# ----------------------------------------------------------------- commands


def _ensure_staged_release(args: argparse.Namespace) -> bool:
    """Put the app on the release that resolves units, if it is not already.

    Returns True if it had to restart. Checked rather than assumed, because
    `docker compose up --build app` run by hand leaves the flag off and the
    staged row then sits there doing nothing — the endpoint answers 200 and
    the incident quietly does not exist.
    """
    environment = app_environment()
    if environment.get("RATION_RESOLVE_PACKAGE_UNITS", "").strip().lower() == "true":
        return False
    print("restarting the app on the release that resolves units…")
    restart_app(resolve_units=True, port=args.port)
    wait_for_health(args.base_url)
    return True


def stage(args: argparse.Namespace) -> int:
    guard(args.base_url)

    if STATE.exists():
        # Already staged — but a restart of the app re-runs `ration-seed`,
        # which is idempotent and puts the catalog back. So check the row
        # rather than the state file, and put it back if something reset it.
        # The state file keeps the *original* unit either way: overwriting it
        # here would make `revert` restore the bad value.
        state = json.loads(STATE.read_text())
        current = psql(f"SELECT package_unit FROM ingredients WHERE slug = '{state['slug']}'")
        restarted = _ensure_staged_release(args)
        if current == BAD_UNIT and not restarted:
            print(
                f"already staged: {state['slug']} carries {BAD_UNIT!r} "
                f"(was {state['original_unit']!r}). Nothing to do."
            )
            return 0
        psql(f"UPDATE ingredients SET package_unit = '{BAD_UNIT}' WHERE slug = '{state['slug']}'")
        print(
            f"re-staged {state['slug']}.package_unit = {BAD_UNIT!r} — the app had been "
            f"restarted or was not on the staged release, and its start command re-seeds "
            f"the catalog."
        )
        status, _ = shopping_list(args.base_url)
        print(f"shopping list now answers {status}")
        return 0 if status == 500 else 1

    # An ingredient the seeded plan actually reaches, so the failure is on the
    # path the alert watches. Deterministic, so two runs stage the same row.
    slug = psql(
        "SELECT i.slug FROM ingredients i "
        "JOIN module_lines ml ON ml.ingredient_id = i.id "
        "JOIN plan_entries pe ON pe.module_id = ml.module_id "
        "WHERE i.package_unit IS NOT NULL "
        "GROUP BY i.slug ORDER BY i.slug LIMIT 1"
    )
    if not slug:
        raise SystemExit(
            "no seeded ingredient with a package unit is used by any plan — "
            "is the stack seeded with the reference plan?"
        )

    original = psql(f"SELECT package_unit FROM ingredients WHERE slug = '{slug}'")
    status, before = shopping_list(args.base_url)
    if status != 200:
        raise SystemExit(f"the shopping list is already failing ({status}); fix that first")

    # Deploy first, then write the row — not the other way round. The app's
    # start command runs `ration-seed`, which is idempotent and therefore puts
    # the catalog back exactly as the fixture has it. Staging the row before
    # the restart looks like it worked, prints a reassuring line, and leaves
    # the endpoint answering 200: the staged incident silently does not happen.
    _ensure_staged_release(args)

    psql(f"UPDATE ingredients SET package_unit = '{BAD_UNIT}' WHERE slug = '{slug}'")
    STATE.write_text(
        json.dumps(
            {
                "slug": slug,
                "original_unit": original,
                "bad_unit": BAD_UNIT,
                "staged_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "response_before": before,
            },
            indent=2,
        )
    )
    print(f"set {slug}.package_unit = {BAD_UNIT!r} (was {original!r})")

    status, _ = shopping_list(args.base_url)
    print(f"shopping list now answers {status}")
    if status != 500:
        print(
            "  expected 500 — the staged release may not be on, "
            "or the chosen ingredient is not on this plan's path",
            file=sys.stderr,
        )
        return 1
    print("\nNow run:  python3 observability/incident/stage_incident.py provoke")
    return 0


def provoke(args: argparse.Namespace) -> int:
    """Fail the endpoint enough times to cross the alert's threshold of three."""
    guard(args.base_url)
    if not STATE.exists():
        raise SystemExit("nothing is staged — run `stage` first")

    for attempt in range(1, args.times + 1):
        status, _ = shopping_list(args.base_url)
        print(f"request {attempt}: {status}")
        if attempt < args.times:
            time.sleep(args.interval)

    print(
        "\nPrometheus scrapes every 15s and the rule evaluates every minute.\n"
        "  http://localhost:9090/alerts     the rule firing\n"
        "  observability/alerts/latest.json the delivered payload\n"
        "Then: docs/runbooks/shopping-list-5xx.md"
    )
    return 0


def status(args: argparse.Namespace) -> int:
    if not STATE.exists():
        print("not staged")
        return 0
    state = json.loads(STATE.read_text())
    print(f"staged at {state['staged_at']}")
    print(
        f"  {state['slug']}.package_unit = {state['bad_unit']!r} (was {state['original_unit']!r})"
    )
    code, _ = shopping_list(args.base_url)
    print(f"  shopping list answers {code}")
    return 0


def revert(args: argparse.Namespace) -> int:
    guard(args.base_url)

    if not STATE.exists():
        print("nothing is staged. Nothing to do.")
        return 0

    state = json.loads(STATE.read_text())
    original = state["original_unit"]

    print("restarting the app without the staged release…")
    restart_app(resolve_units=False, port=args.port)
    wait_for_health(args.base_url)

    # After the restart, for the same reason staging happens after it: the
    # restart re-seeds, and a row restored before it would be restored twice
    # and proved once.
    psql(f"UPDATE ingredients SET package_unit = '{original}' WHERE slug = '{state['slug']}'")
    print(f"restored {state['slug']}.package_unit = {original!r}")

    code, after = shopping_list(args.base_url)
    print(f"shopping list answers {code}")
    if code == 200:
        same = after == state["response_before"]
        print(
            "the response matches the one recorded before staging"
            if same
            else "WARNING: the response differs from the one recorded before staging"
        )
    STATE.unlink()
    return 0 if code == 200 else 1


def main() -> int:
    # The two options are on the top-level parser *and* on every subcommand,
    # so `stage --base-url X` works as well as `--base-url X stage`. A reviewer
    # following a runbook will type one of them, and meeting "unrecognized
    # arguments" at that point reads as a broken runbook.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--base-url", default=os.environ.get("RATION_URL", "http://localhost:8010"))
    common.add_argument("--port", default=os.environ.get("RATION_PORT", "8010"))

    parser = argparse.ArgumentParser(description=__doc__, parents=[common])
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser(
        "stage", parents=[common], help="introduce the bad unit and the staged release"
    )
    provoker = commands.add_parser(
        "provoke", parents=[common], help="fail the endpoint until the alert fires"
    )
    # Six requests, twenty seconds apart. The count has to rise across
    # several scrapes: four failures in six seconds reach Prometheus as one
    # sample, and `increase()` over one sample is zero.
    provoker.add_argument("--times", type=int, default=6)
    provoker.add_argument("--interval", type=float, default=20.0)
    commands.add_parser("status", parents=[common], help="say whether the incident is staged")
    commands.add_parser("revert", parents=[common], help="put the catalog and the release back")

    args = parser.parse_args()
    return {"stage": stage, "provoke": provoke, "status": status, "revert": revert}[args.command](
        args
    )


if __name__ == "__main__":
    sys.exit(main())
