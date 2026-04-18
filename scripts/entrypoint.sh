#!/bin/bash
# ╔════════════════════════════════════════════════════════════════╗
# ║  entrypoint.sh - Container Execution Environment Setup         ║
# ╚════════════════════════════════════════════════════════════════╝
set -e

# ── 1. Recovery & Cleanup ───────────────────────────────────────────
# Remove stale Xvfb lock files (prevents "Server already active" error)
rm -f /tmp/.X1-lock /tmp/.X99-lock

# Ensure local persistence directories are writable
mkdir -p /app/logs /app/WORK /app/browser_profiles

# ── 1.5 Profile Sanitization (The Chrome Lock-Killer) ───────────────
# Forcefully remove Chrome Singleton locks that cause "Profile in use" errors
# on container restarts (very common on Linux/Fedora).
echo "🧹 Cleaning stale Chrome profile locks..."
find /app/browser_profiles -name "SingletonLock" -delete 2>/dev/null || true
find /app/browser_profiles -name "SingletonSocket" -delete 2>/dev/null || true
find /app/browser_profiles -name "SingletonCookie" -delete 2>/dev/null || true

# Don't fail if we can't chmod (e.g. read-only mounts), but try to ensure write access.
chmod 777 /app/logs /app/WORK /app/browser_profiles /tmp || true

# ── 2. Virtual Display (Xvfb) ───────────────────────────────────────
# Starts a fake, invisible monitor. This takes near-zero resources
# but allows Chrome to run in "Headed" mode to bypass bot detectors.
echo "🖥️ Starting Xvfb on Display :99 (Invisible Headed Mode)..."
Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp &
export DISPLAY=:99

# Give Xvfb short time to initialize
sleep 1

# ── 2. Agent Validation (GitAgent) ──────────────────────────────────
# If the GitAgent open standard definition exists, validate it.
if [ -f "agent.yaml" ]; then
    echo "🤖 Validating AI Agent definitions..."
    # python scripts/validator.py || { echo "❌ Native Agent validation failed!"; exit 1; }
fi

# ── 3. Execution ────────────────────────────────────────────────────
echo "🚀 Booting IA Agent Engine..."
echo "Command: $@"
exec "$@"
