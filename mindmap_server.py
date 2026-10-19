"""Combined server for JARVIS Living Mind.

Serves the mind map frontend and API, plus a WebSocket endpoint for live events.
"""

from __future__ import annotations

import asyncio
import json
import sys
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

import websockets

# Add JARVIS to path
_JARVIS_ROOT = Path.home() / "jarvis"
if str(_JARVIS_ROOT) not in sys.path:
    sys.path.insert(0, str(_JARVIS_ROOT))

from jarvis.config import load_config, load_dotenv
from jarvis.memory import MemoryStore
from jarvis.mindmap import build_mind_skeleton, get_node_detail
from jarvis.paths import MEMORY_FILE
from jarvis.tools import build_registry

MINDMAP_ROOT = Path(__file__).parent / "mindmap"

# Connected WebSocket clients
connected_clients: set = set()


class MindMapHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(MINDMAP_ROOT), **kwargs)

    def do_GET(self):
        if self.path == "/api/mind-map":
            self.handle_mind_map()
        elif self.path.startswith("/api/mind-map/node/"):
            node_id = self.path[len("/api/mind-map/node/"):]
            self.handle_node_detail(node_id)
        else:
            super().do_GET()

    def handle_mind_map(self):
        load_dotenv()
        config = load_config()
        store = MemoryStore(MEMORY_FILE)
        store.load()
        registry = build_registry(store)
        skeleton = build_mind_skeleton(memory_store=store, tool_registry=registry)
        data = json.dumps(skeleton.to_dict()).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def handle_node_detail(self, node_id: str):
        detail = get_node_detail(node_id)
        if detail is None:
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error": "not found"}')
            return
        data = json.dumps(detail).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format, *args):
        pass


async def websocket_handler(websocket):
    """Handle WebSocket connections."""
    connected_clients.add(websocket)
    try:
        # Send initial connection confirmation
        await websocket.send(json.dumps({
            "type": "connected",
            "message": "Connected to JARVIS mind map live feed"
        }))

        # Keep connection alive and listen for messages
        async for message in websocket:
            # Echo back any received messages (for testing)
            await websocket.send(json.dumps({
                "type": "echo",
                "message": message
            }))
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        connected_clients.discard(websocket)


async def broadcast_event(event_type: str, data: dict):
    """Broadcast an event to all connected clients."""
    if not connected_clients:
        return
    message = json.dumps({"type": event_type, "data": data})
    await asyncio.gather(
        *[client.send(message) for client in connected_clients],
        return_exceptions=True
    )


def start_http_server():
    """Start the HTTP server in a separate thread."""
    server = HTTPServer(("127.0.0.1", 8792), MindMapHandler)
    print("HTTP server running at http://127.0.0.1:8792")
    server.serve_forever()


async def main():
    """Start both HTTP and WebSocket servers."""
    # Start HTTP server in a thread
    import threading
    http_thread = threading.Thread(target=start_http_server, daemon=True)
    http_thread.start()

    # Start WebSocket server
    ws_server = await websockets.serve(websocket_handler, "127.0.0.1", 8793)
    print("WebSocket server running at ws://127.0.0.1:8793")

    # Keep running
    await asyncio.Future()  # Run forever


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nServer stopped")
