#!/usr/bin/env python3
"""
╔════════════════════════════════════════════════════════════════════════╗
║  scripts/benchmark_engines.py                                            ║
║                                                                          ║
║  STANDALONE BENCHMARK ARENA — Multi-Engine Continuity Stress Test        ║
║                                                                          ║
║  Feeds the same dataset to each browser engine independently              ║
║  (one engine at a time, no hybrid fallback). Measures per-engine:        ║
║                                                                          ║
║    ✓ MTTI   — Mean Time To Interruption (primary continuity KPI)         ║
║    ✓ Success Rate (DONE vs NO TEL)                                       ║
║    ✓ Average row latency                                                 ║
║    ✓ CAPTCHA blocks / IP bans / exceptions count                         ║
║    ✓ Total throughput time                                               ║
║                                                                          ║
║  Output:                                                                 ║
║    • Console — formatted ranking report                                  ║
║    • WORK/telemetry.json — machine-readable payload                      ║
║                                                                          ║
║  Usage:                                                                  ║
║    python scripts/benchmark_engines.py --input WORK/INCOMING/your.xlsx   ║
║    python scripts/benchmark_engines.py --input WORK/INCOMING/your.xlsx   ║
║                    --engines seleniumbase patchright nodriver            ║
║    python scripts/benchmark_engines.py --input WORK/INCOMING/your.xlsx   ║
║                    --rows 50  --engines seleniumbase                     ║
║                                                                          ║
║  Available engine names (sorted by tier):                                ║
║    seleniumbase →  SeleniumBase UC Driver  (⭐ Tier 1 — PRIMARY)          ║
║    selenium     →  Selenium 4 + undetected-chromedriver (Tier 0 legacy)  ║
║    patchright   →  Patchright stealth Chromium (Tier 2)                 ║
║    nodriver     →  Nodriver UC-Mode CDP stealth (Tier 3)                ║
║    crawl4ai     →  Crawl4AI managed scraper (Tier 4)                    ║
║    camoufox     →  Camoufox patched Firefox (Tier 5, heavy)             ║
╚════════════════════════════════════════════════════════════════════════╝
"""

import sys
import asyncio
import argparse
import time
from pathlib import Path
from typing import List, Optional

# ── Ensure src/ is on sys.path (current project layout) ────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from core import config
from core.logger import get_logger
from domain.excel.reader import ExcelRow, read_excel
from common.metrics import BenchmarkTelemetry

logger = get_logger("benchmark")

# ── Lightweight telemetry helpers (graceful if BenchmarkTelemetry API differs) ─────

def _record(engine: str, row_idx: int, status: str, latency: float,
            interruption: str | None, telemetry) -> None:
    """Route a row result to telemetry, tolerating different API versions."""
    try:
        telemetry.record(engine, row_idx, status, latency, interruption)
    except TypeError:
        try:
            telemetry.record(engine, row_idx, status, latency)
        except Exception:
            pass


def _record_error(engine: str, row_idx: int, telemetry) -> None:
    _record(engine, row_idx, "ERROR", 0.0, "startup_failure", telemetry)

# ── Engine registry — maps CLI name → lazy import factory ────────────────────
ENGINE_REGISTRY = {
    # ⭐ Tier 1: PRIMARY benchmark target (docs/Gemini.md)
    "seleniumbase": lambda: _import("infra.browsers.seleniumbase_agent", "SeleniumBaseAgent"),
    # Tier 0: Legacy undetected-chromedriver (kept for baseline comparison)
    "selenium":     lambda: _import("infra.browsers.selenium_agent",     "SeleniumAgent"),
    # Tier 2–5: existing agents
    "patchright":   lambda: _import("infra.browsers.patchright_agent",   "PatchrightAgent"),
    "nodriver":     lambda: _import("infra.browsers.nodriver_agent",     "NodriverAgent"),
    "crawl4ai":     lambda: _import("infra.browsers.crawl4ai_agent",     "Crawl4AIAgent"),
    "camoufox":     lambda: _import("infra.browsers.camoufox_agent",     "CamoufoxAgent"),
}
# Default: run SeleniumBase first, then Patchright and Nodriver for comparison
DEFAULT_ENGINES = ["seleniumbase", "patchright", "nodriver"]


def _import(module_path: str, class_name: str):
    """Lazy import helper — avoids loading unavailable optional deps at startup."""
    import importlib
    mod = importlib.import_module(module_path)
    return getattr(mod, class_name)


