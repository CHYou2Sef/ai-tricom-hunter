# 🤖 AI Tricom Hunter — Industrial B2B Autonomous Agent

High-performance asynchronous agent for automated company data enrichment. Designed for **24/7 autonomous operation** on Windows, macOS, and Linux with a fully resilient multi-tier browser waterfall engine.

---

## 🚀 Getting Started (Pre-flight Checklist)

1. **Clone the Project:**
   ```bash
   git clone https://github.com/youssef/ai_tricom_hunter.git
   cd ai_tricom_hunter
   ```

2. **Configure Environment:**
   Copy the example environment file and fill in your API keys (Google AI, Proxy settings, etc.):
   ```bash
   cp .env.example .env
   ```

3. **Prepare Work Directory:**
   Ensure the `WORK/INCOMING` folder exists (this is where you will drop your Excel files):
   ```bash
   mkdir -p WORK/INCOMING
   ```

---

## 🐳 Option 1: Docker Deployment (Recommended for All OS)
The easiest way to run the agent. It handles all system dependencies, headless displays (`Xvfb`), and browser binaries automatically.

### Prerequisites
- **Windows/Mac:** [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running.
- **Linux:** Docker + Docker Compose installed.

### Commands
```bash
# 1. Build and start the agent in background
docker compose up -d --build

# 2. View the live agent output (Recommended)
docker logs -f tricom_ai_agent

# 3. Stop the agent
docker compose down
```

*Note: In Docker, `pre_process.py` and `main.py` are managed automatically by the container entrypoint.*

---

## 💻 Option 2: Local Developer Setup (Win / Mac / Linux)
Follow these steps if you want to run the code natively on your host machine.

### 1. Requirements
- **Python 3.10 or 3.11** (Recommended)

### 2. Installation
```bash
# Create and activate virtual environment
# Windows:
python -m venv venv
venv\Scripts\activate

# Linux / Mac:
python3 -m venv venv
source venv/bin/activate

# Install dependencies (use 'uv' for 10x faster install if you have it)
pip install -r requirements.txt

# Install Stealth Browser Binaries (CRITICAL)
patchright install chromium
```

### 3. Running the Pipeline
The agent runs in a two-stage 24/7 pipeline. **Open two terminal windows:**

#### **Terminal 1: Pre-Processor**
Watches the `INCOMING` folder, cleans data, and splits large files into manageable chunks.
```bash
python pre_process.py
```

#### **Terminal 2: Main Agent**
Picks up cleaned files and starts the autonomous browsing/enrichment process.
```bash
python main.py
```

---

## 🏛️ Pipeline Flow
1. **Drop File:** Put your `.xlsx` or `.csv` in `WORK/INCOMING/`.
2. **Pre-Process:** `pre_process.py` detects it, normalizes data, and moves chunks to `WORK/STD/` (or `RS/`, `SIREN/`).
3. **Enrichment:** `main.py` workers pick up the chunks and enrichment begins using the Waterfall engine (Patchright → Nodriver → Crawl4AI).
4. **Results:** Final enriched files appear in `WORK/output/`.

---

## 🛠️ Maintenance & Troubleshooting

### ❌ "Another instance is already running"
The agent uses a **Singleton Pattern** to prevent data corruption. If you see this error:
- **Docker:** You are likely trying to run `python main.py` manually while the container is already running it. Use `docker logs -f tricom_ai_agent`.
- **Local:** Check if a previous script is still hanging in the background and kill it.

### 🧹 Cleaning Stale Locks
If the browser fails to start because of a profile lock:
- **Docker:** The `entrypoint.sh` automatically cleans these on restart. Run `docker compose restart`.
- **Local:** Delete any `SingletonLock` files found in the `browser_profiles/` directory.

### 📁 Permissions (Linux/Fedora)
If you get `Permission Denied` on the `WORK/` folder inside Docker:
```bash
sudo chown -R $USER:$USER WORK/ logs/
```

---

## 📂 Project Structure
- `agent.yaml`: Core agent definition & model settings.
- `config.py`: The "Control Panel" for all settings (delays, workers, paths).
- `browser/`: The hybrid engine logic and browser agents.
- `excel/`: High-performance pandas handlers for reading/writing results.
- `utils/`: Anti-bot logic, singleton management, and logging.
- `WORK/`: The persistent data wormhole (Input -> Processing -> Output).

---
*Built for industrial-grade stability and 24/7 autonomy.*
