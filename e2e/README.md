# End-to-end tests

Two browser contexts against the compose stack, which is what makes them
different from everything else in the suite: they are the only tests that prove
a planner's change reaches a follower's **open** screen.

## Running

The stack must be reset first. These tests write to a real database, and one
of them fills the plan's last unplanned day — a second run against the same
data has nothing left to fill.

```bash
docker compose down -v && docker compose up -d --build
cd e2e && npm test
```

`npm run test:desktop` skips the mobile project when iterating.

## Conventions

- **No arbitrary sleeps.** Every wait is on a condition. A suite with sleeps in
  it is a suite people learn to rerun rather than read.
- **No absolute dates.** The seeded week spans today, so which day is "today"
  depends on when the suite runs. Tests navigate to the state they need rather
  than assuming a date.
- **Relative assertions where state persists.** The shopping test toggles and
  asserts the flip, rather than asserting "checked" — which would pass on a
  fresh database and fail on the second run, a property of the test and not of
  the application.