# ── CLI ────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="AI Phone Hunter — Engine Benchmark Arena",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--input", required=True,
        help="Path to the Excel/CSV input file (50–1000 rows recommended).",
    )
    parser.add_argument(
        "--engines", nargs="+", default=DEFAULT_ENGINES,
        choices=list(ENGINE_REGISTRY.keys()),
        help=(
            f"Engines to benchmark. Default: {DEFAULT_ENGINES}. "
        ),
    )
    parser.add_argument(
        "--rows", type=int, default=1000,
        help="Maximum number of rows to process per engine. Default: 1000.",
    )
    parser.add_argument(
        "--search-only", action="store_true",
        help="Run only the AI Mode search step (skip enrichment). Faster for raw engine comparison.",
    )
    return parser.parse_args()


# ── Per-engine runner ─────────────────────────────────────────────────────

async def run_engine_benchmark(
    engine_name: str,
    rows: List[ExcelRow],
    telemetry: BenchmarkTelemetry,
    search_only: bool = False,
    start_idx: int = 0,
) -> None:
    """
    Execute the full search pipeline on `rows` using a single agent instance.
    No hybrid fallback — pure single-engine isolation for accurate telemetry.
    """
    AgentClass = ENGINE_REGISTRY[engine_name]()
    agent = AgentClass(worker_id=0)

    tier_label = {
        "seleniumbase": "⭐ Tier 1 (SeleniumBase UC)",
        "selenium":     "Tier 0 (SeleniumUCD legacy)",
        "patchright":   "Tier 2 (Patchright)",
        "nodriver":     "Tier 3 (Nodriver)",
        "crawl4ai":     "Tier 4 (Crawl4AI)",
        "camoufox":     "Tier 5 (Camoufox)",
    }.get(engine_name, engine_name)

    logger.info(f"\n{'\u2550'*64}")
    logger.info(f"🚀  BENCHMARKING: {engine_name.upper()}  [{tier_label}]  ({len(rows)} rows)")
    logger.info(f"{'\u2550'*64}")

    try:
        await agent.start()
    except Exception as exc:
        logger.error(f"[{engine_name}] ❌  Failed to start browser: {exc}")
        telemetry.record(engine_name, 0, "ERROR", 0.0, "startup_failure")
        return

    for i, row in enumerate(rows, 1):
        row_start = time.perf_counter()
        status = "ERROR"
        interruption_reason: Optional[str] = None

        try:
            nom, adr = (row.nom or row.siren or ""), (row.adresse or "")
            siren = getattr(row, "siren", "NOT_PROVIDED")
            category = getattr(row, "category", "NOT_PROVIDED")
            extra = getattr(row, "raw_context", "")[:200]
            
            prompt = config.AI_MODE_SEARCH_PROMPT.format(
                nom=nom, adresse=adr, siren=siren, category=category, extra=extra
            )

            # ── 1. Standard AI Search ─────────────────────────────────────
            result = await agent.search_google_ai_mode(prompt)
            from domain.search.phone_extractor import extract_phones
            phones = extract_phones(result if result else "", source_label=engine_name)
            phone = phones[0] if phones else None

            # ── 2. Expert AI Retry (Waterfall) ──────────────────────────
            if not phone:
                logger.info(f"🔄 [{engine_name.upper()}] No phone in standard mode. Retrying with EXPERT prompt...")
                expert_prompt = config.AI_MODE_EXPERT_PROMPT.format(
                    nom=nom, adresse=adr, siren=siren, category=category, extra=extra
                )
                result = await agent.search_google_ai_mode(expert_prompt)
                phones = extract_phones(result if result else "", source_label=f"{engine_name}_expert")
                phone = phones[0] if phones else None

            # Detect interruption signal from the agent (set by _record_interruption)
            if hasattr(agent, "last_interruption_reason") and agent.last_interruption_reason:
                interruption_reason = agent.last_interruption_reason
                agent.last_interruption_reason = None  # reset after consuming

            if phone:
                logger.info(f"🏆 [{engine_name.upper()}] Row {i}/{len(rows)} HARVESTED: {phone}")

            status = "DONE" if (result and phone) else "NO TEL"

        except asyncio.CancelledError:
            logger.warning(f"[{engine_name}] Row #{i} was cancelled.")
            status = "ERROR"
            interruption_reason = "cancelled"
            break
        except Exception as exc:
            logger.error(f"[{engine_name}] Row #{i} exception: {exc}")
            status = "ERROR"
            interruption_reason = "exception"

        latency = time.perf_counter() - row_start
        row.status = status # CRITICAL: Update the object so summary counting works
        _record(engine_name, i, status, latency, interruption_reason, telemetry)

        # Progress heartbeat every 25 rows
        if i % 25 == 0 or i == len(rows):
            done   = sum(1 for r in rows[:i] if getattr(r, "status", "") == "DONE")
            no_tel = sum(1 for r in rows[:i] if getattr(r, "status", "") == "NO TEL")
            errs   = i - done - no_tel
            logger.info(
                f"  [{engine_name}] Row {start_idx + i}/{start_idx + len(rows)}  |  "
                f"DONE={done}  NO_TEL={no_tel}  ERR={errs}  |  lat={latency:.1f}s"
            )

        # Human-like inter-row delay (mirrors production behaviour)
        import random
        await asyncio.sleep(random.uniform(config.MIN_DELAY_SECONDS, config.MAX_DELAY_SECONDS))

        save_checkpoint(engine_name, start_idx + i)

    try:
        await agent.close()
    except Exception:
        pass

    logger.info(f"✅  {engine_name.upper()} benchmark complete.")


