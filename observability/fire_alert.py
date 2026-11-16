#!/usr/bin/env python3
"""Make the real alert rule fire, in about a minute, without breaking the app.

    python3 observability/fire_alert.py

It posts OTLP metric points for the instrumented route with status 500 straight
at the collector, raising the counter one step at a time with a real pause
between the steps. The pause is the point: Prometheus *scrapes* the collector,
so a counter that arrives already at four looks flat and `increase()` over five
minutes is zero. The rule does not fire, and the reason is invisible — the
metric is there with the right value and the alert is silent. The counter has
to climb across scrapes, which means climbing across wall-clock time.

**What this does and does not prove.** It exercises the rule, the routing and
the payload: the alert that fires is the one the stack loaded, not a copy. It
does *not* exercise the application failing, because nothing here touches the
app — there is deliberately no route in the image that can be made to return
500 on demand, since a deployable artefact with a break-glass endpoint in it is
a worse idea than a slow demo. The failure of the real pipeline is #60's staged
incident, and that is the one the report reconstructs.

Standard library only.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

ROUTE = "/api/plans/{plan_id}/shopping-list"


def _point(value: int, start_nanos: int, nanos: int, status: int) -> dict[str, object]:
    return {
        "startTimeUnixNano": str(start_nanos),
        "timeUnixNano": str(nanos),
        "count": str(value),
        "sum": value * 0.05,
        "bucketCounts": [str(value), "0"],
        "explicitBounds": [0.1],
        "attributes": [
            {"key": "http.route", "value": {"stringValue": ROUTE}},
            {"key": "http.request.method", "value": {"stringValue": "GET"}},
            {"key": "http.response.status_code", "value": {"intValue": str(status)}},
        ],
    }


def _payload(value: int, start_nanos: int, nanos: int, version: str, status: int) -> bytes:
    body = {
        "resourceMetrics": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": "ration-api"}},
                        {"key": "service.version", "value": {"stringValue": version}},
                        {
                            "key": "deployment.environment",
                            "value": {"stringValue": "development"},
                        },
                    ]
                },
                "scopeMetrics": [
                    {
                        "scope": {"name": "ration"},
                        "metrics": [
                            {
                                "name": "http.server.request.duration",
                                "unit": "s",
                                "histogram": {
                                    "aggregationTemporality": 2,
                                    "dataPoints": [
                                        _point(value, start_nanos, nanos, status)
                                    ],
                                },
                            }
                        ],
                    }
                ],
            }
        ]
    }
    return json.dumps(body).encode()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default="http://localhost:4318")
    parser.add_argument("--version", default="dev", help="the release to blame")
    parser.add_argument("--count", type=int, default=4, help="how many 5xx to report")
    parser.add_argument(
        "--status", type=int, default=500, help="status code to report, for negative tests"
    )
    parser.add_argument(
        "--step",
        type=float,
        default=20.0,
        help="seconds between steps; must exceed the scrape interval",
    )
    args = parser.parse_args()

    start = time.time_ns()
    for index in range(1, args.count + 1):
        if index > 1:
            # Longer than Prometheus's 15s scrape interval, so each step is
            # seen as its own sample rather than collapsed into the last one.
            time.sleep(args.step)
        stamp = time.time_ns()
        request = urllib.request.Request(
            f"{args.endpoint}/v1/metrics",
            data=_payload(index, start, stamp, args.version, args.status),
            headers={"content-type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                response.read()
        except urllib.error.URLError as error:
            print(f"could not reach the collector at {args.endpoint}: {error}", file=sys.stderr)
            return 1
        print(f"reported {index} × {args.status} on {ROUTE} ({args.version})", flush=True)

    print(
        "\nPrometheus scrapes every 15s and the rule evaluates every minute.\n"
        "  http://localhost:9090/alerts        the rule going pending, then firing\n"
        "  observability/alerts/latest.json    the payload Alertmanager delivered\n"
        "  docker compose -f observability/compose.yaml logs alert-sink"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
