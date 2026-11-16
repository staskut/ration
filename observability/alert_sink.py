#!/usr/bin/env python3
"""Catch Alertmanager's webhook and write each payload to a file.

A reviewer should see the alert that was delivered, not a green tick saying one
was. Every payload lands in `/alerts` as its own JSON file, named for the time
it arrived, and the latest is also copied to `latest.json` so a runbook and a
script can name one path.

This is where #60's on-call responder starts: it reads a payload from here.
Invoking the responder *from* this process — authentication, a loop, duplicate
suppression, an unattended "ask a human" — is #71 and deliberately not here.

Standard library only, as `AGENTS.md` requires of anything that is not a
declared dependency.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ALERTS = Path(os.environ.get("ALERT_DIR", "/alerts"))
PORT = int(os.environ.get("ALERT_SINK_PORT", "9099"))
MAX_BODY = 1 << 20


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's spelling
        length = int(self.headers.get("content-length", "0"))
        if length > MAX_BODY:
            self.send_error(413)
            return
        raw = self.rfile.read(length)

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            self.send_error(400, "not json")
            return

        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        name = payload.get("groupLabels", {}).get("alertname", "alert")
        status = payload.get("status", "unknown")
        path = ALERTS / f"{stamp}-{name}-{status}.json"
        body = json.dumps(payload, indent=2, sort_keys=True)

        ALERTS.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
        (ALERTS / "latest.json").write_text(body)

        # One line per alert on stdout, so `docker compose logs alert-sink`
        # answers "did it fire?" without opening a file.
        print(
            json.dumps(
                {
                    "message": "alert.received",
                    "status": status,
                    "alertname": name,
                    "file": str(path),
                    "alerts": len(payload.get("alerts", [])),
                }
            ),
            flush=True,
        )

        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok\n")

    def do_GET(self) -> None:  # noqa: N802
        """Liveness, and a way to read the latest payload back."""
        if self.path == "/latest":
            latest = ALERTS / "latest.json"
            body = latest.read_bytes() if latest.exists() else b"{}\n"
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok\n")

    def log_message(self, fmt: str, *args: object) -> None:
        """Quiet. The one line printed per alert above is the useful output."""


def main() -> int:
    ALERTS.mkdir(parents=True, exist_ok=True)
    print(json.dumps({"message": "alert_sink.started", "port": PORT}), flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