# ── Main entrypoint ────────────────────────────────────────────────────────

async def main() -> None:
    args = parse_args()
    input_path = Path(args.input).resolve()

    if not input_path.exists():
        logger.error(f"❌  Input file not found: {input_path}")
        sys.exit(1)

    logger.info(f"📂  Loading dataset: {input_path}")
    rows, _ = await asyncio.to_thread(read_excel, str(input_path))

    if not rows:
        logger.error("❌  No rows loaded from input file. Aborting.")
        sys.exit(1)

    # Cap rows per engine
    rows_to_process = rows[:args.rows]
    logger.info(
        f"📊  {len(rows_to_process)} rows loaded  |  "
        f"Engines to test: {args.engines}"
    )

    # Cumulative telemetry (loads existing results from WORK/telemetry.json)
    telemetry = BenchmarkTelemetry()
    for name in args.engines:
        telemetry.register_engine(name)
    
    logger.info("📈  Cumulative results tracking active. Previous data preserved.")

    # Run each engine independently and sequentially
    for engine_name in args.engines:
        if engine_name not in ENGINE_REGISTRY:
            logger.warning(f"⚠️  Unknown engine '{engine_name}' — skipping.")
            continue

        # Reset row state between engines so each gets a clean slate
        for row in rows_to_process:
            row.phone = None
            row.status = "PENDING"

        # Check if engine is already fully done in checkpoint
        checkpoint = load_checkpoint()
        last_row = checkpoint.get(engine_name, 0)
        
        if last_row >= len(rows_to_process):
            logger.info(f"⏭️   Engine '{engine_name}' already completed in previous run. Skipping.")
            continue

        await run_engine_benchmark(
            engine_name=engine_name,
            rows=rows_to_process[last_row:], # Start from where we left off
            telemetry=telemetry,
            search_only=args.search_only,
            start_idx=last_row,
        )

        # Save results for this engine
        telemetry.finalize()

        # Cooldown between engines
        logger.info("⏸️   Cooling down 30s before next engine...")
        await asyncio.sleep(30)

    # All engines complete
    logger.info("🏁  All benchmarks finished.")
    # Clear checkpoint on full success
    checkpoint_path = Path(config.WORK_DIR) / "benchmark_checkpoint.json"
    if checkpoint_path.exists():
        checkpoint_path.unlink()


def load_checkpoint() -> dict:
    path = Path(config.WORK_DIR) / "benchmark_checkpoint.json"
    if path.exists():
        try:
            import json
            return json.loads(path.read_text())
        except:
            return {}
    return {}


def save_checkpoint(engine: str, row_idx: int):
    path = Path(config.WORK_DIR) / "benchmark_checkpoint.json"
    import json
    data = load_checkpoint()
    data[engine] = row_idx
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, asyncio.exceptions.CancelledError):
        # Suppress Noise: Python 3.12+ raised CancelledError then KeyboardInterrupt
        print("\n" + "═" * 60)
        print("🛑  Benchmark stopped by user.")
        print("═" * 60 + "\n")
        import sys
        sys.exit(0)
