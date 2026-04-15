#!/bin/bash
# ╔════════════════════════════════════════════════════════════════╗
# ║  entrypoint.sh - Container Execution Environment Setup         ║
# ╚════════════════════════════════════════════════════════════════╝

set -e

# ── 1. Virtual Display (Xvfb) ───────────────────────────────────────
# Starts a fake, invisible monitor. This takes near-zero resources
# but allows Chrome to run in "Headed" mode to bypass bot detectors.
echo "🖥️  Starting Xvfb on Display :99 (Invisible Headed Mode)..."
Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp &
export DISPLAY=:99

# Give Xvfb short time to initialize
sleep 1

# ── 2. Agent Validation (GitAgent) ──────────────────────────────────
# If the GitAgent open standard definition exists, validate it.
if [ -f "agent.yaml" ]; then
    echo "🤖 Validating AI Agent definitions..."
    python scripts/validator.py || { echo "❌ Native Agent validation failed!"; exit 1; }
fi

# ── 3. Execution ────────────────────────────────────────────────────
echo "🚀 Booting IA Agent Engine..."
echo "Command: $@"
exec "$@"
