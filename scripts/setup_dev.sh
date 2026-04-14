#!/bin/bash
# ╔═══════════════════════════════════════════════════════════════════╗
# ║  AI Phone Hunter — Developer Setup Script                         ║
# ║  One-shot environment bootstrap for all browser tiers             ║
# ╚═══════════════════════════════════════════════════════════════════╝

set -e
echo "🚀 Starting Developer Setup..."

# 1. Check Python version
python3 --version || { echo "❌ Python 3 not found"; exit 1; }

# 2. Setup virtual environment
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
fi
source venv/bin/activate

# 3. Install all Python dependencies (includes Selenium + undetected-chromedriver)
echo "📥 Installing requirements..."
pip install --upgrade pip
pip install -r requirements.txt

# 4. Environment Setup
if [ ! -f ".env" ]; then
    echo "📄 Creating .env from template..."
    cp .env.example .env
fi

# 5. Browser Binaries

# Tier 0 (Selenium) — ChromeDriver is managed automatically by webdriver-manager
# and undetected-chromedriver. No manual step required.
echo "🌐 [Tier 0] Selenium ChromeDriver will be auto-managed at runtime."


# Tier 1 (Patchright/Chromium stealth)
echo "🌐 [Tier 1] Installing Patchright Chromium..."
patchright install chromium


# Tier 4 (Camoufox — optional, heavy ~200MB Firefox binary)
if [ "${INSTALL_CAMOUFOX:-false}" = "true" ]; then
    echo "🦊 [Tier 4] Installing Camoufox Firefox binary (~200MB)..."
    python -m camoufox fetch
else
    echo "⚠️  [Tier 4] Camoufox skipped. Set INSTALL_CAMOUFOX=true to enable."
fi

# 6. Create required WORK/ directory structure
echo "📁 Initializing WORK/ directory structure..."
python3 -c "
import sys; sys.path.insert(0, '.')
import config
dirs = [
    config.INCOMING_DIR, config.INPUT_STD_DIR, config.INPUT_SIR_DIR,
    config.INPUT_RS_DIR, config.OUTPUT_ROOT, config.ARCHIVE_BACKUP_DIR,
    config.OUTPUT_SUCCEED_DIR, config.OUTPUT_FAILED_DIR, config.READY_DIR,
]
for d in dirs:
    d.mkdir(parents=True, exist_ok=True)
print('  ✅ WORK/ structure ready.')
"

echo "  ✅  Setup Complete!   "
                                           
python main.py 