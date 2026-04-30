#!/usr/bin/env python3
"""
╔════════════════════════════════════════════════════════════════════════╗
║  scripts/benchmark_engines.py                                          ║
║                                                                        ║
║  STANDALONE BENCHMARK ARENA — Multi-Tier Continuity Stress Test        ║
║                                                                        ║
║  Feeds the same dataset to each tier independently (no hybrid          ║
║  fallback). Produces:                                                  ║
║                                                                        ║
║    • WORK/benchmarks/tier_{name}.json   — per-tier result detail       ║
║    • WORK/benchmarks/final_summary.json — cross-tier ranking & KPIs   ║
║    • WORK/telemetry.json                — live machine-readable payload ║
║                                                                        ║
║  Usage:                                                                ║
║    python scripts/benchmark_engines.py --input WORK/INCOMING/your.xlsx ║
║    python scripts/benchmark_engines.py --input WORK/INCOMING/your.xlsx ║
║                    --engines scrapy seleniumbase nodriver              ║
║    python scripts/benchmark_engines.py --input WORK/INCOMING/your.xlsx ║
║                    --rows 50 --engines scrapy seleniumbase             ║
║                                                                        ║
║  Available tiers (sorted):                                             ║
║    seleniumbase →  SeleniumBase UC Driver      (⭐ Tier 2 — PRIMARY)   ║
║    botasaurus   →  Botasaurus anti-detect      (Tier 3)               ║
║    patchright   →  Patchright stealth Chromium (Tier 4)               ║
║    nodriver     →  Nodriver UC-Mode CDP        (Tier 5)               ║
║    crawl4ai     →  Crawl4AI managed scraper    (Tier 6)               ║
║    camoufox     →  Camoufox patched Firefox    (Tier 7, heavy)        ║
║    firecrawl    →  Firecrawl premium API       (Tier 8)               ║
║    jina         →  Jina Reader fast markdown   (Tier 9)               ║
║    crawlee      →  Crawlee adaptive Playwright (Tier 10)              ║
║    selenium     →  Selenium + undetected-cd    (Tier 0 legacy baseline)║
║                                                                        ║
║  NOTE: Scrapy is no longer a tier. It runs as a global 'bonus' step    ║
║  inside every browser tier during the extraction phase.                ║
╚════════════════════════════════════════════════════════════════════════╝
"""

import sys
import json
import asyncio
import argparse
import time
import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any

# ── Ensure src/ is on sys.path ───────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from core import config
from core.logger import get_logger
from domain.excel.reader import ExcelRow, read_excel
from common.metrics import BenchmarkTelemetry
from domain.search.phone_extractor import extract_phones

logger = get_logger("benchmark")

# ── Output directory for per-tier + final JSON files ─────────────────────────
BENCH_DIR: Path = config.WORK_DIR / "benchmarks"

# ── Tier label map ────────────────────────────────────────────────────────────
TIER_LABELS: Dict[str, str] = {
    "seleniumbase":  "⭐ Tier 2 — SeleniumBase UC (PRIMARY)",
    "botasaurus":    "Tier 3 — Botasaurus Anti-Detect",
    "patchright":    "Tier 4 — Patchright Stealth",
    "nodriver":      "Tier 5 — Nodriver CDP",
    "crawl4ai":      "Tier 6 — Crawl4AI Managed",
    "camoufox":      "Tier 7 — Camoufox Firefox",
    "firecrawl":     "Tier 8 — Firecrawl Premium",
    "jina":          "Tier 9 — Jina Reader",
    "crawlee":       "Tier 10 — Crawlee Adaptive Playwright",
    "selenium":      "Tier 0 — Selenium (legacy baseline)",
}


# ── Lazy import helper ────────────────────────────────────────────────────────

def _import(module_path: str, class_name: str):
    import importlib
    mod = importlib.import_module(module_path)
    return getattr(mod, class_name)




# ── Engine registry ───────────────────────────────────────────────────────────

