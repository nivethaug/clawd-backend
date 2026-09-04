"""
Live-preview screenshot capture for the design layer (Path B).

Runs headless chromium against the project's live URL and returns a PNG
as base64 — no browser-frame post-processing (unlike the gallery
thumbnail pipeline) because the output is composited with the user's
sketch overlay by the frontend.
"""

from __future__ import annotations

import base64
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

MAX_CAPTURE_SECONDS = 30


def capture_preview_png(url: str, width: int = 1280, height: int = 800) -> Optional[bytes]:
    """Capture `url` at the given viewport. Returns PNG bytes or None."""
    width = max(320, min(int(width), 1920))
    height = max(480, min(int(height), 2400))

    with tempfile.TemporaryDirectory(prefix="da-shot-") as tmp:
        out = Path(tmp) / "shot.png"
        cmd = [
            os.getenv("CHROMIUM_PATH", "/usr/bin/chromium"),
            "--headless=new",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--hide-scrollbars",
            f"--window-size={width},{height}",
            f"--screenshot={out}",
            "--virtual-time-budget=5000",
            url,
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=MAX_CAPTURE_SECONDS)
            if res.returncode != 0:
                logger.warning("[DESIGN-SHOT] chromium rc=%s: %s", res.returncode, (res.stderr or "")[:200])
            if not out.is_file() or out.stat().st_size == 0:
                return None
            return out.read_bytes()
        except subprocess.TimeoutExpired:
            logger.error("[DESIGN-SHOT] chromium timeout for %s", url)
            return None
        except Exception as exc:
            logger.error("[DESIGN-SHOT] capture error: %s", exc)
            return None


def capture_preview_data_url(url: str, width: int = 1280, height: int = 800) -> Optional[str]:
    png = capture_preview_png(url, width, height)
    if not png:
        return None
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")
