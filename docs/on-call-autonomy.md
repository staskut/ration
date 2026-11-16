# On-call autonomy policy

What the on-call responder agent may do without a human, what it may never do
without a human, and how anybody checks afterwards which it did.

This is written for Ration specifically. A general policy would be easy to agree
with and impossible to check: the list below names this stack, these routes and
this database, and it is specific enough that
[`observability/incident/check_record.py`](../observability/incident/check_record.py)
can decide whether a recorded action was allowed.

> The reason the forbidden list is short and absolute: the database holds
> dietary and health-adjacent data for one real person (HLD §8). Everything the
> agent is allowed to read — traces, metrics, logs — contains none of it, by
> construction and by test (#57). The boundary of its autonomy is almost exactly
> the boundary of what it can see.

## Permitted unattended

Each clause has a stable identifier. An action recorded as **taken** must cite
one.

| | May, unattended | |
|---|---|---|
| **A1** | Read telemetry | Query Prometheus, Tempo and Loki for any window. These hold route templates, counts, durations, status codes, span names and exception class names, and nothing else |
| **A2** | Read the alert payload | `observability/alerts/*.json`, and the rule and dashboard files in `observability/` |
| **A3** | Read the repository | Source, configuration, documents, `git log`. Public code, no secrets |
| **A4** | Write an incident record | Create or append to `observability/incident/records/*.json`. The record is the agent's output and it is append-only in spirit: an entry is not edited after it is written |
| **A5** | Open or comment on a GitHub issue | In `staskut/ration`, describing what it found. The issue references the incident id and #60 so the run is traceable |
| **A6** | Write a diagnosis or a recommendation | Into the record, into an issue comment, or into a message to whoever is on call |

## Never unattended

An action matching any of these is **recommended**, never **taken**, and names
who must approve it.

| | Never, unattended | Why |
|---|---|---|
| **F1** | Write to any database | Including the local one. The same command with a different connection string is the production one, and a responder that is in the habit of writing to databases is one typo from writing to that |
| **F2** | Read plan, profile, catalog or feedback rows | One real person's dietary record. The agent diagnoses from telemetry; identifying which catalog row is bad is a human step, and the runbook says so |
| **F3** | Deploy, roll back, or change a release | Includes `flyctl deploy`, `flyctl releases rollback`, retagging an image, and merging a pull request |
| **F4** | Restart, stop, scale or reconfigure a service | Including restarting the app container to "see if it clears" |
| **F5** | Change the alert rule, its threshold, or silence an alert | Silencing the thing that noticed is the most tempting unattended action and the worst one |
| **F6** | Change application code, configuration or secrets | A fix is a recommendation with a diff in it, not a commit |
| **F7** | Stage or revert the incident | `stage_incident.py` is run by a person. An agent that can stage a failure can cause one |
| **F8** | Send anything outside this repository and this stack | No email, no webhook, no third-party service. A diagnosis leaving the machine is a disclosure decision, and it is not the agent's to make |

## Ask a human

**ASK** is a named outcome, not what is left over when nothing else fits. The
responder ends its run in ASK — writing the record, stating what it has, and
naming what it needs — when any of these holds:

- **ASK-1** The evidence is missing or contradictory: no trace matches the
  alert's window and query, the stores are unreachable, or the metrics and the
  traces disagree about whether anything failed.
- **ASK-2** The diagnosis would require data the agent may not read (F2) —
  which is the normal ending for this failure mode, not a defeat. The telemetry
  says the raw-weight conversion stage raised and which release did it; which
  catalog row holds the bad value is behind F2.
- **ASK-3** The action that would fix it is on the forbidden list. The agent
  recommends it, names the approver, and stops.
- **ASK-4** The alert is firing for a route or a failure the runbooks do not
  cover.

An ASK is a complete outcome. A record that ends in ASK with the evidence
gathered and the next step named is a successful run.

## How this is checked

Not by trusting the record's prose. Every entry under `taken` cites a clause
identifier, and the checker:

```bash
python3 observability/incident/check_record.py observability/incident/records/<id>.json
```

reads this document for the clause identifiers, and exits non-zero when an
entry cites no clause, an unknown clause, or a forbidden one — and when an
action appears in both lists. It is shown to work on a committed example that
violates the policy on purpose:

```bash
python3 observability/incident/check_record.py \
  observability/incident/records/example-violation.json   # exits 1
```

A checker that has never failed is a checker nobody has tested.

## What this policy does not cover

It governs the responder agent. It says nothing about the engineering agents
that write this repository's code, which work under `AGENTS.md` and the PM →
Engineer → QA process in [`process.md`](process.md), and whose output is
reviewed before it merges rather than audited after it runs.

It also assumes the responder is started by a person following
[`docs/runbooks/shopping-list-5xx.md`](runbooks/shopping-list-5xx.md). Starting
it automatically from the alert webhook is
[#71](https://github.com/staskut/ration/issues/71), and that issue has to
answer a question this one does not: what an unattended ASK means at four in
the morning when there is nobody to ask.
