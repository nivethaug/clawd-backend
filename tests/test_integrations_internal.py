"""
N2 fixture test — proves the SECRET_KEY → owner → Nango chain and the
prompt snippet, without touching a live Nango or a real project.

Chain under test (api/integrations_internal.py):
  1. Project's .env SECRET_KEY is compared with compare_digest
  2. Project resolves to its OWNER via the projects table
  3. Only the OWNER's nango_connections row unlocks the provider call
  4. nango_client.proxy_request receives owner's connection_id (monkeypatched
     here to record the call instead of hitting the network)
  5. Provider status+body pass through untouched

Prompt block (integration_prompt_block._oauth_block):
  6. Renders only when the owner has connections
  7. Snippet contains the proxy URL, SECRET_KEY reference, provider and
     project id; NEVER contains any token

Run: python -m pytest tests/test_integrations_internal.py -q
(or standalone: python tests/test_integrations_internal.py)
"""

import os
import sys
import types
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Local-machine fastapi/starlette version skew (fastapi 0.128 passes
# on_startup to a starlette 1.6 Router that no longer accepts it; the
# server's pinned versions are fine). Shim Router.__init__ so the module
# imports locally and the pure chain logic stays testable.
import starlette.routing as _sr

if not getattr(_sr.Router.__init__, "_n2shim", False):
    _orig_router_init = _sr.Router.__init__

    def _shim_init(self, routes=None, redirect_slashes=True, default=None,
                   lifespan=None, *, middleware=None, max_body_size=None,
                   on_startup=None, on_shutdown=None, **kw):
        _orig_router_init(self, routes, redirect_slashes, default, lifespan,
                          middleware=middleware, max_body_size=max_body_size)

    _shim_init._n2shim = True
    _sr.Router.__init__ = _shim_init


# ------------------------------------------------------------------ fakes

class FakeConn:
    """Minimal CursorAsConnection fake answering the queries our code makes."""

    def __init__(self, rows):
        self._rows = rows          # list of dicts returned per query key
        self.queries = []

    def execute(self, q, params=None):
        self.queries.append((q, params))
        q_l = " ".join(q.lower().split())

        class _Cur:
            def __init__(self, rows):
                self._rows = rows or []
            def fetchone(self):
                return self._rows[0] if self._rows else None
            def fetchall(self):
                return self._rows
            def rowcount(self):
                return len(self._rows)

        if "from projects where id" in q_l:
            return _Cur(self._rows.get("project") or [])
        if "provider_config_key = ?" in q_l:
            return _Cur(self._rows.get("nango_one") or [])
        if "from nango_connections where user_id" in q_l:
            return _Cur(self._rows.get("nango") or [])
        return _Cur([])

    def commit(self):
        pass


ROWS = {
    "project": [{"user_id": 24}],
    "nango": [{"provider_config_key": "youtube"}],
    "nango_one": [{"connection_id": "conn-abc-123"}],
}

PROJECT_ENV = {"SECRET_KEY": "proj-secret-xyz"}

calls = []


def fake_project_env_secret(project_id):
    return PROJECT_ENV.get("SECRET_KEY")


def fake_proxy(provider_config_key, connection_id, method, endpoint, **kw):
    calls.append({"provider": provider_config_key, "cid": connection_id,
                  "method": method, "endpoint": endpoint, **kw})
    return {"status": 200, "body": '{"items": [{"id": "UC123"}]}'}


# ------------------------------------------------------------------ tests

def test_chain():
    from api import integrations_internal as ii
    from services.integrations import nango_client

    with patch.object(ii, "_project_env_secret", fake_project_env_secret), \
         patch("api.integrations_internal.get_db", lambda: _fake_ctx()), \
         patch.object(ii, "get_db", lambda: _fake_ctx()), \
         patch.object(nango_client, "is_configured", lambda: True), \
         patch.object(nango_client, "proxy_request", fake_proxy):
        pass  # provider registry already has youtube from N1

        req = ii.ProxyRequest(provider="youtube", method="GET",
                              endpoint="youtube/v3/channels?part=snippet&mine=true")

        class FakeReqObj:
            query_params = {}

        # wrong secret -> 401
        try:
            ii._resolve_project(101, "wrong-secret")
            raise AssertionError("should have 401'd")
        except Exception as e:
            assert getattr(e, "status_code", 0) == 401, e

        # right secret -> owner id
        owner = ii._resolve_project(101, "proj-secret-xyz")
        assert owner == 24, owner

        # full proxy pass-through
        import asyncio
        resp = asyncio.run(ii.integrations_proxy(req, FakeReqObj(),
                                                 authorization="Bearer proj-secret-xyz",
                                                 x_project_id="101"))
        assert resp.status_code == 200
        assert b"UC123" in resp.body
        assert calls and calls[0]["cid"] == "conn-abc-123", calls
        assert calls[0]["provider"] == "youtube"
        print("PASS 1: SECRET_KEY -> owner(24) -> owner's connection_id -> proxy; body passes through")

    # unconnected provider -> 409 before any proxy call
    calls.clear()
    ROWS_BAD = dict(ROWS, nango_one=[])
    with patch.object(ii, "_project_env_secret", fake_project_env_secret), \
         patch.object(ii, "get_db", lambda: _fake_ctx(ROWS_BAD)), \
         patch.object(nango_client, "is_configured", lambda: True), \
         patch.object(nango_client, "proxy_request", fake_proxy):
        try:
            asyncio.run(ii.integrations_proxy(req, FakeReqObj(),
                                              authorization="Bearer proj-secret-xyz",
                                              x_project_id="101"))
            raise AssertionError("should have 409'd")
        except Exception as e:
            assert getattr(e, "status_code", 0) == 409, e
        assert not calls
        print("PASS 2: no owner connection -> 409, zero provider calls")


def _fake_ctx(rows=None):
    import contextlib

    @contextlib.contextmanager
    def _ctx():
        yield FakeConn(rows or ROWS)
    return _ctx()


def test_prompt_block():
    import integration_prompt_block as ipb

    # owner connected -> block renders with snippet
    with patch.object(ipb, "get_db_ref", None, create=True), \
         patch("integration_prompt_block.get_db", lambda: _fake_ctx(), create=True):
        ipb.get_db = None  # ensure import fallback path in function
        # _oauth_block imports get_db from database_adapter inside itself — patch that
        import database_adapter
        with patch.object(database_adapter, "get_db", lambda: _fake_ctx()):
            from services.integrations import nango_client
            block = ipb._oauth_block(101)
    assert "CONNECTED OAUTH INTEGRATIONS" in block
    assert "YouTube" in block
    assert "/internal/integrations/proxy" in block
    assert "SECRET_KEY" in block
    assert '"provider": "youtube"' in block
    assert "X-Project-Id" in block and "101" in block
    assert "NEVER ask the user for an API key" in block
    assert "conn-abc" not in block and "GOCSPX" not in block and "305a2e46" not in block
    print("PASS 3: prompt snippet has proxy URL + auth pattern + project id; no secrets")

    # no connections -> empty
    empty = dict(ROWS, nango=[])
    import database_adapter as da2
    with patch.object(da2, "get_db", lambda: _fake_ctx(empty)):
        assert ipb._oauth_block(101) == ""
    assert ipb._oauth_block(None) == ""
    print("PASS 4: no owner connections / no project -> empty block (chat never breaks)")


if __name__ == "__main__":
    test_chain()
    test_prompt_block()
    print("\nALL N2 FIXTURES OK")