ENGINE_REGISTRY = {
    "seleniumbase": lambda: _import("infra.browsers.seleniumbase_agent", "SeleniumBaseAgent"),
    "botasaurus":   lambda: _import("infra.browsers.botasaurus_agent",   "BotasaurusAgent"),
    "patchright":   lambda: _import("infra.browsers.patchright_agent",   "PatchrightAgent"),
    "nodriver":     lambda: _import("infra.browsers.nodriver_agent",     "NodriverAgent"),
    "crawl4ai":     lambda: _import("infra.browsers.crawl4ai_agent",     "Crawl4AIAgent"),
    "camoufox":     lambda: _import("infra.browsers.camoufox_agent",     "CamoufoxAgent"),
    "firecrawl":    lambda: _import("infra.browsers.firecrawl_agent",    "FirecrawlAgent"),
    "jina":         lambda: _import("infra.browsers.jina_agent",         "JinaAgent"),
    "crawlee":      lambda: _import("infra.browsers.crawlee_agent",      "CrawleeAgent"),
    "selenium":     lambda: _import("infra.browsers.selenium_agent",     "SeleniumAgent"),
}

DEFAULT_ENGINES = ["seleniumbase", "nodriver", "botasaurus"]


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="AI Phone Hunter — Multi-Tier Benchmark Arena",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--input", required=True,
                        help="Path to the Excel/CSV input file.")
    parser.add_argument("--engines", nargs="+", default=DEFAULT_ENGINES,
                        choices=list(ENGINE_REGISTRY.keys()),
                        help=f"Tiers to benchmark. Default: {DEFAULT_ENGINES}.")
    parser.add_argument("--rows", type=int, default=1000,
                        help="Max rows per tier. Default: 1000.")
    parser.add_argument("--search-only", action="store_true",
                        help="Skip direct-URL scraping step (AI Mode search only).")
    parser.add_argument("--no-delay", action="store_true",
                        help="Remove inter-row delay (faster but detectable). For CI only.")
    parser.add_argument("--skip-preflight", action="store_true",
                        help="Skip the pre-flight health check and start immediately.")
    parser.add_argument("--fail-fast", action="store_true",
                        help="Abort if ANY tier fails the preflight check (default: skip unavailable tiers).")
    return parser.parse_args()


# ── Telemetry helpers ─────────────────────────────────────────────────────────

def _record(engine: str, row_idx: int, status: str, latency: float,
            interruption: Optional[str], telemetry: BenchmarkTelemetry) -> None:
    try:
        telemetry.record(engine, row_idx, status, latency, interruption)
    except TypeError:
        try:
            telemetry.record(engine, row_idx, status, latency)
        except Exception:
            pass


# ── Preflight Health Check ────────────────────────────────────────────────────

