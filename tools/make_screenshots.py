#!/usr/bin/env python3
"""Render README screenshots of the card with headless Chrome, from dev/preview.html (real card, recorded program).

Usage: python3 tools/make_screenshots.py      (needs google-chrome; starts its own local web server)
Writes docs/images/*.png. Each shot uses a fresh temporary Chrome profile, so nothing remembered by the card
(view, watchlist filter) leaks between shots or into your own browser profile.
"""

import functools
import http.server
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "images"
WIDTH = 460

# name: (query string, card height)
SHOTS = {
    "card-films-light": ("lang=en-GB&people=2&day=1", 760),
    "card-list-dark": ("lang=en-GB&theme=dark&view=list&day=1", 760),
    "card-watchlist-compact-dark": ("lang=en-GB&theme=dark&people=2&day=1&seen=compact&film=Almanya", 560),
}


def chrome() -> str:
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        if path := shutil.which(name):
            return path
    sys.exit("Chrome/Chromium not found")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args) -> None:
            pass

    handler = functools.partial(Quiet, directory=str(ROOT))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    try:
        for name, (query, height) in SHOTS.items():
            url = f"http://127.0.0.1:{port}/dev/preview.html?clean=1&width={WIDTH}&height={height}&{query}"
            with tempfile.TemporaryDirectory() as profile:
                subprocess.run(
                    [chrome(), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
                     f"--user-data-dir={profile}", "--force-device-scale-factor=2",
                     f"--window-size={WIDTH + 32},{height + 32}", "--virtual-time-budget=10000",
                     f"--screenshot={OUT / f'{name}.png'}", url],
                    check=True, capture_output=True, timeout=120,
                )
            print("wrote", (OUT / f"{name}.png").relative_to(ROOT))
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
