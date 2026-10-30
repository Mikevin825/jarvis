#!/usr/bin/env python3
"""
JARVIS Desktop — Tier 4: Splash screen + server wake.

When the server is down, shows a splash screen and starts the server.
When the server is up, loads the real UI directly.
"""

import subprocess
import sys
import time
import urllib.request
import tempfile
import os

SPLASH_HTML = """
<!DOCTYPE html>
<html>
<head>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { width: 100vw; height: 100vh; background: #0a0a12; display: flex; flex-direction: column; align-items: center; justify-content: center; font-family: monospace; color: #D4AF37; }
  .orb { width: 60px; height: 60px; border-radius: 50%; background: #2DD4A8; animation: pulse 1.5s ease-in-out infinite; margin-bottom: 24px; }
  @keyframes pulse { 0%, 100% { transform: scale(1); opacity: 0.6; } 50% { transform: scale(1.2); opacity: 1; } }
  .text { font-size: 14px; }
</style>
</head>
<body>
  <div class="orb"></div>
  <div class="text">Waking JARVIS up...</div>
  <script>
    const TARGET = "http://localhost:8792/";
    async function poll() {
      try {
        const res = await fetch(TARGET, { method: "HEAD", mode: "no-cors" });
        window.location.replace(TARGET);
      } catch (e) {
        setTimeout(poll, 1000);
      }
    }
    poll();
  </script>
</body>
</html>
"""

def is_server_up(url):
    """Check if the server is responding."""
    try:
        req = urllib.request.Request(url, method='HEAD')
        urllib.request.urlopen(req, timeout=2)
        return True
    except Exception:
        return False

def main():
    # The combined dashboard is at port 8790 (galaxy_server), but mindmap needs 8792
    # We use the galaxy_server which serves the dashboard with both views
    url = "http://localhost:8790/"
    if len(sys.argv) > 1:
        url = sys.argv[1]

    chrome_cmd = [
        "google-chrome",
        "--window_size=1280,800",
        "--no-first-run",
        "--disable-session-crashed-bubble",
        "--no-default-browser-check",
    ]

    if is_server_up(url):
        # Server is up — load directly
        subprocess.Popen(chrome_cmd + [f"--app={url}"])
        return

    # Server is down — show splash and start it
    print(f"Server not responding at {url}")
    print("Starting server...")

    # Create splash file
    splash_path = os.path.join(tempfile.gettempdir(), "jarvis_splash.html")
    with open(splash_path, "w") as f:
        f.write(SPLASH_HTML)

    # Open splash in Chrome
    subprocess.Popen(chrome_cmd + [f"--app=file://{splash_path}"])

    # Start galaxy_server in the background (serves the combined dashboard)
    subprocess.Popen(
        [sys.executable, "galaxy_server.py"],
        cwd="/home/kingmike/jarvis",
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Poll for server to come up
    for i in range(60):
        time.sleep(1)
        if is_server_up(url):
            print(f"Server is up after {i+1}s")
            # The splash page auto-redirects to the real URL
            break
    else:
        print("Server failed to start within 60s")
        
    # Also start mindmap_server if not running (needed for API calls)
    mindmap_url = "http://localhost:8792/api/mind-map"
    if not is_server_up(mindmap_url):
        print("Starting mindmap server...")
        subprocess.Popen(
            [sys.executable, "mindmap_server.py"],
            cwd="/home/kingmike/jarvis",
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

if __name__ == "__main__":
    main()
