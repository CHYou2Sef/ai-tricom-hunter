#!/bin/bash
# ╔══════════════════════════════════════════════════════════════════════╗
# ║  update.sh — AI Tricom Hunter Industrial Update Script               ║
# ║                                                                      ║
# ║  This script automates the full CI/CD pull and redeployment cycle.   ║
# ║  It handles the re-build and container replacement automatically.    ║
# ╚══════════════════════════════════════════════════════════════════════╝

echo "🔄 [Update] Starting Industrial Update Cycle..."

# 1. Pull latest code from GitHub
echo "📡 [Git] Pulling latest changes from origin..."
git pull origin main

# 2. Re-build and Re-deploy
echo "🐳 [Docker] Re-building and replacing container..."

docker compose up -d --build --remove-orphans
# -d: background mode
# --build: force rebuild of image
# --remove-orphans: clean up old stale containers

# 3. Cleanup stale images to save HDD space
echo "🧹 [Cleanup] Removing dangling images (HDD optimization)..."
docker image prune -f

echo "✅ [Success] AI Tricom Hunter is now UP TO DATE."
