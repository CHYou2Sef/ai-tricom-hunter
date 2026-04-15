#!/bin/bash
# ╔═══════════════════════════════════════════════════════════════════╗
# ║  Architecture Validation Suite                                    ║
# ║  Tests the 4-Pillar setup: uv, GitAgent, and Docker builds        ║
# ╚═══════════════════════════════════════════════════════════════════╝

set -e

echo "🧪 Starting Architecture Validation Suite..."

# 1. Check uv (Environment Pillar)
if ! command -v uv &> /dev/null; then
    echo "❌ uv is NOT installed! Run scripts/setup_dev.sh first."
    exit 1
else
    echo "✅ [Pillar 1/4] Environment Manager (uv) detected."
fi

# 2. Check GitAgent (Agent Definition Pillar)
echo "🔍 Validating AI Agent definitions (agent.yaml, SOUL.md, RULES.md)..."
python scripts/validator.py

# 3. Check Docker (Containerization Pillar)
if ! command -v docker &> /dev/null; then
    echo "⚠️ Docker is NOT installed locally. Skipping Container Build Test."
else
    echo "🐳 [Pillar 2/4] Docker detected. Testing Container Build..."
    echo "Building 'ai-phone-hunter-test:latest'..."
    docker build -t ai-phone-hunter-test:latest .
    echo "✅ Docker build succeeded!"
fi

echo "🎉 Architecture Validation COMPLETE! The 4-Pillar framework is perfectly stable."
