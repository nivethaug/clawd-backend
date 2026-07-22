#!/usr/bin/env python3
"""
CDP Web Scraper — server-side Chrome DevTools Protocol scraper.

Runs on the main VPS where Chrome (headless, port 9222) is installed as a
systemd service. The /internal/scrape endpoint in app.py calls this module.

Each scrape request:
1. Opens a fresh Chrome tab via POST http://127.0.0.1:9222/json/new
2. Connects to the tab's webSocketDebuggerUrl
3. Sends Page.navigate + waits for load
4. Sends Runtime.evaluate with the user's JS extraction function
5. Closes the tab via Target.closeTarget

This is naturally concurrent-safe — each request gets its own isolated tab.
No global lock needed. The caller (bwrap sandbox / Docker container) never
needs Chrome installed — it just calls the HTTP API.

Dependencies: websockets==12.0, httpx==0.25.2 (both already in requirements.txt)
"""

import asyncio
import json
import logging
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger("services.cdp_scraper")

# Chrome DevTools endpoint — the host Chrome instance (systemd service).
# 127.0.0.1:9222 matches docs/worker_vps_setup.md Phase 6.
CDP_HTTP_URL = "http://127.0.0.1:9222"

# Max concurrent scrape tabs (Chrome memory budget). Each headless tab uses
# ~50-100MB, so 10 tabs ≈ ~1GB. Adjust via env if needed.
_MAX_CONCURRENT = int(__import__("os").getenv("CDP_SCRAPER_MAX_CONCURRENT", "10"))
_semaphore: Optional[asyncio.Semaphore] = None


def _get_semaphore() -> asyncio.Semaphore:
    """Lazy-init the concurrency semaphore (needs event loop)."""
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(_MAX_CONCURRENT)
    return _semaphore


def _is_chrome_available() -> bool:
    """Quick health check — is Chrome listening on 9222?"""
    try:
        resp = httpx.get(f"{CDP_HTTP_URL}/json/version", timeout=3)
        return resp.status_code == 200
    except Exception:
        return False


async def _open_tab() -> dict:
    """Open a new Chrome tab, return its descriptor (webSocketDebuggerUrl etc)."""
    async with httpx.AsyncClient() as client:
        resp = await client.put(f"{CDP_HTTP_URL}/json/new?about:blank", timeout=10)
        if resp.status_code != 200:
            # Some Chrome versions use POST instead of PUT
            resp = await client.post(f"{CDP_HTTP_URL}/json/new?about:blank", timeout=10)
        tab = resp.json()
    if "webSocketDebuggerUrl" not in tab:
        raise RuntimeError(f"Chrome returned no webSocketDebuggerUrl: {tab}")
    return tab


async def _close_tab(target_id: str) -> None:
    """Close a Chrome tab by targetId."""
    try:
        async with httpx.AsyncClient() as client:
            await client.get(f"{CDP_HTTP_URL}/json/close/{target_id}", timeout=5)
    except Exception as e:
        logger.warning(f"Failed to close tab {target_id}: {e}")


# Minimal CDP over WebSocket — send command, wait for matching response.

class _CDPSession:
    """One-off CDP websocket session for a single tab."""

    def __init__(self, ws_url: str):
        self.ws_url = ws_url
        self._msg_id = 0
        self._ws = None
        self._event_queue: asyncio.Queue = asyncio.Queue()

    async def connect(self):
        import websockets
        self._ws = await asyncio.wait_for(
            websockets.connect(self.ws_url, max_size=50 * 1024 * 1024),
            timeout=10,
        )
        # Start background reader to drain events into the queue
        asyncio.create_task(self._reader())

    async def _reader(self):
        """Read messages from websocket, route responses vs events."""
        try:
            async for raw in self._ws:
                msg = json.loads(raw)
                if "id" in msg:
                    # Response to a command — put in queue for send() to pick up
                    await self._event_queue.put(msg)
                else:
                    # Event (Page.loadEventFired etc) — also queue
                    await self._event_queue.put(msg)
        except Exception:
            pass

    async def send(self, method: str, params: dict = None, timeout: float = 15) -> dict:
        """Send a CDP command and wait for its response."""
        self._msg_id += 1
        msg_id = self._msg_id
        await self._ws.send(json.dumps({
            "id": msg_id,
            "method": method,
            "params": params or {},
        }))

        # Wait for the response with matching id (skip events)
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                raise asyncio.TimeoutError(f"CDP timeout waiting for {method} response")
            try:
                msg = await asyncio.wait_for(self._event_queue.get(), timeout=remaining)
            except asyncio.TimeoutError:
                raise asyncio.TimeoutError(f"CDP timeout waiting for {method} response")

            if msg.get("id") == msg_id:
                if "error" in msg:
                    raise RuntimeError(f"CDP error on {method}: {msg['error']}")
                return msg.get("result", {})

    async def wait_for_event(self, event_name: str, timeout: float = 15) -> dict:
        """Wait for a specific CDP event (e.g. Page.loadEventFired)."""
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                raise asyncio.TimeoutError(f"Timeout waiting for event {event_name}")
            try:
                msg = await asyncio.wait_for(self._event_queue.get(), timeout=remaining)
            except asyncio.TimeoutError:
                raise asyncio.TimeoutError(f"Timeout waiting for event {event_name}")

            if msg.get("method") == event_name:
                return msg.get("params", {})

    async def close(self):
        if self._ws:
            await self._ws.close()


