"""The mobile server — JARVIS as an installable web app (PWA).

Reuses the exact same brain, tool registry, memory store and session as the
terminal and desktop paths. The only new thing here is a transport: JSON over
HTTP, plus a WebSocket-free SSE-free streaming endpoint that sends plain text
chunks, so a phone browser can render the reply as it is written.

Design rules, mirroring the rest of the project:
  * One brain, many doors. No logic lives here that the terminal does not get.
  * stdlib only — http.server + json. No Flask, no FastAPI, no new dependency.
  * Bind to the LAN so the phone can reach it, but require a token, because a
    LAN is not a private place.

Run:  .venv/bin/python mobile_server.py
Then open the printed URL on your phone and "Add to Home Screen".
"""

from typing import Any, Iterator

import json
import secrets
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_JARVIS_ROOT = Path(__file__).resolve().parent
if str(_JARVIS_ROOT) not in sys.path:
    sys.path.insert(0, str(_JARVIS_ROOT))

from jarvis.brain import Chunk, ToolRun  # noqa: E402
from jarvis.cli import _build_brain  # noqa: E402
from jarvis.gate import ConfirmationRequest  # noqa: E402
from jarvis.providers import ProviderError  # noqa: E402
from jarvis.voice.stt import TranscriptionError  # noqa: E402
from jarvis.voice.tts import SpeechError  # noqa: E402
from jarvis.voice.web import synthesize_bytes, transcribe_bytes  # noqa: E402

WEB_ROOT = _JARVIS_ROOT / "mobile"
TOKEN_FILE = _JARVIS_ROOT / "state" / "mobile-token.txt"
PORT = 8794


def _load_or_create_token() -> str:
    """A shared secret, so the LAN is not an open door.

    Persisted so the phone does not have to re-pair on every server restart.
    """
    try:
        existing = TOKEN_FILE.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    except OSError:
        pass
    token = secrets.token_urlsafe(24)
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(token, encoding="utf-8")
    return token


def _lan_ip() -> str:
    """The address a phone on the same wifi should use."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("1.1.1.1", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


# -- the shared brain -------------------------------------------------------

class JarvisCore:
    """One brain, guarded by a lock so two taps cannot interleave a turn."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.pending: dict[str, ConfirmationRequest] = {}
        self.decisions: dict[str, bool] = {}

        # A gate that routes a consequential tool to the phone and waits for
        # an answer, rather than denying outright. It still fails closed: if
        # nobody answers within the window, the action does not happen.
        core = self

        class PhoneGate:
            def confirm(self, request: ConfirmationRequest):
                from jarvis.gate import Decision

                call_id = f"confirm-{int(time.time() * 1000)}"
                core.pending[call_id] = request
                deadline = time.time() + 120
                while time.time() < deadline:
                    if call_id in core.decisions:
                        approved = core.decisions.pop(call_id)
                        core.pending.pop(call_id, None)
                        reason = "" if approved else "you declined on your phone"
                        return Decision(approved, reason)
                    time.sleep(0.25)
                core.pending.pop(call_id, None)
                return Decision(
                    False,
                    "nobody answered the confirmation in time",
                )

        self.cfg, self.brain, self.store, self.session_store, self.provider = (
            _build_brain(gate=PhoneGate())
        )

    def ask(self, text: str) -> Iterator[tuple[str, Any]]:
        """Run one turn, yielding (kind, payload) tuples."""
        with self.lock:
            try:
                for event in self.brain.ask(text):
                    if isinstance(event, ToolRun):
                        yield ("tool", {
                            "name": event.name,
                            "ok": event.ok,
                            "gated": getattr(event, "gated", False),
                        })
                    elif isinstance(event, Chunk):
                        yield ("text", event.text)
            except ProviderError as exc:
                yield ("error", str(exc))
            finally:
                try:
                    self.session_store.save(self.brain.history)
                except Exception:
                    pass


CORE = JarvisCore()


