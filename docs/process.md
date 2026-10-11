- Tasks are GitHub issues, one at a time
- Read the acceptance criteria before starting and before closing
- Commit regularly
- Do not write `Closes #N` in a commit message. It closes the issue on merge,
  which skips QA. Reference the issue as `#N` and let a QA PASS close it

The issues are the source of truth. `docs/tasks.md` is the planning snapshot
that produced them and is not kept up to date.

Labels

- `ready` - groomed, has checkable acceptance criteria, safe to pick up
- `needs-grooming` - a goal and a description only; groom it first

Roles

- PM - grooms a task before anyone implements it, follows docs/team/pm.md
- Engineer - implements one groomed task, follows docs/team/software-engineer.md
- QA - checks the result against the acceptance criteria, follows docs/team/qa-engineer.md

An issue is closed by a QA PASS, never by the engineer who implemented it.

Orchestrator

The main session is the orchestrator. It launches the PM, the engineer
and QA as subagents. It does not groom, implement or test itself.

Lifecycle

1. Pick the next open issue from the backlog
2. PM grooms it
3. Engineer implements it
4. QA verifies it
5. On FAIL, back to step 3 with the QA comment as input
6. On PASS, close the issue
7. Repeat until the backlog is empty

Rules

- Do not skip step 2
- The engineer does not close the issue
- QA does not fix the code, only outputs PASS or FAIL
- The orchestrator closes the issue only after QA outputs PASS
