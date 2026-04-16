@echo off
:: ╔══════════════════════════════════════════════════════════════════════╗
:: ║  update.bat — AI Tricom Hunter Windows Update Helper                ║
:: ╚══════════════════════════════════════════════════════════════════════╝

echo [Update] Starting Industrial Update Cycle...

echo [Git] Pulling latest changes...
git pull origin main

echo [Docker] Re-building and replacing container...
docker compose up -d --build --remove-orphans

echo [Cleanup] Cleaning disk space...
docker image prune -f

echo [Success] Update Complete!
pause