# -- HTTP -------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "JarvisMobile/1.0"

    def log_message(self, format, *args):  # quiet by default
        pass

    # -- helpers -----------------------------------------------------------

    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authed(self) -> bool:
        supplied = self.headers.get("X-Jarvis-Token", "")
        return secrets.compare_digest(supplied, TOKEN)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

    def _static(self, path: str) -> None:
        """Serve the PWA shell from mobile/."""
        rel = path.lstrip("/") or "index.html"
        target = (WEB_ROOT / rel).resolve()
        if not str(target).startswith(str(WEB_ROOT.resolve())):
            self.send_error(403)
            return
        if not target.is_file():
            # Unknown paths fall back to the shell so the app always loads.
            target = WEB_ROOT / "index.html"
            if not target.is_file():
                self.send_error(404)
                return
        ctype = {
            ".html": "text/html; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".json": "application/json",
            ".webmanifest": "application/manifest+json",
            ".png": "image/png",
            ".svg": "image/svg+xml",
        }.get(target.suffix, "application/octet-stream")
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    # -- routes ------------------------------------------------------------

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/health":
            self._json({
                "ok": True,
                "name": CORE.cfg.assistant.name,
                "model": CORE.cfg.brain.model,
                "tools": len(CORE.brain.registry.names()),
            })
            return
        if path == "/api/state":
            if not self._authed():
                self._json({"error": "unauthorised"}, 401)
                return
            self._json({
                "name": CORE.cfg.assistant.name,
                "model": CORE.cfg.brain.model,
                "pending": [
                    {
                        "id": cid,
                        "tool": req.tool_name,
                        "effect": req.effect,
                        "detail": req.detail,
                    }
                    for cid, req in CORE.pending.items()
                ],
            })
            return
        if path == "/api/history":
            if not self._authed():
                self._json({"error": "unauthorised"}, 401)
                return
            msgs = [
                {"role": m.role, "content": m.content}
                for m in CORE.brain.history
                if m.content and not m.outputs and not m.calls
            ]
            self._json({"messages": msgs[-40:]})
            return
        self._static(path)

    def do_POST(self):
        path = self.path.split("?", 1)[0]

        if path == "/api/speak":
            if not self._authed():
                self._json({"error": "unauthorised"}, 401)
                return
            text = str(self._body().get("text", ""))
            try:
                audio, mime = synthesize_bytes(text)
            except SpeechError as exc:
                self._json({"error": str(exc)}, 502)
                return
            if not audio:
                self._json({"error": "nothing to say"}, 400)
                return
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(audio)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(audio)
            return

        if path == "/api/transcribe":
            if not self._authed():
                self._json({"error": "unauthorised"}, 401)
                return
            length = int(self.headers.get("Content-Length") or 0)
            if not length:
                self._json({"error": "no audio"}, 400)
                return
            if length > 25 * 1024 * 1024:
                self._json({"error": "recording too large"}, 413)
                return
            raw = self.rfile.read(length)
            # The browser tells us the container; keep the suffix so ffmpeg
            # picks the right demuxer.
            ctype = (self.headers.get("Content-Type") or "").lower()
            suffix = ".webm"
            if "mp4" in ctype or "m4a" in ctype or "aac" in ctype:
                suffix = ".m4a"
            elif "ogg" in ctype:
                suffix = ".ogg"
            elif "wav" in ctype:
                suffix = ".wav"

            try:
                text = transcribe_bytes(raw, suffix=suffix)
            except TranscriptionError as exc:
                self._json({"error": str(exc)}, 502)
                return
            self._json({"text": text})
            return

        if path == "/api/confirm":
            if not self._authed():
                self._json({"error": "unauthorised"}, 401)
                return
            body = self._body()
            call_id = str(body.get("id", ""))
            if call_id in CORE.pending:
                CORE.decisions[call_id] = bool(body.get("approved"))
                self._json({"ok": True})
            else:
                self._json({"ok": False, "error": "no such request"}, 404)
            return

        if path == "/api/reset":
            if not self._authed():
                self._json({"error": "unauthorised"}, 401)
                return
            CORE.brain.reset()
            try:
                CORE.session_store.save([])
            except Exception:
                pass
            self._json({"ok": True})
            return

        if path != "/api/ask":
            self._json({"error": "not found"}, 404)
            return

        if not self._authed():
            self._json({"error": "unauthorised"}, 401)
            return

        text = str(self._body().get("text", "")).strip()
        if not text:
            self._json({"error": "empty message"}, 400)
            return

        # Streaming NDJSON: one JSON object per line, flushed as it happens,
        # so the phone shows the reply forming rather than a spinner.
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        def emit(obj: dict) -> None:
            try:
                self.wfile.write((json.dumps(obj) + "\n").encode("utf-8"))
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass

        try:
            for kind, payload in CORE.ask(text):
                if kind == "text":
                    emit({"type": "text", "text": payload})
                elif kind == "tool":
                    emit({
                        "type": "tool",
                        "name": payload.get("name"),
                        "ok": payload.get("ok"),
                        "gated": payload.get("gated"),
                    })
                elif kind == "error":
                    emit({"type": "error", "error": payload})
        except Exception as exc:  # noqa: BLE001 - a turn must never kill the server
            emit({"type": "error", "error": f"{type(exc).__name__}: {exc}"})
        emit({"type": "done"})


TOKEN = ""


def main() -> int:
    global TOKEN
    TOKEN = _load_or_create_token()
    ip = _lan_ip()

    print(f"{CORE.cfg.assistant.name} mobile server")
    print("=" * 52)
    print(f"  on this machine : http://localhost:{PORT}/")
    print(f"  on your phone   : http://{ip}:{PORT}/")
    print(f"  pairing token   : {TOKEN}")
    print()
    print("Open the phone URL, paste the token once, then Add to Home Screen.")
    print("Ctrl-C to stop.\n")

    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
