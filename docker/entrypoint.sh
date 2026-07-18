#!/bin/bash
# DreamAgent workspace container entrypoint.
#
# Runs AS dreampilot (uid 1001) — docker run sets --user 1001:1001.
# Copies the baked-in Claude config templates from /opt/claude-config/ into
# the writable tmpfs at /home/dreampilot/, then execs the main command.
#
# Why this exists:
#   The container runs with --read-only rootfs (security hardening). Claude
#   needs to WRITE to ~/.claude/ (session state, caches, .claude.json updates).
#   We mount /home/dreampilot as tmpfs (writable, ephemeral, owned by 1001)
#   and copy the pre-baked config in on every start. This gives Claude a
#   writable home without weakening the read-only rootfs protection.
#
# NO gosu/sudo needed — docker run already sets the user to dreampilot.

set -e

CLAUDE_CONFIG_SRC="/opt/claude-config"
CLAUDE_HOME="/home/dreampilot/.claude"
CLAUDE_JSON="/home/dreampilot/.claude.json"

# Ensure directories exist (tmpfs starts empty; dreampilot owns it via uid=1001 mount opt)
mkdir -p "$CLAUDE_HOME"
mkdir -p /home/dreampilot/.npm /home/dreampilot/.config

# Copy settings template (preserves the baked config with correct proxy URL)
if [[ -f "$CLAUDE_CONFIG_SRC/settings.json" ]]; then
    cp "$CLAUDE_CONFIG_SRC/settings.json" "$CLAUDE_HOME/settings.json"
    chmod 600 "$CLAUDE_HOME/settings.json"
fi

# Copy onboarding state (hasCompletedOnboarding=true)
if [[ -f "$CLAUDE_CONFIG_SRC/.claude.json" ]]; then
    cp "$CLAUDE_CONFIG_SRC/.claude.json" "$CLAUDE_JSON"
    chmod 600 "$CLAUDE_JSON"
fi

# Exec the main command (already running as dreampilot)
exec "$@"
