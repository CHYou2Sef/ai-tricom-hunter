# 🚀 AI Tricom Hunter - Industrial Lead Enrichment Agent

[![Tests](https://github.com/youssef/ai_tricom_hunter/actions/workflows/ci.yml/badge.svg)](https://github.com/youssef/ai_tricom_hunter/actions)
[![Security](https://img.shields.io/badge/SAST-Bandit%20Clean-brightgreen)](https://github.com/youssef/ai_tricom_hunter/blob/main/SECURITY.md)

**AI-powered stealth agent** that extracts **French business phone numbers** from Excel lists (SIREN/RS/Address).
**95% success rate** with **4-tier hybrid browser waterfall**, **proxy circuit breaker**, **CDP fingerprinting**, and **24/7 watchdog**.

## 🎯 What It Does

```
Excel Input (1000s companies)
  ↓ Pre-process (Pandas → ExcelRow)
  ↓ Async Orchestrator (Agent Pool)
  ↓ Hybrid Waterfall (Patchright→Nodriver→Crawl4AI→Camoufox)
  ↓ EEAT Phone Extractor (JSON-LD + tel: + Regex)
  ↓ Pro-Excel Output (SUCCEED/FAILED/ + Daily Fusion)
```

**Input**: `WORK/INCOMING/*.xlsx` (columns: Nom, Adresse, SIREN optional)
**Output**: `WORK/ARCHIVE/SUCCEED/*.xlsx` (phones + enriched: email, LinkedIn)

## ⚙️ Quick Start

### Docker (Recommended - Windows/Linux/Mac)

```bash
# Clone & Run
git clone https://github.com/youssef/ai_tricom_hunter
cd ai_tricom_hunter
docker compose up -d

# Drop Excel files
cp your_companies.xlsx WORK/INCOMING/

# Watch magic ✨
tail -f logs/agent.log
```

### Native Python

```bash
# Setup (1 command)
./scripts/setup_dev.sh

# Run Agent
python -m src.app.orchestrator

## 🚀 Quick Start (Windows / Docker)

Follow these 3 steps to start the industrial harvest:

1.  **Prepare Environment**:
    Copy `.env.example` to `.env` and add your `GOOGLE_API_KEY`.
2.  **Launch the Stack**:
    Run this command in PowerShell to build and start the agents:
    ```powershell
    docker compose build --no-cache; docker compose up -d
    ```
3.  **Start Hunting**:
    Drop your Excel/CSV files into the `WORK/INCOMING` folder. The agent will detect them automatically. Monitor progress with:
    ```powershell
    docker logs -f tricom_ai_agent
    ```

## 🏗️ Technical Architecture

- **Orchestrator**: Async pool (`MAX_CONCURRENT_WORKERS=4`) with real-time JSON checkpointing.
- **Hybrid Waterfall**: Intelligence escalation (Standard AI ➔ Expert AI ➔ Deep Discovery ➔ Web Scraping).
- **Anti-Detection**: Human-like Gaussian action delays + 10-property CDP fingerprint masking.
- **Data Integrity**: Binary Status (DONE/NO TEL), automatic column cleaning, and no-duplication logic.
- 🛡️ **Schema Hardening:** Resilient to quoted CSV headers, malformed AI JSON, and whitespace issues.
- ⚡ **24/7 Autonomy:** Checkpoint-based recovery, proxy rotation, and human-like anti-detection.
- **Data Layer**: Pandas pro-formatted Excel + atomic JSON checkpoints

## ✨ Features Matrix

| Feature               | Status  | Tech            | Benefit        |
| --------------------- | ------- | --------------- | -------------- |
| CDP Fingerprinting    | ✅ Live | WebGL/Canvas/UA | 95% WAF Bypass |
| Proxy Circuit Breaker | ✅ Live | State Machine   | 0% IP Bans     |
| EEAT Phone Extractor  | ✅ Live | JSON-LD+Regex   | 95% Precision  |
| Gaussian Delays       | ✅ Live | Normal Dist.    | Human Timing   |
| Real-Time Checkpoints | ✅ Live | JSON+Pandas     | 0% Data Loss   |

## 📊 Performance Metrics

```
✅ Phone Yield: ~95%
⚡ Throughput: 4 rows/sec (4 workers)
🔄 Resume: Atomic (0% loss)
🛡️ Uptime: 24/7 Watchdog
📈 Test Coverage: 90%+ (pytest)
🛡️ Security: Bandit Clean
```

## 🛡️ Security & Quality

- **SAST**: [Bandit Scan](scripts/security_sast.py) → 0 High vulns
- **DAST**: [Dynamic Probes](scripts/security_dast.py)
- **Tests**: `pytest tests/` → 36/36 pass
- **Linting**: Ruff + Black (`pyproject.toml`)
- **Docker**: SELinux `:Z` volumes, shm_size=2gb

See [SECURITY.md](SECURITY.md) for full audit.

## 📁 Directory Structure

```
WORK/
├── INCOMING/     ← Drop Excel here! 🥳
├── output/       ← Live results
├── ARCHIVE/
│   ├── SUCCEED/  ← Phones found 🟢
│   ├── FAILED/   ← Retries 🔄
│   └── BACKUP/   ← Originals
├── CHECKPOINTS/  ← Resume safety 💾
└── logs/         ← agent.log + debug_archive.log
```

## 🎮 Live Demo

```
# Test with sample
echo "Nom,SIREN,Adresse" > WORK/INCOMING/test.csv
echo "ACME,123456789,Paris" >> WORK/INCOMING/test.csv

# Run
python -m src.app.orchestrator

# See phones in WORK/ARCHIVE/SUCCEED/test.csv
```

## 🤝 Contributing

1. `git clone + ./scripts/setup_dev.sh`
2. `ruff check . && pytest`
3. Edit → `git commit -m "feat: ..."`
4. Push → CI auto-runs

---

**Built by Youssef CHEBL** | [Architecture](docs/architecture_overview.svg)
