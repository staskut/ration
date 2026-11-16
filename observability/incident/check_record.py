#!/usr/bin/env python3
"""Check an incident record against the autonomy policy.

    python3 observability/incident/check_record.py observability/incident/records/<id>.json

"The agent stayed within its autonomy policy" is established by running this,
not by reading the record's prose. Every action the agent says it **took** must
cite a clause that `docs/on-call-autonomy.md` permits; an action that cites
nothing, cites a clause that does not exist, or cites a forbidden one is a
violation and exits non-zero.

The clause identifiers are parsed out of the policy document itself, so a
clause renamed there and not in a record fails here rather than passing
silently. The policy is the source of truth; this file holds no copy of it.

Standard library only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

POLICY = Path("docs/on-call-autonomy.md")

#: Clause ids as the policy's tables write them: | **A1** | … | and | **F3** | …
_CLAUSE = re.compile(r"\|\s*\*\*(A\d+|F\d+)\*\*\s*\|")
#: ASK outcomes are written as **ASK-1** in prose rather than in a table.
_ASK = re.compile(r"\*\*(ASK-\d+)\*\*")

OUTCOMES = {"diagnosed", "ask", "inconclusive"}


def policy_clauses(path: Path) -> tuple[set[str], set[str], set[str]]:
    """(permitted, forbidden, ask) identifiers, read from the policy."""
    if not path.exists():
        raise SystemExit(f"no autonomy policy at {path}")
    text = path.read_text()
    ids = set(_CLAUSE.findall(text))
    return (
        {i for i in ids if i.startswith("A")},
        {i for i in ids if i.startswith("F")},
        set(_ASK.findall(text)),
    )


def check(record: dict[str, Any], permitted: set[str], forbidden: set[str], ask: set[str]):
    """Return a list of violations. Empty means the record is within policy."""
    problems: list[str] = []

    for field in ("incident_id", "outcome", "taken", "recommended"):
        if field not in record:
            problems.append(f"the record has no {field!r} field")
    if problems:
        return problems

    outcome = record["outcome"]
    if outcome not in OUTCOMES:
        problems.append(f"outcome {outcome!r} is not one of {sorted(OUTCOMES)}")
    if outcome == "ask":
        if not record.get("asking"):
            problems.append("outcome is 'ask' but the record asks nothing")
        reason = record.get("ask_clause")
        if reason not in ask:
            problems.append(
                f"outcome is 'ask' but ask_clause {reason!r} is not one of {sorted(ask)}"
            )

    for index, entry in enumerate(record["taken"]):
        where = f"taken[{index}]"
        action = entry.get("action", "")
        clause = entry.get("clause")
        if not action:
            problems.append(f"{where} has no action")
        if not entry.get("at"):
            problems.append(f"{where} ({action}) has no timestamp")
        if not entry.get("evidence"):
            problems.append(f"{where} ({action}) cites no evidence")
        if clause is None:
            problems.append(f"{where} ({action}) cites no autonomy clause")
        elif clause in forbidden:
            problems.append(
                f"{where} ({action}) was taken under {clause}, which the policy forbids "
                f"unattended — it belongs under 'recommended'"
            )
        elif clause not in permitted:
            problems.append(
                f"{where} ({action}) cites {clause!r}, which is not a clause in the policy"
            )

    for index, entry in enumerate(record["recommended"]):
        where = f"recommended[{index}]"
        action = entry.get("action", "")
        if not action:
            problems.append(f"{where} has no action")
        if not entry.get("approver"):
            problems.append(f"{where} ({action}) names nobody who must approve it")
        clause = entry.get("clause")
        if clause is not None and clause not in forbidden | permitted:
            problems.append(f"{where} ({action}) cites {clause!r}, which is not in the policy")

    taken_actions = {e.get("action") for e in record["taken"]}
    both = taken_actions & {e.get("action") for e in record["recommended"]}
    for action in sorted(a for a in both if a):
        problems.append(f"{action!r} is in both 'taken' and 'recommended'")

    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("record", type=Path)
    parser.add_argument("--policy", type=Path, default=POLICY)
    args = parser.parse_args()

    if not args.record.exists():
        print(f"no record at {args.record}", file=sys.stderr)
        return 2

    permitted, forbidden, ask = policy_clauses(args.policy)
    record = json.loads(args.record.read_text())
    problems = check(record, permitted, forbidden, ask)

    print(f"record:  {args.record}")
    print(f"policy:  {args.policy} ({len(permitted)} permitted, {len(forbidden)} forbidden)")
    print(f"took:    {len(record.get('taken', []))} action(s)")
    print(f"advised: {len(record.get('recommended', []))} action(s)")
    print(f"outcome: {record.get('outcome')}")

    if problems:
        print(f"\n{len(problems)} violation(s):", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    print("\nWithin the autonomy policy.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
