#!/bin/bash
# DreamAgent workspace container entrypoint.
#
# Copies the baked-in Claude config templates from /opt/claude-config/ into
# the writable tmpfs at /home/dreampilot/, then execs the main command.
#
# Why this exists:
#   The container runs with --read-only rootfs (security hardening). Claude
#   needs to WRITE to ~/.claude/ (session state, caches, .claude.json updates).
#   We mount /home/dreampilot as tmpfs (writable, ephemeral) and copy the
#   pre-baked config in on every start. This gives Claude a writable home
#   without weakening the read-only rootfs protection on the rest of the FS.
#
# Files copied:
#   /opt/claude-config/settings.json → /home/dreampilot/.claude/settings.json
#   /opt/claude-config/.claude.json  → /home/dreampilot/.claude.json

set -e

CLAUDE_CONFIG_SRC="/opt/claude-config"
CLAUDE_HOME="/home/dreampilot/.claude"
CLAUDE_JSON="/home/dreampilot/.claude.json"

# Ensure directories exist (tmpfs starts empty)
mkdir -p "$CLAUDE_HOME"

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

# Ensure correct ownership (tmpfs might default to root)
chown -R dreampilot:dreampilot /home/dreampilot

# Drop privileges and exec the main command
exec gosu dreampilot "$@"
