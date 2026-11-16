# Runbooks

What to do when something is wrong, written so that a person who did not build
this can follow it at an inconvenient hour.

| | |
|---|---|
| [`shopping-list-5xx.md`](shopping-list-5xx.md) | the one alert: server errors on the shopping list |
| [`staging-the-incident.md`](staging-the-incident.md) | how to stage the unrecognised-unit failure on purpose, and put it back |

Two conventions hold in both, and they are the reason these are usable at all:

**Every step says what you will see, not only what to type.** A step whose
outcome is unstated cannot be checked, and an unchecked step is where a
response goes wrong.

**Where a step can only be done by a person, it says so and says why.** The
on-call responder agent works under
[`docs/on-call-autonomy.md`](../on-call-autonomy.md), and the boundary of what
it may do is almost exactly the boundary of what the telemetry contains: route
templates, counts, durations, status codes, span names, exception classes. Not
one thing about what anybody eats. So "find which catalog row is wrong" is
always a human step, and the runbook marks it rather than leaving the agent to
discover the refusal.

Related: [`../deployment.md`](../deployment.md) for Fly and Neon,
[`../release-process.md`](../release-process.md) for rolling a release back, and
[`../../observability/README.md`](../../observability/README.md) for the stack
these runbooks query.
