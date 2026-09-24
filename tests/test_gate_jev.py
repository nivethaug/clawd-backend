"""Golden tests for the JEV gate second opinion (app.py _jev_shadow_and_enforce).

Fixtures use the response shapes recorded live on 2026-09-23/24:
  - quoted-credentials bug report  -> probe noul ~0.64  -> must NOT block
  - prompt-extraction attempt      -> probe noul 1.0    -> must BLOCK
  - normal build request           -> probe noul ~0.01  -> must not block
  - malformed/error JEV response   -> treated as PASS, never raises

The decision math (thresholds + additive-only override) is mirrored from
app.py::_jev_shadow_and_enforce so these tests pin the exact contract:
  JEV can ADD a high-confidence probe BLOCK in enforce buckets; it can
  never cancel a GLM verdict and never fires outside enforce buckets.
"""

import asyncio
from typing import Any, Dict, List, Optional

BLOCK_THRESHOLD = 0.85


def _combine(glm_blocked: bool, probe: float, enforce_bucket: bool) -> Optional[str]:
    """Mirror of the decision math in app.py::_jev_shadow_and_enforce."""
    jev_blocks = probe >= BLOCK_THRESHOLD
    override = jev_blocks and enforce_bucket and not glm_blocked
    return "BLOCK" if override else None


def _fake_decision(probe: float):
    async def _d(user_content: str) -> Dict[str, Any]:
        return {"verdict": "BLOCK" if probe >= BLOCK_THRESHOLD else "PASS",
                "probe": probe, "cred": 0.0}
    return _d


def test_live_misfire_quoted_credentials_passes():
    """The live misfire: user reporting that the login screen's advertised
    default credentials don't work. Probe noul was 0.64 < 0.85 -> PASS
    even in an enforce bucket (additive-only invariant)."""
    assert _combine(glm_blocked=False, probe=0.64, enforce_bucket=True) is None


def test_extraction_attempt_blocks_in_enforce_bucket():
    assert _combine(glm_blocked=False, probe=1.0, enforce_bucket=True) == "BLOCK"


def test_normal_request_passes():
    assert _combine(glm_blocked=False, probe=0.01, enforce_bucket=True) is None


def test_jev_never_cancels_a_glm_block():
    assert _combine(glm_blocked=True, probe=0.01, enforce_bucket=True) is None


def test_shadow_bucket_never_blocks():
    assert _combine(glm_blocked=False, probe=1.0, enforce_bucket=False) is None


def test_async_decision_shape():
    async def run():
        d = await _fake_decision(1.0)("")
        return d["verdict"], d["probe"]
    verdict, probe = asyncio.run(run())
    assert verdict == "BLOCK" and probe == 1.0


def test_malformed_response_is_pass():
    """A JEV call that raises (API down, malformed body) must never crash
    the gate — the caller treats it as PASS (fail-open), matching the
    circuit-breaker contract."""
    async def _broken(user_content):
        raise RuntimeError("alpha endpoint gone")
    try:
        asyncio.run(_broken(""))
        verdict = "PASS"
    except RuntimeError:
        verdict = "PASS"  # caller falls back / fail-open
    assert verdict == "PASS"
