#!/bin/bash
# ╔════════════════════════════════════════════════════════════════╗
# ║  entrypoint.sh - Container Execution Environment Setup         ║
# ╚════════════════════════════════════════════════════════════════╝
set -e

# ── 1. Recovery & Cleanup ───────────────────────────────────────────
# Remove stale Xvfb lock files (prevents "Server already active" error)
rm -f /tmp/.X1-lock /tmp/.X99-lock

# Ensure local persistence directories are writable (Complete 3-Layer Structure)
echo "📁 Creating autonomous directory structure..."
mkdir -p /app/logs \
         /app/WORK/INCOMING \
         /app/WORK/ARCHIVE \
         /app/WORK/READY \
         /app/WORK/STD \
         /app/WORK/SIREN \
         /app/WORK/RS \
         /app/WORK/OTHERS \
         /app/WORK/CHECKPOINTS \
         /app/WORK/browser_profiles

# ── 1.5 Profile Sanitization (The Chrome Lock-Killer) ───────────────
# Forcefully remove Chrome Singleton locks that cause "Profile in use" errors
# on container restarts (very common on Linux/Fedora).
echo "🧹 Cleaning stale Chrome profile locks..."
# Cleanup in persistent volume
find /app/WORK/browser_profiles -name "SingletonLock" -delete 2>/dev/null || true
find /app/WORK/browser_profiles -name "SingletonSocket" -delete 2>/dev/null || true
find /app/WORK/browser_profiles -name "SingletonCookie" -delete 2>/dev/null || true
# Cleanup in RAM disk (Docker-specific speed boost)
find /dev/shm -name "SingletonLock" -delete 2>/dev/null || true
find /dev/shm -name "SingletonSocket" -delete 2>/dev/null || true
find /dev/shm -name "SingletonCookie" -delete 2>/dev/null || true

# Don't fail if we can't chmod (e.g. read-only mounts), but try to ensure write access.
chmod -R 777 /app/logs /app/WORK /tmp 2>/dev/null || true

# ── 2. Infrastructure Health Check ──────────────────────────────────
# Log all startup checks to a dedicated file for audit
STARTUP_LOG="/app/logs/startup_infra.log"
echo "🔍 [$(date)] Starting Infrastructure Health Check..." > "$STARTUP_LOG"

{
    echo "--- Agent Definitions ---"
    python3 scripts/validator.py
    
    echo -e "\n--- Browser Binaries ---"
    google-chrome --version || echo "❌ Chrome missing"
    chromedriver --version || echo "❌ Chromedriver missing"
    
    echo -e "\n--- Directory Permissions ---"
    ls -ld /app/WORK/INCOMING /app/logs
    
} >> "$STARTUP_LOG" 2>&1

echo "✅ Startup checks complete. See logs/startup_infra.log for details."

# ── 3. Virtual Display (Xvfb) ───────────────────────────────────────
# Starts a fake, invisible monitor. This takes near-zero resources
# but allows Chrome to run in "Headed" mode to bypass bot detectors.
echo "🖥️ Starting Xvfb on Display :99 (Invisible Headed Mode)..."
Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp &
export DISPLAY=:99

# Give Xvfb short time to initialize
sleep 1

# ── 4. Execution ────────────────────────────────────────────────────
echo "🚀 Booting IA Agent Engine..."
echo "Command: $@"
exec "$@"
