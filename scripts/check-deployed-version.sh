#!/usr/bin/env bash
#
# Is this environment serving a recent release?
#
# Written against the failure in #78: production served an Oct 15 build for a
# month while five deploys failed, `GET /health` answered `{"status":"ok"}`
# throughout, and nothing compared what was running to what should have been.
#
# The 5xx rule from #59 is structurally incapable of catching that — a stale
# release is not a failing release, and v4 served every request correctly.
# This asks the only question that does catch it: how old is the commit the
# deployment is actually serving?
#
# Age rather than equality, because the two environments ship differently.
# Staging deploys automatically on green `main`, so drift there is measured in
# minutes. Production deploys by hand on purpose, so "production is behind
# main" is the normal state within an hour of any merge, and alerting on it
# would be noise that teaches everyone to ignore the alert. What is never
# normal is a deployed commit that has been superseded for days.
#
# Exit codes: 0 current, 1 stale or unreachable, 2 used wrongly.
set -euo pipefail

if [ $# -lt 2 ]; then
  echo "usage: $0 <url> <max-drift-seconds> [git-dir]" >&2
  exit 2
fi

URL="${1%/}"
MAX_DRIFT="$2"
GIT_DIR="${3:-.}"

fail() { echo "$1"; exit 1; }

HEALTH=$(curl -fsS --max-time 20 "$URL/health" 2>/dev/null) \
  || fail "UNREACHABLE: $URL/health did not answer."

# `version` is the short SHA the deploy workflow baked in. An environment that
# does not report one cannot be checked, and silently passing it would
# reproduce the original failure: a green check that proves nothing.
DEPLOYED=$(printf '%s' "$HEALTH" | sed -n 's/.*"version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')
[ -n "$DEPLOYED" ] || fail "NO VERSION: $URL/health answered without one: $HEALTH"
[ "$DEPLOYED" != "dev" ] || fail "UNVERSIONED: $URL is serving an unversioned build."

git -C "$GIT_DIR" cat-file -e "${DEPLOYED}^{commit}" 2>/dev/null \
  || fail "UNKNOWN COMMIT: $URL is serving $DEPLOYED, which is not in this repository."

HEAD_SHA=$(git -C "$GIT_DIR" rev-parse --short HEAD)
if [ "$(git -C "$GIT_DIR" rev-parse "$DEPLOYED")" = "$(git -C "$GIT_DIR" rev-parse HEAD)" ]; then
  echo "CURRENT: $URL is serving $DEPLOYED, which is HEAD."
  exit 0
fi

# Is the deployed commit even on this branch? A `workflow_dispatch` deploy can
# ship any ref — which is how staging ran a review branch for most of a day
# while this was being written. "Behind" is then the wrong question: the
# environment is serving something that was never merged, so what `main` says
# is deployed and what is actually deployed have no relation. Worth saying
# plainly, because the alternative is silence while staging runs an abandoned
# branch indefinitely. A merge to `main` clears it by itself.
if ! git -C "$GIT_DIR" merge-base --is-ancestor "$DEPLOYED" HEAD; then
  fail "OFF-BRANCH: $URL is serving $DEPLOYED, which is not an ancestor of $HEAD_SHA — it was never merged."
fi

# How long has the deployed commit been superseded? Measured from the commit
# that replaced it, not from the deployed commit's own date: a branch that sat
# unmerged for a week is not a stale deployment.
DEPLOYED_TIME=$(git -C "$GIT_DIR" show -s --format=%ct "$DEPLOYED")
HEAD_TIME=$(git -C "$GIT_DIR" show -s --format=%ct HEAD)
DRIFT=$(( HEAD_TIME - DEPLOYED_TIME ))

BEHIND=$(git -C "$GIT_DIR" rev-list --count "${DEPLOYED}..HEAD" 2>/dev/null || echo "?")

# A rebase can date a commit before the one it replaced, so drift is not
# guaranteed positive even on a clean ancestry. Reporting "-46857m behind"
# would be absurd, and worse, a negative number silently passes the `-gt`
# comparison below — the check would report CURRENT no matter how far behind
# the deployment actually was.
if [ "$DRIFT" -lt 0 ]; then
  DRIFT=0
fi

if [ "$DRIFT" -gt "$MAX_DRIFT" ]; then
  fail "STALE: $URL is serving $DEPLOYED, $BEHIND commits and $(( DRIFT / 3600 ))h behind $HEAD_SHA."
fi

echo "CURRENT: $URL is serving $DEPLOYED, $BEHIND commits and $(( DRIFT / 60 ))m behind $HEAD_SHA — within the allowance."
