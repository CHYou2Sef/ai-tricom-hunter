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
# Cleanup in persistent volume
echo "🧹 Cleaning stale application and Chrome locks..."
find /app/WORK -name ".*.lock" -delete 2>/dev/null || true
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
STARTUP_LOG="/app/logs/startup_infra.log"
echo "🔍 [$(date)] Starting Infrastructure Health Check..." > "$STARTUP_LOG"

{
    echo "--- Agent Definitions ---"
    # Skip validator.py in golden-mode (saves ~3-5s per startup; agents are pre-validated)
    if [ "$PERFORMANCE_MODE" != "golden" ]; then
        python3 scripts/validator.py
    else
        echo "⏭️  [Golden-Tiers] Skipping validator.py — agent definitions trust-established."
    fi
    
    echo -e "\n--- Browser Binaries ---"
    
    # 🕵️ Auto-fix symlinks if missing (Playwright/Patchright often changes paths)
    if ! command -v google-chrome &> /dev/null; then
        echo "⚠️ google-chrome missing from PATH. Attempting recovery..."
        CHROME_FIND=$(find /opt/ms-playwright -name "chrome" \( \
            -path "*/chrome-linux64/chrome" -o -path "*/chrome-linux/chrome" \) \
            -type f 2>/dev/null | head -n 1)
        if [ -n "$CHROME_FIND" ]; then
            ln -sf "$CHROME_FIND" /usr/bin/google-chrome
            ln -sf /usr/bin/google-chrome /usr/bin/google-chrome-stable
            echo "✅ Recovered Chrome at $CHROME_FIND"
        else
            # Fallback to cloakbrowser if available
            CLOAK_FIND=$(find /root/.cloakbrowser -name "chrome" | head -n 1)
            if [ -n "$CLOAK_FIND" ]; then
                 ln -sf "$CLOAK_FIND" /usr/bin/google-chrome
                 ln -sf /usr/bin/google-chrome /usr/bin/google-chrome-stable
                 echo "✅ Recovered Cloak Chrome at $CLOAK_FIND"
            fi
        fi
    fi

    # docker-compose may set CHROMIUM_BINARY_PATH=/usr/bin/google-chrome-stable; keep alias in sync
    if [ -e /usr/bin/google-chrome ] && [ ! -e /usr/bin/google-chrome-stable ]; then
        ln -sf /usr/bin/google-chrome /usr/bin/google-chrome-stable
        echo "✅ Linked google-chrome-stable → google-chrome"
    fi

    if ! command -v chromedriver &> /dev/null; then
        echo "⚠️ chromedriver missing from PATH. Attempting recovery..."
        DRV_FIND=$(find /usr/local -name "chromedriver" | head -n 1)
        if [ -n "$DRV_FIND" ]; then
            ln -sf "$DRV_FIND" /usr/local/bin/chromedriver
            echo "✅ Recovered Chromedriver at $DRV_FIND"
        fi
    fi

    # Final check
    google-chrome --version || echo "❌ Chrome missing"
    chromedriver --version || echo "❌ Chromedriver missing"
    
    echo -e "\n--- Directory Permissions ---"
    ls -ld /app/WORK/INCOMING /app/logs /tmp
    
} >> "$STARTUP_LOG" 2>&1

echo "✅ Startup checks complete. See logs/startup_infra.log for details."

# ── 3. Virtual Display (Xvfb) — ONLY when needed ─────────────────────
# Golden-Tiers: headless=True in Docker means SeleniumBase Chrome does NOT
# need Xvfb. Xvfb adds ~50-100 MB RAM overhead for zero benefit in golden mode.
# Skip it if PERFORMANCE_MODE=golden (DOCKER_ENV is set in docker-compose).
if [ "$PERFORMANCE_MODE" != "golden" ] && [ "$DOCKER_ENV" != "true" ]; then
    echo "🖥️ Starting Xvfb on Display :99 (Headed Mode for non-docker)..."
    Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp &
    export DISPLAY=:99
    sleep 1
else
    echo "🖥️ [Golden-Tiers] Skipping Xvfb — headless=True handles display internally."
fi

# ── 3.5 SeleniumBase UC driver (image should bake this via Dockerfile) ───
# Runtime evidence: missing uc_driver forces a mid-start download and makes
# `docker compose logs` look hung until SeleniumBase finishes printing.
UC_DRV="/usr/local/lib/python3.10/site-packages/seleniumbase/drivers/uc_driver"
if [ ! -x "$UC_DRV" ]; then
    echo "📥 SeleniumBase uc_driver missing in image — running: python3 -m seleniumbase install uc_driver"
    python3 -m seleniumbase install uc_driver >>"$STARTUP_LOG" 2>&1 || echo "⚠️ uc_driver install failed — see $STARTUP_LOG"
fi

# ── 4. Execution ────────────────────────────────────────────────────
echo "🚀 Booting IA Agent Engine..."
echo "Command: $@"
exec "$@"
