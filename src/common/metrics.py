"""
╔══════════════════════════════════════════════════════════════════════════╗
║  utils/metrics.py  —  V2: Dual-Output Telemetry Engine                   ║
║                                                                          ║
║  Tracks two distinct metric layers:                                      ║
║                                                                          ║
║  1. FILE-LEVEL: PerformanceTracker (backward-compatible)                 ║
║     Tracks overall file processing speed, success rate, row throughput.  ║
║                                                                          ║
║  2. TIER-LEVEL: BenchmarkTelemetry (new)                                 ║
║     Per-engine MTTI (Mean Time To Interruption), CAPTCHA/IP-ban rates,   ║
║     connection latency, and cumulative uptime continuity scores.          ║
║     Outputs to BOTH agent.log (console) AND WORK/telemetry.json.         ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import json
import time
from pathlib import Path
from typing import Dict, Any, Optional, List

from core import config
from core.logger import get_logger

logger = get_logger(__name__)

# Global singleton-like instance for shared tracking across workers
_telemetry_instance: Optional["BenchmarkTelemetry"] = None

def get_telemetry() -> "BenchmarkTelemetry":
    global _telemetry_instance
    if _telemetry_instance is None:
        _telemetry_instance = BenchmarkTelemetry()
    return _telemetry_instance

# ─── File path for the persistent JSON telemetry payload ──────────────────
TELEMETRY_PATH: Path = config.WORK_DIR / "telemetry.json"


# ══════════════════════════════════════════════════════════════════════════
# LAYER 1 — PerformanceTracker  (backward-compatible, file-level)
# ══════════════════════════════════════════════════════════════════════════

class PerformanceTracker:
    """Tracks processing times and success rates for a single file run."""

    def __init__(self):
        self.file_start_time: Optional[float] = None
        self.file_end_time: Optional[float] = None
        self.rows_processed: int = 0
        self.rows_done: int = 0
        self.total_row_duration: float = 0.0

    def start_file_processing(self) -> None:
        self.file_start_time = time.perf_counter()

    def end_file_processing(self) -> None:
        self.file_end_time = time.perf_counter()

    def track_row(self, duration: float, status: str) -> None:
        self.rows_processed += 1
        self.total_row_duration += duration
        if status == "DONE":
            self.rows_done += 1

    def get_metrics_summary(self) -> Dict[str, Any]:
        total_time = (
            round(self.file_end_time - self.file_start_time, 2)
            if self.file_start_time and self.file_end_time
            else 0.0
        )
        success_rate = (self.rows_done / self.rows_processed * 100) if self.rows_processed > 0 else 0.0
        avg_row_time = (self.total_row_duration / self.rows_processed) if self.rows_processed > 0 else 0.0
        return {
            "total_execution_seconds": total_time,
            "average_row_seconds": round(avg_row_time, 2),
            "rows_processed": self.rows_processed,
            "success_rate_percent": round(success_rate, 2),
        }

    def format_console_report(self) -> str:
        m = self.get_metrics_summary()
        return (
            f"⏱️  Performance Report ⏱️\n"
            f"   Total elapsed:  {m['total_execution_seconds']}s\n"
            f"   Avg row speed:  {m['average_row_seconds']}s / row\n"
            f"   Success rate :  {m['success_rate_percent']}% "
            f"({self.rows_done}/{m['rows_processed']} done)"
        )


# ══════════════════════════════════════════════════════════════════════════
# LAYER 2 — BenchmarkTelemetry  (new, tier/engine-level continuity)
# ══════════════════════════════════════════════════════════════════════════

class TierStats:
    """Accumulates raw events for a single engine/tier during a benchmark run."""

    def __init__(self, engine_name: str):
        self.engine_name: str = engine_name
        self.rows_attempted: int = 0
        self.rows_done: int = 0
        self.rows_no_tel: int = 0
        self.rows_error: int = 0
        # Interruption tracking
        self.interruptions: List[Dict[str, Any]] = []   # [{reason, ts, row_index}]
        self.captcha_count: int = 0
        self.ip_ban_count: int = 0
        # Timing
        self.total_latency_sec: float = 0.0
        self.session_start_ts: float = time.monotonic()
        self._last_clean_ts: float = time.monotonic()  # Start of current uninterrupted streak
        # New: Per-method tracking
        self.methods: Dict[str, Dict[str, Any]] = {}  # {method_name: {attempts, successes, latency}}

    # ── Event recording ────────────────────────────────────────────────

    def record_row_result(
        self,
        row_index: int,
        status: str,
        latency_sec: float,
        interruption_reason: Optional[str] = None,
        method_name: str = "unknown",
    ) -> None:
        """
        Record one row's outcome.
        - status: 'DONE' | 'NO TEL' | 'ERROR' | 'SUCCESS'
        - interruption_reason: 'captcha_waf' | 'ip_ban' | 'exception' | None
        """
        self.rows_attempted += 1
        self.total_latency_sec += latency_sec

        # Method tracking
        if method_name not in self.methods:
            self.methods[method_name] = {"attempts": 0, "successes": 0, "latency": 0.0}
        self.methods[method_name]["attempts"] += 1
        self.methods[method_name]["latency"] += latency_sec

        if status in ("DONE", "SUCCESS"):
            self.rows_done += 1
            self.methods[method_name]["successes"] += 1
        elif status == "NO TEL":
            self.rows_no_tel += 1
        else:
            self.rows_error += 1

        if interruption_reason:
            now = time.monotonic()
            self.interruptions.append({
                "row_index": row_index,
                "reason": interruption_reason,
                "uptime_before_sec": round(now - self._last_clean_ts, 1),
                "ts_offset_sec": round(now - self.session_start_ts, 1),
            })
            self._last_clean_ts = now  # Reset streak clock
            if "captcha" in interruption_reason or "waf" in interruption_reason:
                self.captcha_count += 1
            elif "ip_ban" in interruption_reason:
                self.ip_ban_count += 1

    # ── Derived metrics ────────────────────────────────────────────────

    def compute(self) -> Dict[str, Any]:
        """Compute all derived MTTI and continuity statistics."""
        success_rate = round(self.rows_done / self.rows_attempted * 100, 2) if self.rows_attempted else 0.0
        avg_latency  = round(self.total_latency_sec / self.rows_attempted, 2) if self.rows_attempted else 0.0
        total_uptime = round(time.monotonic() - self.session_start_ts, 1)

        # MTTI — average seconds of uninterrupted operation between failures. 
        # Safely extract uptimes, handling potential missing keys from old logs.
        uptimes = [ev.get("uptime_before_sec", 0.0) for ev in self.interruptions]
        mtti_sec = round(sum(uptimes) / len(uptimes), 1) if uptimes else total_uptime

        return {
            "engine": self.engine_name,
            "rows_attempted": self.rows_attempted,
            "rows_done": self.rows_done,
            "rows_no_tel": self.rows_no_tel,
            "rows_error": self.rows_error,
            "success_rate_pct": success_rate,
            "avg_latency_sec": avg_latency,
            "total_session_sec": total_uptime,
            "interruptions_total": len(self.interruptions),
            "captcha_blocks": self.captcha_count,
            "ip_ban_blocks": self.ip_ban_count,
            "mtti_sec": mtti_sec,   # ← Primary continuity KPI
            "interruption_log": self.interruptions,
            "methods": self.methods,
        }

    def format_console_report(self) -> str:
        """Render a rich console-friendly block for this engine."""
        m = self.compute()
        bar_filled = int(m["success_rate_pct"] / 5)
        bar = ("█" * bar_filled).ljust(20)
        report = (
            f"\n  ┌─ {m['engine']}\n"
            f"  │  Rows:        {m['rows_done']:>4} DONE / {m['rows_no_tel']:>4} NO TEL / {m['rows_error']:>4} ERR\n"
            f"  │  Success:     [{bar}] {m['success_rate_pct']}%\n"
            f"  │  Avg latency: {m['avg_latency_sec']}s / row\n"
            f"  │  Session time:{m['total_session_sec']}s\n"
            f"  │  ─── Continuity ──────────────────────\n"
            f"  │  MTTI:        {m['mtti_sec']}s  (mean time to interruption)\n"
            f"  │  Interruptions:{m['interruptions_total']} total  "
            f"(CAPTCHA/WAF: {m['captcha_blocks']} | IP Ban: {m['ip_ban_blocks']})\n"
            f"  │  ─── Methods ─────────────────────────\n"
        )
        for meth, mdata in m["methods"].items():
            m_sr = round(mdata["successes"] / mdata["attempts"] * 100, 1) if mdata["attempts"] else 0
            m_lat = round(mdata["latency"] / mdata["attempts"], 2) if mdata["attempts"] else 0
            report += f"  │  - {meth:<20}: {m_sr:>5}% | {m_lat:>5}s\n"
        
        report += "  └──────────────────────────────────────"
        return report


class BenchmarkTelemetry:
    """
    Orchestrates multi-engine benchmark telemetry.

    Usage:
        telemetry = BenchmarkTelemetry()
        telemetry.register_engine("Selenium")
        telemetry.register_engine("Patchright")

        # Inside the benchmark loop:
        telemetry.record("Selenium", row_idx, "DONE", latency, interruption_reason)

        # At the end:
        telemetry.finalize()   # prints + saves telemetry.json
    """

    def __init__(self):
        self._engines: Dict[str, TierStats] = {}
        self._benchmark_start_ts: float = time.monotonic()
        self.load_existing()

    def load_existing(self) -> None:
        """Load existing telemetry data from disk to support cumulative benchmarks."""
        if not TELEMETRY_PATH.exists():
            return
        
        try:
            with open(TELEMETRY_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            # Reconstruct TierStats for each engine
            for engine_data in data.get("engines", []):
                name = engine_data["engine"]
                stats = TierStats(name)
                stats.rows_attempted = engine_data.get("rows_attempted", 0)
                stats.rows_done = engine_data.get("rows_done", 0)
                stats.rows_no_tel = engine_data.get("rows_no_tel", 0)
                stats.rows_error = engine_data.get("rows_error", 0)
                stats.interruptions = engine_data.get("interruption_log", [])
                stats.captcha_count = engine_data.get("captcha_blocks", 0)
                stats.ip_ban_count = engine_data.get("ip_ban_blocks", 0)
                stats.total_latency_sec = engine_data.get("avg_latency_sec", 0) * stats.rows_attempted
                stats.methods = engine_data.get("methods", {})
                
                # For session time, we treat existing data as a "previous session" block
                # We can't perfectly recover monotonic time, so we adjust session_start_ts
                # to reflect the already accumulated total_session_sec
                prev_session_sec = engine_data.get("total_session_sec", 0)
                stats.session_start_ts = time.monotonic() - prev_session_sec
                stats._last_clean_ts = time.monotonic()
                
                self._engines[name] = stats
            
            logger.info(f"[Telemetry] Loaded existing data for {len(self._engines)} engines.")
        except Exception as exc:
            logger.error(f"[Telemetry] Failed to load existing telemetry: {exc}")

    def register_engine(self, name: str) -> None:
        """Register a named engine before the benchmark run starts."""
        if name not in self._engines:
            self._engines[name] = TierStats(engine_name=name)
            logger.info(f"[Telemetry] Registered engine: {name}")

    def record(
        self,
        engine_name: str,
        row_index: int,
        status: str,
        latency_sec: float,
        interruption_reason: Optional[str] = None,
        method_name: str = "unknown",
    ) -> None:
        """Record a single row result for the given engine."""
        if engine_name not in self._engines:
            self.register_engine(engine_name)
        self._engines[engine_name].record_row_result(
            row_index=row_index,
            status=status,
            latency_sec=latency_sec,
            interruption_reason=interruption_reason,
            method_name=method_name,
        )

    def finalize(self) -> Dict[str, Any]:
        """
        Compute all metrics, print the full console report, and flush to
        WORK/telemetry.json (dual-output).
        Returns the full computed payload.
        """
        total_runtime = round(time.monotonic() - self._benchmark_start_ts, 1)
        payload = {
            "benchmark_runtime_sec": total_runtime,
            "engines": [stats.compute() for stats in self._engines.values()],
        }

        # ── Rank engines by MTTI (best continuity = highest MTTI) ─────────
        ranked = sorted(
            payload["engines"],
            key=lambda e: (-e["mtti_sec"], -e["success_rate_pct"]),
        )
        payload["ranking"] = [
            {"rank": i + 1, "engine": e["engine"], "mtti_sec": e["mtti_sec"], "success_rate_pct": e["success_rate_pct"]}
            for i, e in enumerate(ranked)
        ]

        # ── Console output ────────────────────────────────────────────────
        print("\n" + "═" * 64)
        print("📊  BENCHMARK TELEMETRY REPORT — Engine Continuity Comparison")
        print("═" * 64)
        print(f"   Total benchmark runtime: {total_runtime}s")
        for stats in self._engines.values():
            print(stats.format_console_report())
        print("\n  🏆  RANKING  (Best Continuity → Worst)")
        for r in payload["ranking"]:
            print(f"     #{r['rank']}  {r['engine']:<20}  MTTI={r['mtti_sec']}s  |  Success={r['success_rate_pct']}%")
        print("═" * 64 + "\n")

        # ── JSON flush (WORK/telemetry.json) ──────────────────────────────
        self._flush_to_json(payload)

        return payload

    def _flush_to_json(self, payload: Dict[str, Any]) -> None:
        """Write the telemetry payload to the persistent JSON file."""
        try:
            TELEMETRY_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(TELEMETRY_PATH, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            logger.info(f"[Telemetry] ✅ Metrics flushed to: {TELEMETRY_PATH}")
        except Exception as exc:
            logger.error(f"[Telemetry] Failed to write telemetry.json: {exc}")