async def preflight_check(engines: List[str], fail_fast: bool = False) -> List[str]:
    """
    3-stage health check for every requested tier BEFORE the benchmark starts.

    Stage 1 — Import:        Can the module + class be imported?
    Stage 2 — Instantiation: Can the agent be created (worker_id=0)?
    Stage 3 — Smoke test:    Can agent.start() and agent.close() complete
                             without raising within 10 s?

    Returns the list of engines that PASSED all 3 stages.
    If fail_fast=True, raises SystemExit on the first failure.
    """
    _W  = "\033[93m"   # yellow
    _G  = "\033[92m"   # green
    _R  = "\033[91m"   # red
    _B  = "\033[96m"   # cyan
    _RST = "\033[0m"

    print("\n" + "═" * 64)
    print(f"{_B}🔬  PRE-FLIGHT HEALTH CHECK — {len(engines)} tier(s){_RST}")
    print("═" * 64)

    passed: List[str] = []
    failed: List[str] = []
    results: Dict[str, Dict[str, Any]] = {}

    for name in engines:
        label = TIER_LABELS.get(name, name)
        result: Dict[str, Any] = {"stage": "", "error": ""}

        # ── Stage 1: Import ───────────────────────────────────────────────
        try:
            AgentClass = ENGINE_REGISTRY[name]()
            result["stage"] = "import ✓"
        except ImportError as exc:
            result["stage"] = "import"
            result["error"] = f"Missing dependency: {exc}"
            results[name] = result
            failed.append(name)
            _print_row(name, label, "FAIL", result["error"], _R, _RST)
            if fail_fast:
                print(f"{_R}\n❌  --fail-fast: aborting on first failure.{_RST}")
                sys.exit(1)
            continue
        except Exception as exc:
            result["stage"] = "import"
            result["error"] = str(exc)
            results[name] = result
            failed.append(name)
            _print_row(name, label, "FAIL", result["error"], _R, _RST)
            if fail_fast:
                sys.exit(1)
            continue

        # ── Stage 2: Instantiation ────────────────────────────────────────
        try:
            agent = AgentClass(worker_id=0)
            result["stage"] = "instantiate ✓"
        except Exception as exc:
            result["stage"] = "instantiate"
            result["error"] = str(exc)
            results[name] = result
            failed.append(name)
            _print_row(name, label, "FAIL", result["error"], _R, _RST)
            if fail_fast:
                sys.exit(1)
            continue

        # ── Stage 3: Smoke test (start + close) ───────────────────────────
        try:
            await asyncio.wait_for(agent.start(), timeout=15.0)
            await asyncio.wait_for(agent.close(), timeout=10.0)
            result["stage"] = "smoke ✓"
            result["error"] = ""
            passed.append(name)
            _print_row(name, label, "PASS", "", _G, _RST)
        except asyncio.TimeoutError:
            result["stage"] = "smoke"
            result["error"] = "Timeout during start()/close() — browser may be missing"
            # Try to clean up
            try:
                await asyncio.wait_for(agent.close(), timeout=5.0)
            except Exception:
                pass
            failed.append(name)
            _print_row(name, label, "WARN", result["error"], _W, _RST)
            if fail_fast:
                sys.exit(1)
        except Exception as exc:
            result["stage"] = "smoke"
            result["error"] = str(exc)[:120]
            try:
                await asyncio.wait_for(agent.close(), timeout=5.0)
            except Exception:
                pass
            failed.append(name)
            _print_row(name, label, "FAIL", result["error"], _R, _RST)
            if fail_fast:
                sys.exit(1)

        results[name] = result

    # ── Summary table ─────────────────────────────────────────────────────
    print("─" * 64)
    print(f"  {_G}✅ READY   : {len(passed)} tier(s) → {passed}{_RST}")
    if failed:
        print(f"  {_W}⚠️  SKIPPED : {len(failed)} tier(s) → {failed}{_RST}")
        print(f"  {_W}   These tiers will be excluded from the benchmark.{_RST}")
    print("═" * 64 + "\n")

    if not passed:
        print(f"{_R}❌  No tiers passed preflight. Cannot run benchmark.{_RST}")
        sys.exit(1)

    return passed


def _print_row(name: str, label: str, status: str, error: str,
               color: str, reset: str) -> None:
    """Print a single preflight result row to console."""
    icon = {"PASS": "✅", "FAIL": "❌", "WARN": "⚠️ "}.get(status, "❓")
    line = f"  {icon} [{status:4}]  {name:<14} {label}"
    if error:
        line += f"\n          └─ {error}"
    print(f"{color}{line}{reset}")


# ── Per-tier JSON persistence ─────────────────────────────────────────────────

