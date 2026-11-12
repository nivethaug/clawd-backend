#!/usr/bin/env python3
"""Subdomain swap — runs ON the box hosting the project (worker or main).

Ordering (safety-first):
  1. Build the new vhost (same dist_path, new server_name) + install it
  2. Create new DNS records ({new} + {new}-api → SERVER_IP)
  3. Rewrite api-config.ts old→new domain, drop stale dist/
  4. Rebuild the frontend (embeds the new API base)
  5. Verify the new URL serves 200
  6. ONLY THEN tear down the old: remove old vhost, delete old DNS records

If any step 1-5 fails → rollback what was created (new vhost + new DNS),
old subdomain untouched and keeps serving.
"""

import logging
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("services.subdomain_swap")


def perform_subdomain_swap(payload: Dict[str, Any]) -> Dict[str, Any]:
    old_sub = payload["old_subdomain"]
    new_sub = payload["new_subdomain"]
    project_path = payload.get("project_path") or ""
    backend_port = payload.get("backend_port")

    out: Dict[str, Any] = {"ok": False, "message": ""}
    steps_done: Dict[str, bool] = {"vhost": False, "dns": False, "rebuild": False}

    try:
        from infrastructure_manager import DNSProvisioner, NginxConfigurator
        from domain_config import BASE_DOMAIN
    except ImportError as e:
        out["message"] = f"infra import failed: {e}"
        return out

    nginx = NginxConfigurator()
    dns = DNSProvisioner()

    frontend_dist = str(Path(project_path) / "frontend" / "dist")

    # ── rollback helper ────────────────────────────────────────────────
    def _rollback(reason: str) -> Dict[str, Any]:
        logger.warning("[SUBDOMAIN-SWAP] rolling back (%s)", reason)
        try:
            if steps_done["vhost"]:
                nginx.remove_config(new_sub)
        except Exception as exc:
            logger.error("[SUBDOMAIN-SWAP] rollback vhost failed: %s", exc)
        try:
            if steps_done["dns"]:
                dns.delete_a_record(new_sub)
                dns.delete_a_record(f"{new_sub}-api")
        except Exception as exc:
            logger.error("[SUBDOMAIN-SWAP] rollback DNS failed: %s", exc)
        return {"ok": False, "message": reason}

    try:
        # 1. New vhost (frontend-only static if no backend_port)
        new_conf = nginx.generate_config(
            new_sub, None, backend_port,
            project_path=Path(project_path).name,
            dist_path=frontend_dist,
        )
        new_fe_domain, _new_be_domain, conf = new_conf
        if not nginx.install_config(new_sub, conf):
            return _rollback("nginx install failed for new subdomain")
        steps_done["vhost"] = True
        nginx.reload_nginx()

        # 2. New DNS records
        dns.create_a_record(new_sub)
        dns.create_a_record(f"{new_sub}-api")
        steps_done["dns"] = True

        # 3. api-config rewrite (old→new; placeholder already consumed at
        #    creation time, so replace the literal old domain string)
        api_cfg = Path(project_path) / "frontend" / "src" / "lib" / "api-config.ts"
        if api_cfg.exists():
            content = api_cfg.read_text(encoding="utf-8")
            rewritten = content.replace(f"{old_sub}-api.{BASE_DOMAIN}", f"{new_sub}-api.{BASE_DOMAIN}")
            rewritten = rewritten.replace(f"{old_sub}.{BASE_DOMAIN}", f"{new_sub}.{BASE_DOMAIN}")
            if rewritten != content:
                api_cfg.write_text(rewritten, encoding="utf-8")
        dist_dir = Path(project_path) / "frontend" / "dist"
        if dist_dir.exists():
            import shutil
            shutil.rmtree(dist_dir, ignore_errors=True)

        # 4. Rebuild frontend (npm run build; node_modules already warm)
        frontend_dir = Path(project_path) / "frontend"
        build = subprocess.run(
            ["npm", "run", "build"],
            cwd=str(frontend_dir),
            capture_output=True, text=True, timeout=420,
        )
        if build.returncode != 0 or not (frontend_dir / "dist" / "index.html").exists():
            return _rollback(f"frontend rebuild failed: {build.stderr[-300:]}")
        steps_done["rebuild"] = True

        # 5. Verify new URL serves (direct against local nginx — DNS may
        #    still be propagating, so resolve via Host header on localhost)
        import httpx as _httpx
        verify_target = f"https://{new_fe_domain}/"
        try:
            probe = _httpx.get(
                verify_target,
                timeout=20,
                verify=False,  # local wildcard cert check can fail pre-DNS
                headers={"Host": new_fe_domain},
            )
            verified = probe.status_code == 200
        except Exception as exc:
            logger.warning("[SUBDOMAIN-SWAP] https probe failed (%s) — trying http", exc)
            try:
                probe = _httpx.get(
                    f"http://{new_fe_domain}/",
                    timeout=20,
                    headers={"Host": new_fe_domain},
                )
                verified = probe.status_code == 200
            except Exception:
                verified = False
        if not verified:
            return _rollback("new subdomain did not verify as serving")

        # 6. Teardown old (only after new verified)
        try:
            nginx.remove_config(old_sub)
        except Exception as exc:
            logger.warning("[SUBDOMAIN-SWAP] old vhost removal failed (continuing): %s", exc)
        try:
            dns.delete_a_record(old_sub)
            dns.delete_a_record(f"{old_sub}-api")
        except Exception as exc:
            logger.warning("[SUBDOMAIN-SWAP] old DNS removal failed (continuing): %s", exc)
        nginx.reload_nginx()

        out.update({
            "ok": True,
            "old_domain": f"{old_sub}.{BASE_DOMAIN}",
            "new_domain": f"{new_sub}.{BASE_DOMAIN}",
            "verified": True,
        })
        logger.info("[SUBDOMAIN-SWAP] %s → %s verified", old_sub, new_sub)
        return out

    except Exception as exc:
        logger.exception("[SUBDOMAIN-SWAP] unexpected failure")
        return _rollback(f"unexpected error: {exc}")
