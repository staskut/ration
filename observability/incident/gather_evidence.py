#!/usr/bin/env python3
"""Turn a firing alert into an evidence bundle.

    python3 observability/incident/gather_evidence.py observability/alerts/latest.json

Reads the payload Alertmanager delivered and asks the three telemetry stores
what they know about that window: the metric series that crossed the threshold,
the failing trace and which of its spans raised, and the log lines for that
trace. It writes a machine-readable bundle and a readable summary, and prints
where it put them.

Two rules it keeps, and both are the point of the exercise:

**It reads telemetry and nothing else.** No database connection, no DSN, no
SQL, no driver imported. The autonomy policy's clause F2 forbids the responder
the plan, profile and catalog rows; a script that could reach them would make
that clause a promise rather than a property.

**A missing signal is recorded as missing.** An unreachable store or an empty
query writes `"status": "unavailable"` with the reason, the rest of the bundle
is still written, and the exit status stays 0. A responder told "no trace was
found" can reason about that. A responder handed a plausible guess cannot.

Standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

PROMETHEUS = os.environ.get("PROMETHEUS_URL", "http://localhost:9090")
TEMPO = os.environ.get("TEMPO_URL", "http://localhost:3200")
LOKI = os.environ.get("LOKI_URL", "http://localhost:3100")
TIMEOUT = float(os.environ.get("EVIDENCE_TIMEOUT", "10"))

#: Why the bundle has no exception message, written into the bundle itself so
#: a responder reading it knows the field is empty by design rather than by
#: accident. See the note on #60 and the privacy rule in HLD §8.
MESSAGE_WITHHELD = (
    "withheld by design: the exception message names the catalog row that "
    "failed, and telemetry carries no dietary data (HLD §8, #57). Identifying "
    "the row is a human step against the database — see "
    "docs/runbooks/shopping-list-5xx.md, step 5."
)


def _get(url: str, params: dict[str, str] | None = None) -> tuple[Any, str | None]:
    """Fetch JSON. Returns (payload, error) and never raises."""
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as response:
            return json.loads(response.read()), None
    except urllib.error.HTTPError as error:
        return None, f"HTTP {error.code} from {url}"
    except urllib.error.URLError as error:
        return None, f"unreachable: {error.reason}"
    except (TimeoutError, json.JSONDecodeError) as error:
        return None, f"{type(error).__name__}: {error}"


def read_alert(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text())
    alerts = payload.get("alerts") or [{}]
    first = alerts[0]
    labels = {**payload.get("commonLabels", {}), **first.get("labels", {})}
    annotations = {**payload.get("commonAnnotations", {}), **first.get("annotations", {})}
    return {
        "source_file": str(path),
        "status": payload.get("status"),
        "alertname": labels.get("alertname"),
        "route": labels.get("route") or labels.get("http_route"),
        "version": labels.get("version") or labels.get("service_version"),
        "environment": labels.get("environment") or labels.get("deployment_environment"),
        "observed_count": annotations.get("observed_count"),
        "window": annotations.get("window"),
        "threshold": annotations.get("threshold"),
        "tempo_query": annotations.get("tempo_query"),
        "runbook": annotations.get("runbook"),
        "starts_at": first.get("startsAt"),
    }


def metrics_evidence(alert: dict[str, Any]) -> dict[str, Any]:
    """The series that crossed the threshold, and when it first did."""
    route, version = alert["route"], alert["version"]
    if not route:
        return {"status": "unavailable", "reason": "the alert names no route"}

    selector = f'http_route="{route}",http_response_status_code=~"5.."'
    if version:
        selector += f',service_version="{version}"'
    expression = f"sum(increase(http_server_request_duration_seconds_count{{{selector}}}[5m]))"

    end = datetime.now(UTC)
    start = end - timedelta(hours=1)
    data, error = _get(
        f"{PROMETHEUS}/api/v1/query_range",
        {
            "query": expression,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "step": "60s",
        },
    )
    if error:
        return {"status": "unavailable", "reason": error, "query": expression}

    series = data.get("data", {}).get("result", [])
    if not series:
        return {
            "status": "unavailable",
            "reason": "no 5xx series for this route and release in the last hour",
            "query": expression,
        }

    points = [(float(t), float(v)) for t, v in series[0]["values"]]
    failing = [(t, v) for t, v in points if v > 0]
    return {
        "status": "ok",
        "query": expression,
        "peak_5xx_in_5m": max(v for _, v in points),
        "first_failure_utc": (
            datetime.fromtimestamp(failing[0][0], UTC).isoformat() if failing else None
        ),
        "minutes_failing": len(failing),
    }


def success_evidence(alert: dict[str, Any]) -> dict[str, Any]:
    """Whether anything on this route is still succeeding.

    Distinguishes "every request fails" from "some do", which is the difference
    between a release that is broken for everyone and a bad row that only some
    plans touch.

    Two numbers, because one of them lies. `increase()` extrapolates and
    smooths over a counter reset, so after a restart it reports a fraction of a
    request and can show successes that are no longer happening — a responder
    reading this during the staged incident was told 1.1 requests had succeeded
    when none had since the restart. The raw counter is exact for the current
    process, so both are reported and the summary says which is which.
    """
    route = alert["route"]
    windowed = (
        f"sum by (http_response_status_code) (increase("
        f'http_server_request_duration_seconds_count{{http_route="{route}"}}[15m]))'
    )
    exact = (
        f"sum by (http_response_status_code) ("
        f'http_server_request_duration_seconds_count{{http_route="{route}"}})'
    )

    data, error = _get(f"{PROMETHEUS}/api/v1/query", {"query": windowed})
    if error:
        return {"status": "unavailable", "reason": error, "query": windowed}
    result = data.get("data", {}).get("result", [])

    raw, raw_error = _get(f"{PROMETHEUS}/api/v1/query", {"query": exact})
    counters = (
        {
            r["metric"].get("http_response_status_code"): int(float(r["value"][1]))
            for r in raw.get("data", {}).get("result", [])
        }
        if not raw_error
        else None
    )

    return {
        "status": "ok" if result else "unavailable",
        "query": windowed,
        "by_status_estimated_15m": {
            r["metric"].get("http_response_status_code"): round(float(r["value"][1]), 1)
            for r in result
        }
        or None,
        "by_status_counter_total": counters,
        "counter_query": exact,
        "caveat": (
            "by_status_estimated_15m is extrapolated by increase() and is smoothed "
            "across a counter reset; by_status_counter_total is exact for the "
            "current process but resets when it restarts"
        ),
        "reason": None if result else "no requests to this route in the last 15 minutes",
    }


def trace_evidence(alert: dict[str, Any]) -> dict[str, Any]:
    """The failing trace, and which pipeline stage raised."""
    query = alert.get("tempo_query")
    if not query:
        return {"status": "unavailable", "reason": "the alert carries no tempo_query"}

    found, error = _get(f"{TEMPO}/api/search", {"q": query, "limit": "5"})
    if error:
        return {"status": "unavailable", "reason": error, "query": query}

    traces = found.get("traces") or []
    if not traces:
        return {
            "status": "unavailable",
            "reason": "no trace matched the alert's query in Tempo's retention window",
            "query": query,
        }

    # Zero-padded to 32. Tempo's search API returns the id with leading zeros
    # stripped, and a 31-character id finds nothing in Loki — the bundle would
    # report "no log lines carry this trace id" on about one incident in
    # sixteen, which reads as missing telemetry rather than as a bug here.
    # Grafana is unaffected, which is why this only shows up in the script.
    trace_id = (traces[0].get("traceID") or "").rjust(32, "0")
    detail, error = _get(f"{TEMPO}/api/traces/{trace_id}")
    if error:
        return {"status": "partial", "trace_id": trace_id, "reason": error, "query": query}

    spans = []
    for batch in detail.get("batches", []):
        for scope in batch.get("scopeSpans", []):
            for span in scope.get("spans", []):
                attributes = {
                    a["key"]: next(iter(a.get("value", {}).values()), None)
                    for a in span.get("attributes", [])
                }
                spans.append(
                    {
                        "name": span.get("name"),
                        # Tempo's HTTP API renders the status as the enum's
                        # name; the protobuf uses 2. Accept both, because
                        # getting this wrong does not fail — it reports "no
                        # failing span" on a trace that plainly has one, which
                        # reads as "the evidence is incomplete" rather than as
                        # a bug in the evidence script.
                        "error": span.get("status", {}).get("code") in (2, "STATUS_CODE_ERROR"),
                        "exception_type": attributes.get("exception.type"),
                        "items_in": attributes.get("ration.items_in"),
                        "items_out": attributes.get("ration.items_out"),
                        "start_unix_nano": span.get("startTimeUnixNano"),
                    }
                )

    spans.sort(key=lambda s: int(s["start_unix_nano"] or 0))
    stages = [s for s in spans if str(s["name"]).startswith("shopping_list.")]
    # The stage, not the request span. Both end ERROR — the request span
    # inherits the failure — and the request span starts first, so taking the
    # earliest failing span reports "the request failed", which the alert
    # already said. The useful answer is which stage of HLD §4 raised.
    failing = [s for s in stages if s["error"]] or [s for s in spans if s["error"]]
    return {
        "status": "ok",
        "query": query,
        "trace_id": trace_id,
        "span_count": len(spans),
        "stages_completed": [s["name"] for s in stages if not s["error"]],
        "failing_span": failing[0]["name"] if failing else None,
        "failing_span_status": "ERROR" if failing else None,
        "exception_type": next((s["exception_type"] for s in failing if s["exception_type"]), None),
        "exception_message": MESSAGE_WITHHELD,
        "stages_seen": [s["name"] for s in stages],
    }


def log_evidence(trace_id: str | None) -> dict[str, Any]:
    """The log lines for that one request."""
    if not trace_id:
        return {"status": "unavailable", "reason": "no trace id to correlate on"}

    end = datetime.now(UTC)
    start = end - timedelta(hours=1)
    query = f'{{service_name="ration-api"}} | trace_id=`{trace_id}`'
    data, error = _get(
        f"{LOKI}/loki/api/v1/query_range",
        {
            "query": query,
            "start": str(int(start.timestamp() * 1e9)),
            "end": str(int(end.timestamp() * 1e9)),
            "limit": "20",
        },
    )
    if error:
        return {"status": "unavailable", "reason": error, "query": query}

    streams = data.get("data", {}).get("result", [])
    lines = [
        {
            "message": value[1],
            "route": stream.get("stream", {}).get("http_route"),
            "status_code": stream.get("stream", {}).get("http_response_status_code"),
            "exception_type": stream.get("stream", {}).get("exception_type"),
            "level": stream.get("stream", {}).get("severity_text"),
        }
        for stream in streams
        for value in stream.get("values", [])
    ]
    if not lines:
        return {
            "status": "unavailable",
            "reason": "no log lines carry this trace id",
            "query": query,
        }
    return {"status": "ok", "query": query, "line_count": len(lines), "lines": lines}


def summarise(bundle: dict[str, Any]) -> str:
    alert = bundle["alert"]
    metrics = bundle["metrics"]
    trace = bundle["trace"]
    logs = bundle["logs"]
    successes = bundle["traffic"]

    def state(part: dict[str, Any]) -> str:
        return "" if part.get("status") == "ok" else f"  _{part.get('reason')}_"

    lines = [
        f"# Evidence for {alert['alertname']} — {bundle['incident_id']}",
        "",
        f"Gathered {bundle['gathered_at_utc']} by `gather_evidence.py`, from telemetry only.",
        "",
        "## The alert",
        "",
        f"- Route: `{alert['route']}`",
        f"- Release: `{alert['version']}` in `{alert['environment']}`",
        f"- {alert['observed_count']} server errors in {alert['window']} "
        f"(threshold {alert['threshold']})",
        f"- Firing since: {alert['starts_at']}",
        "",
        "## Metrics",
        "",
    ]
    if metrics.get("status") == "ok":
        lines += [
            f"- First 5xx in the last hour: **{metrics['first_failure_utc']}** "
            f"(the alert itself started firing at {alert['starts_at']})",
            f"- Peak: {metrics['peak_5xx_in_5m']:.0f} 5xx in a 5-minute window",
            f"- Failing for {metrics['minutes_failing']} of the last 60 minutes",
        ]
    else:
        lines += [f"- Not available.{state(metrics)}"]
    if successes.get("status") == "ok":
        lines += [
            f"- Requests by status, counter total (exact for this process): "
            f"{successes['by_status_counter_total']}",
            f"- Requests by status, estimated over 15 minutes: "
            f"{successes['by_status_estimated_15m']} "
            f"— extrapolated, and smoothed across a restart, so trust the counter above it",
        ]
    else:
        lines += [f"- Traffic breakdown not available.{state(successes)}"]

    lines += ["", "## Trace", ""]
    if trace.get("status") == "ok":
        lines += [
            f"- Trace `{trace['trace_id']}`, {trace['span_count']} spans",
            f"- **Failing stage: `{trace['failing_span']}` ({trace['failing_span_status']})**",
            f"- Exception type: `{trace['exception_type']}`",
            f"- Stages that completed: {', '.join(trace['stages_completed']) or 'none'}",
            "",
            f"> Exception message: {trace['exception_message']}",
        ]
    else:
        lines += [f"- Not available.{state(trace)}"]

    lines += ["", "## Logs", ""]
    if logs.get("status") == "ok":
        lines += [f"- {logs['line_count']} line(s) carrying that trace id:"]
        lines += [
            f"  - `{line['message']}` — {line['level']}, status {line['status_code']}"
            for line in logs["lines"]
        ]
    else:
        lines += [f"- Not available.{state(logs)}"]

    missing = [
        name
        for name, part in (
            ("metrics", metrics),
            ("traffic", successes),
            ("trace", trace),
            ("logs", logs),
        )
        if part.get("status") != "ok"
    ]
    lines += [
        "",
        "## What is missing",
        "",
        (
            "Nothing — all four queries returned."
            if not missing
            else "These signals could not be gathered: " + ", ".join(missing) + "."
        ),
        "",
        "No ingredient, module, plan, target or feedback value appears above, and none",
        "can: every field comes from a route template, a count, a status code, a span",
        "name or an exception class (HLD §8, #57).",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("alert", type=Path, help="the alert payload Alertmanager delivered")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("observability/incident/evidence"),
        help="where to write the bundle",
    )
    args = parser.parse_args()

    if not args.alert.exists():
        print(f"no alert payload at {args.alert}", file=sys.stderr)
        return 2

    alert = read_alert(args.alert)
    now = datetime.now(UTC)
    incident_id = f"{now.strftime('%Y%m%dT%H%M%SZ')}-{alert['alertname'] or 'alert'}"

    trace = trace_evidence(alert)
    bundle = {
        "incident_id": incident_id,
        "gathered_at_utc": now.isoformat(),
        "gathered_by": "observability/incident/gather_evidence.py",
        "sources": {"prometheus": PROMETHEUS, "tempo": TEMPO, "loki": LOKI},
        "alert": alert,
        "metrics": metrics_evidence(alert),
        "traffic": success_evidence(alert),
        "trace": trace,
        "logs": log_evidence(trace.get("trace_id")),
    }

    directory = args.out / incident_id
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "bundle.json").write_text(json.dumps(bundle, indent=2, sort_keys=True))
    (directory / "summary.md").write_text(summarise(bundle))

    print(f"incident_id: {incident_id}")
    print(f"wrote: {directory}/bundle.json")
    print(f"wrote: {directory}/summary.md")
    if trace.get("status") == "ok":
        print(f"failing stage: {trace['failing_span']} ({trace['exception_type']})")
    # Always 0: a missing signal is a finding, not a failure of this script.
    return 0


if __name__ == "__main__":
    sys.exit(main())
