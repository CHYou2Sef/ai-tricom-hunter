# 🤖 AI Phone Hunter - Universal B2B Agent

High-performance asynchronous agent for automated company data enrichment using Google AI Mode. Works on **Windows, macOS, and Linux**.

---

## ⚡ Quick Start (All OS)

### 1. Requirements
- **Python 3.10+**
- **Google Chrome** (Just install the regular browser, the agent will find it automatically).

### 2. Tools (Optional)
The project is optimized for speed and simplicity. Advanced tools like `code-review-graph` are now optional.

### 3. Setup
Clone the repository and run:

**Windows (PowerShell):**
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
patchright install chromium
```

**macOS / Linux:**
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
patchright install chromium
```

### 4. Configuration
Copy `.env.example` to `.env`. 
- **Auto-Detect Chrome:** By default, the agent searches for your installed Chrome. No path config needed!
- **Ollama/Camoufox:** Disabled by default for maximum speed and simplicity. (Set to `true` only if you manually install them).

---

## 🎮 How to Run

The pipeline works in two steps:

1.  **Ingestion:** Start the pre-processor to watch for new files in `WORK/INCOMING/`.
    ```bash
    python pre_process.py
    ```
2.  **Enrichment:** Start the main agent to begin browsing and extracting data.
    ```bash
    python main.py
    ```

---

## 🛡️ Resilience & Safety
- **Crash Proof:** Progress is saved every row in `WORK/active_processing.json`.
- **Power Off:** If your PC shuts down, the agent resumes exactly where it left off.
- **Stealth:** Uses a 3-tier hybrid engine (Patchright, Nodriver, Crawl4AI) to bypass most anti-bot protections.

---

## 📂 Project Structure
- `WORK/INCOMING/`: Drop your raw Excel/CSV files here.
- `WORK/output/`: Final results appear here.
- `logs/`: Daily logs for monitoring activity.
- `utils/progress_tracker.py`: The "recovery" brain of the project.
