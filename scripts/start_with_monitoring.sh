#!/bin/bash
# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  start_with_monitoring.sh — Dual-process launcher (Worker + Monitor)    ║
# ║                                                                          ║
# ║  Starts both the 24/7 file watchdog worker AND the FastAPI monitoring   ║
# ║  API in the same container. Uses background jobs for simplicity.         ║
# ╚══════════════════════════════════════════════════════════════════════════╝

set -e

echo "🚀 Starting AI Tricom Hunter with Monitoring API..."

# ── 0. Infrastructure Prep ──────────────────────────────────────────────
echo "🧹 Cleaning stale Chrome profile locks..."
find /tmp -name ".com.google.Chrome.*" -exec rm -rf {} + 2>/dev/null || true
find ./browser_profiles -name "SingletonLock" -exec rm -f {} + 2>/dev/null || true

echo "🔒 Fixing permissions on WORK/ directory..."
chmod -R 777 WORK/ 2>/dev/null || true
chmod -R 777 logs/ 2>/dev/null || true

# ── 1. Start Xvfb (virtual display) if not already running ────────────────
if [ -z "$DISPLAY" ] || ! pgrep -x "Xvfb" > /dev/null; then
    echo "🖥️  Starting Xvfb on :99..."
    Xvfb :99 -screen 0 1920x1080x24 -ac +extension GLX +render -noreset &
    export DISPLAY=:99
    sleep 2
fi

# ── 2. Start FastAPI Monitoring API (background) ─────────────────────────
echo "📊 Starting monitoring API on port 8000..."
python -m uvicorn app.monitoring.app:app --host 0.0.0.0 --port 8000 --loop asyncio &
MONITOR_PID=$!

# ── 3. Wait for monitor to be ready ──────────────────────────────────────
for i in {1..10}; do
    if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
        echo "✅ Monitoring API ready at http://localhost:8000"
        break
    fi
    sleep 1
done

# ── 4. Start the main worker (foreground — blocks) ───────────────────────
echo "🤖 Starting agent worker..."
python run/worker.py &
WORKER_PID=$!

# ── 5. Graceful shutdown handler ─────────────────────────────────────────
shutdown() {
    echo "🛑 Shutting down..."
    kill -TERM "$WORKER_PID" 2>/dev/null || true
    kill -TERM "$MONITOR_PID" 2>/dev/null || true
    wait
    exit 0
}
trap shutdown SIGTERM SIGINT

# ── 6. Keep script alive, restart children if they die ───────────────────
while true; do
    if ! kill -0 "$WORKER_PID" 2>/dev/null; then
        echo "⚠️  Worker died. Exiting..."
        shutdown
    fi
    if ! kill -0 "$MONITOR_PID" 2>/dev/null; then
        echo "⚠️  Monitor died. Restarting..."
        python -m uvicorn app.monitoring.app:app --host 0.0.0.0 --port 8000 --loop asyncio &
        MONITOR_PID=$!
    fi
    sleep 5
done

