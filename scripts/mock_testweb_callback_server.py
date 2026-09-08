"""Minimal TestWeb callback receiver that records review-safe JSONL evidence."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("", encoding="utf-8")
    lock = Lock()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            status = 200 if self.path == "/health" else 404
            self.send_response(status)
            self.end_headers()

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(length)
            try:
                body = json.loads(raw_body or b"{}")
            except json.JSONDecodeError:
                body = raw_body.decode("utf-8", errors="replace")
            headers = dict(self.headers.items())
            if "Authorization" in headers:
                headers["Authorization"] = "Bearer ***"
            record = {
                "received_at": datetime.now(UTC).isoformat(),
                "method": "POST",
                "path": self.path,
                "headers": headers,
                "body": body,
                "response": {"status": 204, "body": None},
            }
            with lock, args.output.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            self.send_response(204)
            self.end_headers()

        def log_message(self, _format: str, *args: object) -> None:
            del args

    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
