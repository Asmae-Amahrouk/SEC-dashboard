#!/usr/bin/env python3
"""All-in-one runner for Docker: serve the dashboard and refresh news on a timer.

    python scraper/serve.py                 # http://0.0.0.0:8080, refresh every 3h

Environment variables (all optional):
    PORT            HTTP port (default 8080)
    HOST            bind address (default 0.0.0.0)
    REFRESH_HOURS   hours between feed refreshes (default 3, 0 = never)
    WINDOW_DAYS     days of stories to keep (default 30)
    FETCH_ON_START  "0" to skip the fetch at startup (default "1")
    WEEKLY_IDEAS    "0" to turn off the weekly blog ideas (default "1")
    SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, EMAIL_TO, EMAIL_FROM,
    DASHBOARD_URL   optional: email the weekly ideas (see weekly_ideas.py)
"""
from __future__ import annotations

import functools
import os
import signal
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fetch_news  # noqa: E402
import weekly_ideas  # noqa: E402

DOCS = fetch_news.ROOT / "docs"


class DashboardHandler(SimpleHTTPRequestHandler):
    server_version = "SECPulse"
    sys_version = ""

    def list_directory(self, path):  # no directory listings
        self.send_error(404)
        return None

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'",
        )
        if self.path.startswith("/data/"):
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def do_GET(self):
        if self.path in ("/healthz", "/healthz/"):
            body = b"ok\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def log_message(self, fmt, *args):
        if os.environ.get("ACCESS_LOG", "0") == "1":
            super().log_message(fmt, *args)


def refresh_loop(stop: threading.Event, hours: float, days: int, run_now: bool) -> None:
    first = True
    while not stop.is_set():
        if run_now or not first:
            fetch_news.log(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Refreshing feeds…")
            try:
                fetch_news.main(["--days", str(days)])
            except Exception as exc:  # keep serving even if a refresh crashes
                fetch_news.log(f"Refresh failed: {exc!r}")
            if os.environ.get("WEEKLY_IDEAS", "1") != "0":
                try:
                    # Generates once per ISO week (kept stable after that) and emails once if SMTP is set.
                    weekly_ideas.run(email=bool(os.environ.get("SMTP_HOST")))
                except Exception as exc:
                    fetch_news.log(f"Weekly ideas failed: {exc!r}")
        first = False
        if hours <= 0:
            return
        stop.wait(hours * 3600)


def main() -> int:
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8080"))
    hours = float(os.environ.get("REFRESH_HOURS", "3"))
    days = int(os.environ.get("WINDOW_DAYS", "30"))
    run_now = os.environ.get("FETCH_ON_START", "1") != "0"

    (DOCS / "data").mkdir(parents=True, exist_ok=True)
    stop = threading.Event()
    threading.Thread(target=refresh_loop, args=(stop, hours, days, run_now), daemon=True).start()

    handler = functools.partial(DashboardHandler, directory=str(DOCS))
    httpd = ThreadingHTTPServer((host, port), handler)

    def shutdown(*_):
        stop.set()
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    fetch_news.log(f"SEC Pulse on http://{host}:{port}  (refresh every {hours:g}h, keep {days} days)")
    httpd.serve_forever()
    httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