async def scrape(
    url: str,
    extract_js: str,
    wait_for_selector: Optional[str] = None,
    wait_ms: int = 2000,
    timeout: int = 15,
) -> dict:
    """Scrape a URL and extract data via JavaScript.

    Args:
        url: Target URL to scrape
        extract_js: JavaScript function body to execute on the page.
                    Must be a function body (not a full function).
                    Example: "return document.title"
                    Example: "return Array.from(document.querySelectorAll('.item')).map(e => e.textContent)"
        wait_for_selector: CSS selector to wait for before extracting (optional)
        wait_ms: Additional wait in ms after page load (for JS rendering)
        timeout: Overall timeout in seconds

    Returns:
        {"success": True, "data": <extracted_data>}
        {"success": False, "error": "..."} on failure
    """
    async with _get_semaphore():
        tab = None
        session = None
        try:
            # 1. Open a fresh tab
            tab = await _open_tab()
            ws_url = tab["webSocketDebuggerUrl"]
            target_id = tab.get("id", "")

            # 2. Connect via WebSocket
            session = _CDPSession(ws_url)
            await session.connect()

            # 3. Enable Page domain (required for navigation events)
            await session.send("Page.enable", timeout=timeout)

            # 4. Navigate to the URL
            await session.send("Page.navigate", {"url": url}, timeout=timeout)

            # 5. Wait for page load event
            try:
                await session.wait_for_event("Page.loadEventFired", timeout=timeout)
            except asyncio.TimeoutError:
                logger.warning(f"Page load timeout for {url}, proceeding anyway")

            # 6. Optional: wait for a CSS selector to appear
            if wait_for_selector:
                # Use Runtime.evaluate with a polling loop
                poll_js = f"""
                    const el = document.querySelector('{wait_for_selector}');
                    return el ? true : false;
                """
                deadline = asyncio.get_event_loop().time() + timeout
                found = False
                while asyncio.get_event_loop().time() < deadline:
                    result = await session.send("Runtime.evaluate", {
                        "expression": f"(()=>{{ try {{ {poll_js} }} catch(e) {{ return false; }} }})()",
                        "returnByValue": True,
                    }, timeout=5)
                    val = result.get("result", {}).get("value", False)
                    if val:
                        found = True
                        break
                    await asyncio.sleep(0.5)
                if not found:
                    logger.warning(f"Selector '{wait_for_selector}' not found on {url}")

            # 7. Additional wait for JS rendering
            if wait_ms > 0:
                await asyncio.sleep(wait_ms / 1000)

            # 8. Execute extraction JS
            wrapped_js = f"(()=>{{ try {{ {extract_js} }} catch(e) {{ return {{ error: e.message }}; }} }})()"
            result = await session.send("Runtime.evaluate", {
                "expression": wrapped_js,
                "returnByValue": True,
                "awaitPromise": True,
            }, timeout=timeout)

            extracted = result.get("result", {}).get("value")
            if extracted is None:
                # Value might be undefined — check for exception details
                exception_details = result.get("exceptionDetails")
                if exception_details:
                    return {"success": False, "error": f"JS error: {exception_details.get('text', 'unknown')}"}
                return {"success": True, "data": None, "type": result.get("result", {}).get("type")}

            return {"success": True, "data": extracted}

        except asyncio.TimeoutError as e:
            logger.error(f"Scrape timeout for {url}: {e}")
            return {"success": False, "error": f"timeout: {e}"}
        except Exception as e:
            logger.error(f"Scrape failed for {url}: {e}")
            return {"success": False, "error": str(e)}
        finally:
            # Always close the session and tab
            if session:
                try:
                    await session.close()
                except Exception:
                    pass
            if tab:
                try:
                    await _close_tab(tab.get("id", ""))
                except Exception:
                    pass


def scrape_sync(
    url: str,
    extract_js: str,
    wait_for_selector: Optional[str] = None,
    wait_ms: int = 2000,
    timeout: int = 15,
) -> dict:
    """Synchronous wrapper for scrape() — for use in non-async contexts."""
    try:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                scrape(url, extract_js, wait_for_selector, wait_ms, timeout)
            )
        finally:
            loop.close()
    except Exception as e:
        return {"success": False, "error": str(e)}
