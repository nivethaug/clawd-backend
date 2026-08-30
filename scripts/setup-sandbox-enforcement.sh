#!/bin/bash
# Worker VPS sandbox-enforcement setup — Layers 1C/2/3.
# Safe to run repeatedly; prints the manual XFS step instead of doing it.
set -euo pipefail

echo "══ 1C: shared wheelhouse ═════════════════════════════════"
bash "$(dirname "$0")/build-wheelhouse.sh" || echo "  (wheelhouse build failed — installs fall back to PyPI; gate still active)"
grep -q "^WHEELHOUSE_URL=" /root/clawd-backend/.env.postgres 2>/dev/null \
  && echo "  WHEELHOUSE_URL already set" \
  || echo "  → add to /root/clawd-backend/.env.postgres:  WHEELHOUSE_URL=/opt/wheelhouse"

echo
echo "══ 3: egress allowlist (squid sidecar) ══════════════════"
if grep -q "^EGRESS_ENFORCE=1" /root/clawd-backend/.env.postgres 2>/dev/null; then
  echo "  EGRESS_ENFORCE=1 already set — restarting sidecar on next container create"
else
  cat <<'EOF'
  → add to /root/clawd-backend/.env.postgres:

  EGRESS_ENFORCE=1
  EGRESS_ALLOWLIST=pypi.org,files.pythonhosted.org,registry.npmjs.org,api.github.com,github.com,objects.githubusercontent.com,api.dreamagent.cloud
  EGRESS_REPLY_MAX_MB=200
EOF
fi

echo
echo "══ 2: XFS per-project disk quota (MAINTENANCE WINDOW) ═══"
FS_TYPE=$(stat -f -c %T /var/lib/docker 2>/dev/null || echo unknown)
if [ "$FS_TYPE" = "xfs" ]; then
  echo "  docker root is XFS ✓ — check pquota is enabled:"
  mount | grep -E "xfs" | head -3
  echo "  → if no 'pquota' in the docker-root mount options: add prjquota to"
  echo "    its fstab entry and remount, then set PROJECT_DISK_LIMIT_GB=10"
  echo "    in .env.postgres (enables --storage-opt size= per container)."
else
  echo "  docker root is '$FS_TYPE' (not XFS) — --storage-opt size= will fail."
  cat <<'EOF'
  → to enable hard per-container disk caps (schedule downtime):
      1. docker system stop / stop containers
      2. pick a volume, e.g. /dev/sdb:
           wipefs -a /dev/sdb
           mkfs.xfs -f /dev/sdb
           mount -o pquota,prjquota /dev/sdb /var/lib/docker   (fstab: ... xfs pquota,prjquota 0 0)
      3. move docker data-root to it (daemon.json: "data-root": "/var/lib/docker")
      4. restart docker, then set PROJECT_DISK_LIMIT_GB=10 in .env.postgres
  Until then the reaper's soft quota (du monitor) covers over-limit projects.
EOF
fi

echo
echo "══ restart services ═════════════════════════════════════"
echo "  cd /root/clawd-backend && git pull"
echo "  systemctl restart <worker-api> <scheduler> && pm2 restart container-reaper 2>/dev/null || true"
echo "Done."