def save_tier_json(engine_name: str, rows: List[ExcelRow], tier_stats: Dict[str, Any]) -> Path:
    """
    Write a detailed per-tier result file to WORK/benchmarks/tier_{name}.json.
    Includes row-level detail + aggregate KPIs.
    """
    BENCH_DIR.mkdir(parents=True, exist_ok=True)
    out_path = BENCH_DIR / f"tier_{engine_name}.json"

    row_details = []
    for row in rows:
        row_details.append({
            "row_index": row.row_index,
            "nom": row.nom or "",
            "adresse": row.adresse or "",
            "siren": row.siren or "",
            "status": getattr(row, "status", "UNKNOWN"),
            "phone_found": row.phone or "",
        })

    payload = {
        "tier": engine_name,
        "label": TIER_LABELS.get(engine_name, engine_name),
        "generated_at": datetime.datetime.now().isoformat(),
        "input_file": tier_stats.get("input_file", ""),
        "kpis": {
            "rows_attempted":    tier_stats.get("rows_attempted", 0),
            "rows_done":         tier_stats.get("rows_done", 0),
            "rows_no_tel":       tier_stats.get("rows_no_tel", 0),
            "rows_error":        tier_stats.get("rows_error", 0),
            "success_rate_pct":  tier_stats.get("success_rate_pct", 0.0),
            "avg_latency_sec":   tier_stats.get("avg_latency_sec", 0.0),
            "total_session_sec": tier_stats.get("total_session_sec", 0.0),
            "mtti_sec":          tier_stats.get("mtti_sec", 0.0),
            "captcha_blocks":    tier_stats.get("captcha_blocks", 0),
            "ip_ban_blocks":     tier_stats.get("ip_ban_blocks", 0),
            "interruptions_total": tier_stats.get("interruptions_total", 0),
        },
        "row_details": row_details,
        "interruption_log": tier_stats.get("interruption_log", []),
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    logger.info(f"[Benchmark] 💾 Tier result saved: {out_path}")
    return out_path


def save_final_summary(engines: List[str], telemetry_payload: Dict[str, Any],
                       input_file: str) -> Path:
    """
    Write the cross-tier ranking + KPI comparison to
    WORK/benchmarks/final_summary.json.
    """
    BENCH_DIR.mkdir(parents=True, exist_ok=True)
    out_path = BENCH_DIR / "final_summary.json"

    summary = {
        "generated_at": datetime.datetime.now().isoformat(),
        "input_file": input_file,
        "engines_tested": engines,
        "benchmark_runtime_sec": telemetry_payload.get("benchmark_runtime_sec", 0),
        "ranking": telemetry_payload.get("ranking", []),
        "engines": telemetry_payload.get("engines", []),
        "tier_json_files": [str(BENCH_DIR / f"tier_{e}.json") for e in engines],
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    logger.info(f"[Benchmark] 🏁 Final summary saved: {out_path}")
    return out_path


# ── Checkpoint helpers ────────────────────────────────────────────────────────

def load_checkpoint() -> dict:
    path = config.WORK_DIR / "benchmark_checkpoint.json"
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            return {}
    return {}


def save_checkpoint(engine: str, row_idx: int) -> None:
    path = config.WORK_DIR / "benchmark_checkpoint.json"
    data = load_checkpoint()
    data[engine] = row_idx
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


# ── Core phone extraction helper ──────────────────────────────────────────────

async def _extract_phone_for_row(
    agent,
    engine_name: str,
    row: "ExcelRow",
    is_scrapy: bool,
    search_only: bool,
) -> Optional[str]:
    """
    Attempt phone extraction for a single row using one agent/tier.
    Mirrors the production phone_hunter pipeline:

      1. [Scrapy]   Direct HTTP scrape of company website (if URL known)
      2. [Browser]  Google AI Mode — Standard prompt → JSON parse
      3. [Browser]  Google AI Mode — Expert prompt (retry if step 2 fails)
      4. [Both]     Regex fallback on raw text
      5.            normalize_phone() + NULL_VALUE_STRINGS filter

    Returns the first valid phone string, or None.
    """
    from domain.search.phone_extractor import extract_phones, normalize_phone
    import re as _re

    _null_upper = {s.upper() for s in config.NULL_VALUE_STRINGS}

    nom      = row.nom or row.siren or ""
    adr      = row.adresse or ""
    siren    = getattr(row, "siren", "") or ""
    category = getattr(row, "category", "") or ""
    extra    = getattr(row, "raw_context", "")[:200]

    def _pick_phone_from_json(data: dict) -> Optional[str]:
        """Extract and normalize the best phone from a parsed JSON dict."""
        candidates = []
        # Try standard phone fields
        for key in ("phone_numbers", "telephone", "phone",
                    "director_direct_phone", "tel_direct"):
            val = data.get(key)
            if isinstance(val, list):
                candidates.extend([str(v) for v in val if v])
            elif isinstance(val, str) and val.strip():
                candidates.append(val.strip())
        for raw in candidates:
            if raw.upper() in _null_upper:
                continue
            normed = normalize_phone(raw)
            if normed:
                return normed
        return None

    def _pick_phone_from_text(text: str, label: str) -> Optional[str]:
        """Regex extraction on plain text as a last resort."""
        phones = extract_phones(text, source_label=label)
        for p in phones:
            if str(p).upper() not in _null_upper:
                n = normalize_phone(p)
                if n:
                    return n
        return None

    def _parse_json_safe(text: str) -> Optional[dict]:
        """Try to parse JSON from AI Mode response (handles markdown code blocks)."""
        if not text:
            return None
        # Strip markdown ```json ... ``` wrapper
        clean = _re.sub(r"```(?:json)?\s*", "", text).replace("```", "").strip()
        # Find first { ... } block
        m = _re.search(r"\{.*\}", clean, _re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
        return None

    # Helper: Extract website from AI Mode result
    def _extract_website(text: str) -> Optional[str]:
        if not text: return None
        # Try JSON parse
        m = _re.search(r'\{.*\}', text, _re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(0))
                u = data.get("website") or data.get("site_web") or data.get("url")
                if u and u.startswith("http"): return u
            except: pass
        # Regex fallback
        m2 = _re.search(r'https?://[^\s"\'>]+', text)
        return m2.group(0) if m2 else None

    # Helper: Run Scrapy bonus
    async def _run_scrapy_bonus(website: str) -> Optional[str]:
        try:
            from infra.scrapers.agent_scraper import run_ai_spider
            data = await asyncio.wait_for(run_ai_spider(website), timeout=12.0)
            raw_p = data.get("phone") or data.get("telephone")
            if raw_p and raw_p.upper() not in _null_upper:
                return normalize_phone(raw_p)
        except: pass
        return None

    # ══ PATH A: DEPRECATED — Scrapy no longer a standalone tier ══════════════
    if is_scrapy:
        return None # Should not happen with new ENGINE_REGISTRY

    # ══ PATH B: Browser tiers — Google AI Mode ════════════════════════════════

    # Step 1 — Standard prompt
    prompt = config.AI_MODE_SEARCH_PROMPT.format(
        nom=nom, adresse=adr, siren=siren, category=category, extra=extra
    )
    raw_result = await agent.search_google_ai_mode(prompt)

    if raw_result:
        parsed = _parse_json_safe(raw_result)
        if parsed:
            phone = _pick_phone_from_json(parsed)
            if phone: return phone
        
        # Scrapy Bonus Step (if website found but no phone)
        if not search_only:
            website = _extract_website(raw_result)
            if website:
                phone = await _run_scrapy_bonus(website)
                if phone: return phone

        # Regex fallback on raw text
        phone = _pick_phone_from_text(raw_result, engine_name)
        if phone: return phone

    # Step 2 — Expert retry prompt
    expert_prompt = config.AI_MODE_EXPERT_PROMPT.format(
        nom=nom, adresse=adr, siren=siren, category=category, extra=extra
    )
    raw_expert = await agent.search_google_ai_mode(expert_prompt)

    if raw_expert:
        parsed = _parse_json_safe(raw_expert)
        if parsed:
            phone = _pick_phone_from_json(parsed)
            if phone: return phone
        
        # Scrapy Bonus Step on Expert Result
        if not search_only:
            website = _extract_website(raw_expert)
            if website:
                phone = await _run_scrapy_bonus(website)
                if phone: return phone

        phone = _pick_phone_from_text(raw_expert, f"{engine_name}_expert")
        if phone: return phone

    # Step 3 — Website crawl (if not search_only and agent supports crawl_website)
    if not search_only and hasattr(agent, "crawl_website"):
        website = getattr(row, "website", None) or _extract_website(raw_result) or _extract_website(raw_expert)
        if website:
            if not website.startswith("http"): website = "https://" + website
            try:
                crawl_text = await asyncio.wait_for(agent.crawl_website(website), timeout=20.0)
                phone = _pick_phone_from_text(crawl_text or "", f"{engine_name}_crawl")
                if phone: return phone
            except: pass

    return None


# ── Per-engine runner ─────────────────────────────────────────────────────────

async def run_engine_benchmark(
    engine_name: str,
    rows: List[ExcelRow],
    telemetry: BenchmarkTelemetry,
    input_file: str,
    search_only: bool = False,
    no_delay: bool = False,
    start_idx: int = 0,
) -> None:
    """
    Run the full extraction pipeline on `rows` using a SINGLE tier agent.
    No hybrid fallback — pure isolation for accurate per-tier telemetry.
    After completion, flushes WORK/benchmarks/tier_{name}.json.
    """
    import random

    label = TIER_LABELS.get(engine_name, engine_name)
    AgentClass = ENGINE_REGISTRY[engine_name]()
    agent = AgentClass(worker_id=0)

    logger.info(f"\n{'═' * 64}")
    logger.info(f"🚀  BENCHMARKING: {engine_name.upper()}  [{label}]  ({len(rows)} rows)")
    logger.info(f"{'═' * 64}")

    try:
        await agent.start()
    except Exception as exc:
        logger.error(f"[{engine_name}] ❌ Failed to start: {exc}")
        _record(engine_name, 0, "ERROR", 0.0, "startup_failure", telemetry)
        return

    is_scrapy = engine_name == "scrapy"

    for i, row in enumerate(rows, 1):
        row_start = time.perf_counter()
        status = "ERROR"
        interruption_reason: Optional[str] = None
        phone: Optional[str] = None

        try:
            # ── Full phone extraction pipeline (mirrors production phone_hunter) ──
            phone = await _extract_phone_for_row(
                agent=agent,
                engine_name=engine_name,
                row=row,
                is_scrapy=is_scrapy,
                search_only=search_only,
            )
            status = "DONE" if phone else "NO TEL"

            # Detect interruption signal from the agent
            if hasattr(agent, "last_interruption_reason") and agent.last_interruption_reason:
                interruption_reason = agent.last_interruption_reason
                agent.last_interruption_reason = None

            if phone:
                logger.info(f"🏆 [{engine_name.upper()}] Row {i}/{len(rows)} DONE: {phone}")

        except asyncio.CancelledError:
            logger.warning(f"[{engine_name}] Row #{i} cancelled.")
            status = "ERROR"
            interruption_reason = "cancelled"
            break
        except Exception as exc:
            logger.error(f"[{engine_name}] Row #{i} exception: {exc}")
            status = "ERROR"
            interruption_reason = "exception"

        latency = time.perf_counter() - row_start
        row.status = status
        row.phone = phone
        _record(engine_name, start_idx + i, status, latency, interruption_reason, telemetry)

        # Progress heartbeat every 25 rows
        if i % 25 == 0 or i == len(rows):
            done   = sum(1 for r in rows[:i] if getattr(r, "status", "") == "DONE")
            no_tel = sum(1 for r in rows[:i] if getattr(r, "status", "") == "NO TEL")
            errs   = i - done - no_tel
            logger.info(
                f"  [{engine_name}] Row {start_idx + i} | "
                f"DONE={done}  NO_TEL={no_tel}  ERR={errs}  lat={latency:.1f}s"
            )

        # Inter-row human delay
        if not no_delay:
            await asyncio.sleep(random.uniform(config.MIN_DELAY_SECONDS, config.MAX_DELAY_SECONDS))

        save_checkpoint(engine_name, start_idx + i)

    try:
        await agent.close()
    except Exception:
        pass

    # ── Flush per-tier JSON ───────────────────────────────────────────────
    telemetry_payload = telemetry.save()
    tier_stats_list = [e for e in telemetry_payload.get("engines", [])
                       if e.get("engine") == engine_name]
    tier_stats = tier_stats_list[0] if tier_stats_list else {}
    tier_stats["input_file"] = input_file
    save_tier_json(engine_name, rows, tier_stats)

    logger.info(f"✅  {engine_name.upper()} benchmark complete.")


# ── Main entrypoint ───────────────────────────────────────────────────────────

async def main() -> None:
    args = parse_args()
    input_path = Path(args.input).resolve()

    if not input_path.exists():
        logger.error(f"❌ Input file not found: {input_path}")
        sys.exit(1)

    logger.info(f"📂 Loading dataset: {input_path}")
    rows, _ = await asyncio.to_thread(read_excel, str(input_path))

    if not rows:
        logger.error("❌ No rows loaded. Aborting.")
        sys.exit(1)

    rows_to_process = rows[:args.rows]
    logger.info(
        f"📊 {len(rows_to_process)} rows | Tiers requested: {args.engines} | "
        f"Output dir: {BENCH_DIR}"
    )

    # ── Preflight health check (can be skipped with --skip-preflight) ────
    engines_to_run = args.engines
    if not args.skip_preflight:
        engines_to_run = await preflight_check(args.engines, fail_fast=args.fail_fast)
    else:
        logger.warning("⚠️  --skip-preflight: Skipping health check. Tier failures will be recorded during the run.")

    if not engines_to_run:
        logger.error("❌ No tiers available after preflight. Aborting.")
        sys.exit(1)

    logger.info(f"🚀 Starting benchmark with {len(engines_to_run)} tier(s): {engines_to_run}")

    # Telemetry — loads existing results from WORK/telemetry.json
    telemetry = BenchmarkTelemetry()
    for name in engines_to_run:
        telemetry.register_engine(name)

    logger.info("📈 Cumulative results tracking active.")

    checkpoint = load_checkpoint()

    for engine_name in engines_to_run:
        if engine_name not in ENGINE_REGISTRY:
            logger.warning(f"⚠️  Unknown tier '{engine_name}' — skipping.")
            continue

        # Fresh slate for each tier
        for row in rows_to_process:
            row.phone = None
            row.status = "PENDING"

        last_row = checkpoint.get(engine_name, 0)
        if last_row >= len(rows_to_process):
            logger.info(f"⏭️  Tier '{engine_name}' already completed. Skipping.")
            continue

        await run_engine_benchmark(
            engine_name=engine_name,
            rows=rows_to_process[last_row:],
            telemetry=telemetry,
            input_file=str(input_path),
            search_only=args.search_only,
            no_delay=args.no_delay,
            start_idx=last_row,
        )

        # Print live ranking after each tier completes
        telemetry.finalize()

        if engine_name != engines_to_run[-1]:
            logger.info("⏸️  Cooling down 30s before next tier...")
            await asyncio.sleep(30)

    # ── Final cross-tier summary ──────────────────────────────────────────
    logger.info("🏁 All tiers benchmarked.")
    final_payload = telemetry.finalize()
    summary_path = save_final_summary(engines_to_run, final_payload, str(input_path))

    # Clear checkpoint on full success
    cp_path = config.WORK_DIR / "benchmark_checkpoint.json"
    if cp_path.exists():
        cp_path.unlink()

    print("\n" + "═" * 64)
    print("📁  OUTPUT FILES")
    print("═" * 64)
    for eng in engines_to_run:
        tier_file = BENCH_DIR / f"tier_{eng}.json"
        status_icon = "✅" if tier_file.exists() else "❌"
        print(f"   {status_icon}  {tier_file}")
    print(f"   🏆  {summary_path}")
    print("═" * 64 + "\n")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, asyncio.exceptions.CancelledError):
        print("\n" + "═" * 60)
        print("🛑  Benchmark stopped by user. Partial results saved.")
        print("═" * 60 + "\n")
        sys.exit(0)
