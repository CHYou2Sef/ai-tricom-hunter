#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════╗
║  scripts/benchmark_engines.py                                            ║
║                                                                          ║
║  STANDALONE BENCHMARK ARENA — Multi-Engine Continuity Stress Test        ║
║                                                                          ║
║  Feeds the same 1000-line dataset to each browser engine independently   ║
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
║                    --engines selenium patchright nodriver                ║
║    python scripts/benchmark_engines.py --input WORK/INCOMING/your.xlsx   ║
║                    --rows 100  --engines selenium                         ║
║                                                                          ║
║  Available engine names:                                                 ║
║    selenium   →  Selenium 4 + undetected-chromedriver (new)              ║
║    patchright →  Patchright stealth Chromium (Tier 1)                   ║
║    nodriver   →  Nodriver UC-Mode CDP stealth (Tier 2)                  ║
║    crawl4ai   →  Crawl4AI managed scraper (Tier 3)                      ║
║    camoufox   →  Camoufox patched Firefox (Tier 4, heavy)               ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import sys
import asyncio
import argparse
import time
from pathlib import Path
from typing import List, Optional

# ── Ensure project root is on sys.path ────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config
from excel.reader import ExcelRow, read_excel
from utils.metrics import BenchmarkTelemetry
from utils.logger import get_logger

logger = get_logger("benchmark")

# ── Engine registry — maps CLI name → lazy import factory ─────────────────
ENGINE_REGISTRY = {
    "selenium":   lambda: _import("browser.selenium_agent",   "SeleniumAgent"),
    "patchright": lambda: _import("browser.patchright_agent", "PatchrightAgent"),
    "nodriver":   lambda: _import("browser.nodriver_agent",   "NodriverAgent"),
    "crawl4ai":   lambda: _import("browser.crawl4ai_agent",   "Crawl4AIAgent"),
    "camoufox":   lambda: _import("browser.camoufox_agent",   "CamoufoxAgent"),
}
DEFAULT_ENGINES = ["selenium", "patchright", "nodriver"]


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
        help="Path to the Excel/CSV input file (1000 lines recommended).",
    )
    parser.add_argument(
        "--engines", nargs="+", default=DEFAULT_ENGINES,
        choices=list(ENGINE_REGISTRY.keys()),
        help=f"Engines to benchmark. Default: {DEFAULT_ENGINES}",
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

    logger.info(f"\n{'═'*60}")
    logger.info(f"🚀  BENCHMARKING: {engine_name.upper()}  ({len(rows)} rows)")
    logger.info(f"{'═'*60}")

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
            nom = row.nom or row.siren or ""
            adr = row.adresse or ""
            prompt = config.AI_MODE_SEARCH_PROMPT.format(nom=nom, adresse=adr)

            # Primary search
            result = await agent.search_google_ai_mode(prompt)

            # Detect interruption signal from the agent (set by _record_interruption)
            if hasattr(agent, "last_interruption_reason") and agent.last_interruption_reason:
                interruption_reason = agent.last_interruption_reason
                agent.last_interruption_reason = None  # reset after consuming

            if result:
                # Quick phone check without full enrichment
                from search.phone_extractor import extract_phones
                phones = extract_phones(result)
                row.phone = phones[0] if phones else None

            status = "DONE" if row.phone else "NO TEL"

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
        telemetry.record(engine_name, i, status, latency, interruption_reason)

        # Progress heartbeat every 25 rows
        if i % 25 == 0 or i == len(rows):
            stats = telemetry._engines[engine_name].compute()
            logger.info(
                f"  [{engine_name}] Row {start_idx + i}/{start_idx + len(rows)}  |  "
                f"DONE={stats['rows_done']}  NO_TEL={stats['rows_no_tel']}  "
                f"ERR={stats['rows_error']}  |  MTTI={stats['mtti_sec']}s"
            )

        # Human-like delay between rows (mirrors production behaviour)
        import random
        await asyncio.sleep(random.uniform(config.MIN_DELAY_SECONDS, config.MAX_DELAY_SECONDS))
        
        # Save row-level checkpoint (adding the start offset)
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
