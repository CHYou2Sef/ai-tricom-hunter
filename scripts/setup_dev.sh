#!/bin/bash
# AI Phone Hunter - Developer Setup Script

echo "🚀 Starting Developer Setup..."

# 1. Check Python version
python3 --version || { echo "❌ Python 3 not found"; exit 1; }

# 2. Setup virtual environment
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
fi
source venv/bin/activate

# 3. Install dependencies
echo "📥 Installing requirements..."
pip install --upgrade pip
pip install -r requirements.txt

# 4. Initialize Tools (Skipped code-review-graph)

# 5. Environment Setup
if [ ! -f ".env" ]; then
    echo "📄 Creating .env from template..."
    cp .env.example .env
fi

# 6. Browser Setup
echo "🌐 Installing browser binaries..."
patchright install chromium

echo "✅ Setup Complete. Run 'python main.py' to start."
