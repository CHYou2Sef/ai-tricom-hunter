# 🤖 AI Phone Hunter — Industrial B2B Autonomous Agent

High-performance asynchronous agent for automated company data enrichment. Designed for **24/7 autonomous operation** on Windows, macOS, and Linux with a fully resilient multi-tier browser waterfall engine.

---

## 🏛️ The 4-Pillar Architecture

This project is built on a highly portable, cross-platform architecture:
1. **Environment:** Powered by `uv` for lightning-fast, deterministic dependency resolution.
2. **Containerization:** Deployed via Docker with an embedded `Xvfb` display server to maintain browser stealth in headless environments without memory leakages from VNCs.
3. **Agent Definition:** Built on the `open-gitagent` standard (`agent.yaml`, `SOUL.md`, `RULES.md`) so agent behaviors are declarative and framework-agnostic.
4. **Continuous Delivery:** GitHub Actions CI/CD automatically lints, validates agent logic, and builds container images dynamically.

---

## ⚡ Quick Start

### Option A: Effortless Windows Target Deployment (Recommended)
The production target requires absolutely ZERO setups. No Python, no Node.js, no environments. Just Docker.

1. Ensure Docker Desktop is installed.
2. Put your `.env` in the root folder alongside `docker-compose.yml`.
3. Open terminal/PowerShell and run:
```bash
docker compose up -d
```
The agent starts in the background and watches your `WORK/INCOMING/` folder.

### Option B: Local Developer setup (Linux/macOS)
If you wish to develop and test locally, use the one-shot dev script.
*100% Native Python. Zero Node.js required.*

```bash
# Installs uv, python requirements, and stealth browsers
bash scripts/setup_dev.sh
```

---

## 🛡️ Agent Validation Operations

To modify the AI's core behavior, edit `SOUL.md` or `RULES.md`. After any edits, validate the logic to prevent pipeline crashes:
```bash
python scripts/validator.py
```

---

## 🎮 Running the Agent (Locally)

If not using Docker, the pipeline runs in two decoupled stages:

**Stage 1 — Pre-processor** (watches for new files in `WORK/INCOMING/`):
```bash
python pre_process.py
```

**Stage 2 — Main Agent** (browses & enriches data autonomously):
```bash
python main.py
```

---

## 🧪 Architecture Testing

To verify the Docker container, GitAgent validation, and test suite on your local development machine:

```bash
bash scripts/test_architecture.sh
```

---

## 🔬 Engine Benchmark Arena

Before deploying a configuration for production, run the **standalone benchmark** to determine the superior engine for your environment. 

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

---

## 📂 Project Structure

```
ai_phone_hunter/
├── agent.yaml               ← GitAgent definition
├── SOUL.md                  ← Agent Personality/Role
├── RULES.md                 ← Hard Constraints
├── Dockerfile               ← Multi-stage container recipe
├── requirements-prod.txt    ← Production dependencies
├── main.py                  ← Orchestrator entry
├── config.py                ← Master settings
├── agents/                  ← Specialized agents
├── browser/                 ← Browser engines
│   ├── hybrid_engine.py     ← Multi-tier router
│   ├── selenium_agent.py    
│   ├── patchright_agent.py  
│   └── nodriver_agent.py    
├── scripts/
│   ├── benchmark_engines.py
│   ├── setup_dev.sh         ← Dev environment bootstrapper
│   ├── entrypoint.sh        ← Docker entrypoint (Xvfb)
│   └── test_architecture.sh ← Validation suite
└── WORK/                    ← Runtime data (gitignored)
```
