#!/usr/bin/env python3
"""DoD verifier — live browser UI checks via CDP, tri-state, deploy-settle.

Uses the real headless Chrome on :9222 (same one the design editor uses).
Each check opens a tab, loads the page, and runs proper DOM queries with
full CSS selector support, visibility checks, and console error capture.

Design principles (from the cycle-2/4/5 postmortems):
  1. Live browser UI: document.querySelector, offsetParent, computed styles
  2. Deploy-settle: 6 retries × 5s = 30s window after rebuild
  3. Console errors captured via CDP Runtime.consoleAPICalled + Log.entryAdded
  4. url_200 via simple httpx (instant, no rendering)

Verdicts: pass | fail | unverified (infra errors — never fail a build).
Core kinds (url_200, console_clean) = blockers; content kinds = warnings.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Callable, Dict, Optional, Tuple

logger = logging.getLogger("services.dev_cycles.verifier")

RETRY_DELAY_S = 5
MAX_RETRIES = 6  # 6 × 5s = 30s deploy-settle window
CDP_TIMEOUT = 15  # per-CDP-command timeout
PAGE_LOAD_WAIT_MS = 3000  # extra wait after load for SPA rendering

_ALLOWLIST = (
    "fetchpriority", "strokewidth", "strokelinecap", "non-boolean attribute",
    "react devtools", "favicon", "third-party cookie", "deprecat",
)


# ── CDP browser session ─────────────────────────────────────────────────

class BrowserCheck:
    """Open a tab, load a page, run DOM queries, capture console errors."""

    def __init__(self, url: str):
        self.url = url
        self.console_errors: list = []

    def run(self, js: str) -> Tuple[Optional[Any], list]:
        """Load the page and evaluate JS. Returns (result, console_errors).

        The JS must be an expression or IIFE that returns a value.
        Console errors are collected during page load + evaluation.

        The CDP work runs in a dedicated thread with its own event loop —
        callers may themselves be inside an event loop (the engine's asyncio
        main loop), and asyncio.run() cannot nest.
        """
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            return ex.submit(asyncio.run, self._run(js)).result()

    async def _run(self, js: str) -> Tuple[Optional[Any], list]:
        from services.cdp_scraper import _open_tab, _close_tab, _CDPSession

        tab = await _open_tab()
        session = _CDPSession(tab["webSocketDebuggerUrl"])
        try:
            await session.connect()
            await session.send("Page.enable", timeout=CDP_TIMEOUT)
            await session.send("Runtime.enable", timeout=CDP_TIMEOUT)
            await session.send("Log.enable", timeout=CDP_TIMEOUT)

            # Collect console errors in a background task
            error_task = asyncio.create_task(self._collect_errors(session))

            # Navigate
            await session.send("Page.navigate", {"url": self.url}, timeout=CDP_TIMEOUT)

            # Wait for load
            try:
                await session.wait_for_event("Page.loadEventFired", timeout=CDP_TIMEOUT)
            except asyncio.TimeoutError:
                logger.warning("[VERIFY] page load timeout for %s, proceeding", self.url)

            # Extra wait for SPA render
            await asyncio.sleep(PAGE_LOAD_WAIT_MS / 1000)

            # Evaluate
            wrapped = f"(()=>{{ try {{ {js} }} catch(e) {{ return {{__error: e.message}}; }} }})()"
            result = await session.send("Runtime.evaluate", {
                "expression": wrapped,
                "returnByValue": True,
                "awaitPromise": True,
            }, timeout=CDP_TIMEOUT)

            # Stop collecting errors
            error_task.cancel()
            await asyncio.sleep(0.1)  # let the task finish

            value = result.get("result", {}).get("value")
            if isinstance(value, dict) and "__error" in value:
                raise RuntimeError(f"JS error on page: {value['__error']}")
            return value, self.console_errors

        finally:
            try:
                await session.close()
            except Exception:
                pass
            try:
                await _close_tab(tab.get("id", ""))
            except Exception:
                pass

    async def _collect_errors(self, session) -> None:
        """Drain CDP events and capture console errors."""
        try:
            while True:
                await asyncio.sleep(0.1)
                while not session._event_queue.empty():
                    try:
                        msg = session._event_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    method = msg.get("method", "")
                    params = msg.get("params") or {}
                    if method == "Runtime.consoleAPICalled" and params.get("type") == "error":
                        for arg in params.get("args") or []:
                            v = arg.get("value")
                            if isinstance(v, str) and not any(a in v.lower() for a in _ALLOWLIST):
                                self.console_errors.append(v[:200])
                            elif arg.get("description") and not any(a in arg["description"].lower() for a in _ALLOWLIST):
                                self.console_errors.append(arg["description"][:200])
                    elif method == "Log.entryAdded":
                        entry = params.get("entry", {})
                        if entry.get("level") == "error":
                            text = entry.get("text", "")
                            if text and not any(a in text.lower() for a in _ALLOWLIST):
                                self.console_errors.append(text[:200])
        except asyncio.CancelledError:
            pass


# ── public API ───────────────────────────────────────────────────────────

def verify(dod_item: Dict[str, Any], frontend_domain: str) -> Dict[str, Any]:
    """Run one DoD item with deploy-settle retries.

    Core checks (url_200, console_clean) get the full 6×5s settle window —
    a rebuild may still be propagating. Content checks (dom_exists,
    text_present) settle fast: once the page renders, a selector miss is a
    miss — 2 attempts (1 retry) cover a slow load without burning ~45s
    per stale check in every sweep.
    """
    kind = dod_item.get("kind")
    params = dod_item.get("params") or {}
    # `evidence` = technical proof (logs, repair prompts). `user_text` =
    # the same finding in plain words — the only string shown to users.
    result = {"verdict": "unverified", "evidence": "", "user_text": "", "check": dod_item}
    if not frontend_domain:
        result["evidence"] = "infra error: no site domain (project not created)"
        return result
    url = f"https://{frontend_domain}/{(params.get('path') or '/').lstrip('/')}"
    is_core = kind in ("url_200", "console_clean")
    max_retries = MAX_RETRIES if is_core else 2
    label = str(dod_item.get("description") or kind or "check").strip()
    label = label[:1].upper() + label[1:]

    for attempt in range(1, max_retries + 1):
        try:
            if kind == "url_200":
                ok, ev, plain = _check_url_200(url)
            elif kind == "console_clean":
                ok, ev, plain = _check_console(url)
            elif kind == "dom_exists":
                ok, ev, plain = _check_dom(url, params)
            elif kind == "text_present":
                ok, ev, plain = _check_text(url, params)
            else:
                result["evidence"] = f"unknown check kind: {kind}"
                return result

            if ok:
                result["verdict"] = "pass"
                result["evidence"] = ev + (f" (attempt {attempt})" if attempt > 1 else "")
                result["user_text"] = plain if is_core else f"{label} — {plain}"
                return result

            result["evidence"] = ev
            result["user_text"] = plain if is_core else f"{label} — {plain}"
            if attempt < max_retries:
                logger.info("[VERIFY] %s fail attempt %d/%d, retry in %ds: %s",
                            kind, attempt, max_retries, RETRY_DELAY_S, ev[:80])
                time.sleep(RETRY_DELAY_S)

        except Exception as exc:
            logger.warning("[VERIFY] %s attempt %d infra error: %s", kind, attempt, exc)
            result["evidence"] = f"infra error: {exc}"
            if attempt < max_retries:
                time.sleep(RETRY_DELAY_S)

    if result["evidence"] and "infra error" not in result["evidence"]:
        result["verdict"] = "fail"
    return result


def verify_all(dod: list, frontend_domain: str,
               on_progress: Optional[Callable[[int, int, Dict[str, Any]], None]] = None) -> Dict[str, Any]:
    """Run every DoD item. Returns {results[], passed, failed, unverified}.

    on_progress(i, total, item) fires before each check (1-based) so the
    caller can show "checking 3 of 7" during the sweep. It must never
    break a sweep — exceptions from it are swallowed.
    """
    results = []
    for i, item in enumerate(dod, 1):
        if on_progress:
            try:
                on_progress(i, len(dod), item)
            except Exception as exc:
                logger.debug("[VERIFY] progress callback failed: %s", exc)
        results.append(verify(item, frontend_domain))
    passed = sum(1 for r in results if r["verdict"] == "pass")
    failed = sum(1 for r in results if r["verdict"] == "fail")
    unverified = sum(1 for r in results if r["verdict"] == "unverified")
    return {"results": results, "passed": passed, "failed": failed, "unverified": unverified}


# ── check implementations (live browser DOM) ────────────────────────────

# Each check returns (ok, evidence, plain): `evidence` is the technical
# proof; `plain` is the finding in words a non-developer understands (for
# content checks it is a short reason that verify() prefixes with the
# check's description, e.g. "Contact form — not found on the page").

def _check_url_200(url: str) -> Tuple[bool, str, str]:
    import httpx
    r = httpx.get(url, timeout=20, follow_redirects=True)
    ok = r.status_code == 200
    return ok, f"GET {url} → {r.status_code}", (
        "The site loads" if ok else f"The site didn't load (error {r.status_code})")


def _check_console(url: str) -> Tuple[bool, str, str]:
    """Load the page in a real browser, capture console errors."""
    browser = BrowserCheck(url)
    _, errors = browser.run("return document.readyState")
    if not errors:
        return True, "0 console errors (live browser)", "No errors on the page"
    n = len(errors)
    return (False, f"{n} error(s): " + " | ".join(errors[:2]),
            f"The page has {n} script error{'s' if n > 1 else ''}")


def _check_dom(url: str, params: Dict[str, Any]) -> Tuple[bool, str, str]:
    """Check that a CSS selector matches a visible element in the live DOM."""
    selector = (params.get("selector") or "").strip()
    if not selector:
        return False, "no selector given", "couldn't be checked"

    # Proper CSS selector + visibility check via the browser engine
    js = (
        "const el = document.querySelector(" + _js(selector) + ");"
        " if (!el) return JSON.stringify({found: false, reason: 'selector not found'});"
        " const rect = el.getBoundingClientRect();"
        " const visible = el.offsetParent !== null || el.getClientRects().length > 0;"
        " const tag = el.tagName.toLowerCase();"
        " const cls = (el.className || '').toString().split(' ').slice(0, 3).join(' ');"
        " return JSON.stringify({"
        " found: true,"
        " visible: visible,"
        " tag: tag,"
        " cls: cls,"
        " size: Math.round(rect.width) + 'x' + Math.round(rect.height)"
        " });"
    )
    browser = BrowserCheck(url)
    raw, _ = browser.run(js)
    if raw is None:
        raise RuntimeError("no result from page")

    info = json.loads(raw) if isinstance(raw, str) else raw
    if not info.get("found"):
        return False, f"querySelector('{selector}') → not found in live DOM", "not found on the page"

    if not info.get("visible"):
        return (False, f"'{selector}' found but not visible ({info.get('tag')}, {info.get('size')})",
                "on the page but hidden")

    return (True, f"'{selector}' visible <{info.get('tag')} class='{info.get('cls')}'> {info.get('size')}",
            "on the page")


def _check_text(url: str, params: Dict[str, Any]) -> Tuple[bool, str, str]:
    """Check that specific text is visible in an element (live browser)."""
    selector = (params.get("selector") or "").strip()
    text = (params.get("text") or "").strip()
    if not text:
        return False, "no text to check", "couldn't be checked"
    shown = text if len(text) <= 60 else text[:57] + "…"

    # Title special case: check <title> directly
    if selector.lower() == "title":
        browser = BrowserCheck(url)
        raw, _ = browser.run("return document.title")
        title = (raw or "").strip()
        found = text.lower() in title.lower()
        return (found, f"'{text}' in <title>('{title[:50]}') -> {'yes' if found else 'no'}",
                f"reads “{shown}”" if found
                else f"the page title is “{title[:60]}”, expected “{shown}”")

    # If a selector is given, check that element's text; otherwise body
    if selector:
        js = (
            "const el = document.querySelector(" + _js(selector) + ");"
            " if (!el) return JSON.stringify({found: false, reason: 'selector not found'});"
            " const content = el.textContent || '';"
            " return JSON.stringify({"
            " found: content.toLowerCase().includes(" + _js(text.lower()) + "),"
            " preview: content.trim().slice(0, 80)"
            " });"
        )
    else:
        js = (
            "const content = document.body.innerText || '';"
            " return JSON.stringify({"
            " found: content.toLowerCase().includes(" + _js(text.lower()) + "),"
            " preview: content.trim().slice(0, 80)"
            " });"
        )

    browser = BrowserCheck(url)
    raw, _ = browser.run(js)
    if raw is None:
        raise RuntimeError("no result from page")

    info = json.loads(raw) if isinstance(raw, str) else raw
    where = f" in {selector}" if selector else " in body"
    if info.get("found"):
        return (True, f"'{text}'{where} → found ('{info.get('preview', '')[:50]}')",
                f"reads “{shown}”")

    if info.get("reason") == "selector not found":
        return (False, f"querySelector('{selector}') not found; can't check for '{text}'",
                "not found on the page")

    preview = " ".join((info.get("preview") or "").split())[:60]
    if selector and preview:
        plain = f"the page says “{preview}”, expected “{shown}”"
    else:
        plain = f"“{shown}” isn't on the page"
    return False, f"'{text}'{where} → not found (element has: '{preview}')", plain


def _js(s: str) -> str:
    return json.dumps(s)
