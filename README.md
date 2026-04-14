# 🤖 AI Phone Hunter — Industrial B2B Autonomous Agent

High-performance asynchronous agent for automated company data enrichment using Google AI Mode. Designed for **24/7 autonomous operation** on Windows, macOS, and Linux with a fully resilient multi-tier browser waterfall engine.

---

## ⚡ Quick Start

### Prerequisites
- **Python 3.10+**
- **Google Chrome** (installed normally — auto-detected at runtime)

### One-Command Setup (Linux / macOS)
```bash
bash scripts/setup_dev.sh
```

### Manual Setup

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

### Configuration
Copy `.env.example` to `.env`.
- **Chrome auto-detection** is enabled by default — no path config needed.
- `OLLAMA_ENABLED=false` and `CAMOUFOX_ENABLED=false` by default (enable if you install them).

---

## 🎮 Running the Agent

The pipeline runs in two decoupled stages:

**Stage 1 — Pre-processor** (watches for new files in `WORK/INCOMING/`):
```bash
python pre_process.py
```

**Stage 2 — Main Agent** (browses & enriches data autonomously):
```bash
python main.py
```

---

## 🔬 Engine Benchmark Arena

Before deploying a configuration for production, run the **standalone benchmark** to determine the superior engine for your environment. Each engine is tested in isolation (no hybrid fallback) on the same dataset to produce empirical MTTI and success-rate data.

```bash
python scripts/benchmark_engines.py \
    --input WORK/INCOMING/your_1000_lines.xlsx \
    --engines selenium patchright nodriver \
    --rows 1000
```

**Available engines:** `selenium` | `patchright` | `nodriver` | `crawl4ai` | `camoufox`

**Output:**
- `WORK/telemetry.json` — Machine-readable ranked metrics payload
- Console — Formatted MTTI ranking report

**Key metrics per engine:**

| Metric | Description |
|---|---|
| **MTTI** | Mean Time To Interruption — uninterrupted seconds before CAPTCHA/IP ban |
| **Success Rate** | % of rows resolved as DONE (phone found) |
| **Avg Latency** | Average seconds per row |
| **CAPTCHA Blocks** | Total WAF/CAPTCHA interceptions |
| **IP Ban Events** | Total 403/429 rate-limit detections |

---

## 🏗️ Browser Engine Matrix

| Tier | Engine | Technology | Primary Strength |
|---|---|---|---|
| Benchmark | **Selenium** | UC + WebDriver 4 | Universal compatibility, easy setup |
| Tier 1 | **Patchright** | Patched Chromium (async) | Deep stealth, AI Mode search |
| Tier 2 | **Nodriver** | CDP-only, zero WebDriver flags | Cloudflare & WAF bypass |
| Tier 3 | **Crawl4AI** | Managed headless + JS rendering | Hardened e-commerce |
| Tier 4 | **Camoufox** | Patched Firefox (anti-detect) | Last resort, different engine pool |

The active engine configuration is determined by the benchmark results stored in `WORK/telemetry.json`.

---

## 🛡️ Resilience & Safety
- **Crash Proof**: Progress is committed every row in `WORK/active_processing.json`.
- **Power-Off Recovery**: The agent resumes exactly where it stopped after any interruption.
- **Circuit Breaker**: After 5 consecutive failures, the engine pauses for 5 minutes and rotates proxy before resuming.
- **Log Rotation**: Logs are automatically compressed at 10MB to prevent disk exhaustion.

---

## 📂 Project Structure

```
ai_phone_hunter/
├── main.py                  ← Agent orchestration entry point
├── pre_process.py           ← File ingestion & classification watcher
├── config.py                ← Master control panel (all settings here)
├── agent.py                 ← Core row-processing orchestrator
├── agents/                  ← Specialized agent modules
│   ├── phone_hunter.py      ← Primary search & extraction logic
│   └── enricher.py          ← Data enrichment layer
├── browser/                 ← Browser automation engines
│   ├── hybrid_engine.py     ← Multi-tier waterfall router
│   ├── selenium_agent.py    ← Selenium + undetected-chromedriver (benchmark)
│   ├── patchright_agent.py  ← Tier 1 (Patchright stealth Chrome)
│   ├── nodriver_agent.py    ← Tier 2 (Nodriver CDP-only)
│   ├── crawl4ai_agent.py    ← Tier 3 (Crawl4AI managed)
│   └── camoufox_agent.py    ← Tier 4 (Camoufox Firefox)
├── scripts/
│   ├── benchmark_engines.py ← Engine benchmark arena (NEW)
│   └── setup_dev.sh         ← One-shot developer environment bootstrap
├── utils/
│   ├── metrics.py           ← Dual-output MTTI telemetry engine (NEW)
│   └── universal_extractor.py ← UUE — central DOM parsing brain
├── WORK/                    ← Runtime data (gitignored)
│   ├── INCOMING/            ← Drop input files here
│   ├── output/              ← Live extraction results
│   ├── ARCHIVE/             ← Processed file backups
│   └── telemetry.json       ← Latest benchmark metrics (auto-generated)
└── logs/                    ← Rolling daily logs
```
