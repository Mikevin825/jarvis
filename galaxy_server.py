"""One server for the galaxy, the mindmap, and a combined dashboard.

The galaxy is a Vite build that expects `/state/*.json` to be served from
JARVIS's state directory — that is what its own dev-server plugin does. Serving
the build with a plain static server would leave the galaxy blind, so this
replicates the plugin in stdlib Python and needs no Node at all.

It also serves a dashboard page at `/` that puts the galaxy and the mindmap
side by side in one window, which is the point: opening both used to mean two
terminal windows.
"""

from __future__ import annotations

import json
import os
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GALAXY_DIST = ROOT / "galaxy" / "dist"
STATE_DIR = ROOT / "state"
DASHBOARD = ROOT / "desktop" / "dashboard.html"

HOST = os.environ.get("JARVIS_DESKTOP_HOST", "127.0.0.1")
PORT = int(os.environ.get("JARVIS_DESKTOP_PORT", "8790"))


class DesktopHandler(SimpleHTTPRequestHandler):
    """Serves the dashboard, the galaxy build, and JARVIS's state files."""

    def do_GET(self) -> None:  # noqa: N802 — http.server API
        path = self.path.split("?", 1)[0]

        if path == "/" or path == "/index.html":
            return self._serve_dashboard()
        if path.startswith("/state/"):
            return self._serve_state(path[len("/state/"):])
        if path.startswith("/galaxy/"):
            # Serve from the dist directory, with the galaxy build's own
            # index.html for its root.
            self.path = path[len("/galaxy"):] or "/"
            if self.path == "/":
                self.path = "/index.html"
            return super().do_GET()
        return super().do_GET()

    def _serve_dashboard(self) -> None:
        try:
            body = DASHBOARD.read_bytes()
        except OSError:
            self.send_error(404, "dashboard.html is missing")
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _serve_state(self, name: str) -> None:
        """Serve a JARVIS state file, so the galaxy can see what he is doing."""
        # Never allow a path traversal out of the state directory.
        safe = Path(name).name
        target = STATE_DIR / safe
        if not target.is_file():
            self.send_error(404, "no such state file")
            return
        try:
            body = target.read_bytes()
        except OSError:
            self.send_error(500, "could not read state file")
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:
        """Keep the console quiet — the dashboard is opened by a launcher."""
        return


def main() -> None:
    if not GALAXY_DIST.is_dir():
        raise SystemExit(
            f"No galaxy build at {GALAXY_DIST}.\n"
            "Build it with:  cd galaxy && npm run build"
        )

    handler = partial(DesktopHandler, directory=str(GALAXY_DIST))
    server = ThreadingHTTPServer((HOST, PORT), handler)
    print(f"JARVIS desktop serving http://{HOST}:{PORT}/")
    print("  /            the combined dashboard (galaxy + mindmap)")
    print(f"  /galaxy/     the galaxy on its own")
    print(f"  /state/*     JARVIS's state files")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
