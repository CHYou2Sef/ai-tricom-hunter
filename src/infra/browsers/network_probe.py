import time
from core.logger import get_logger

logger = get_logger(__name__)

class NetworkSpeedProbe:
    """
    Lightweight network quality probe to adapt timeouts based on connection quality.
    Measures TCP connect latency and small-asset download speed.
    """

    _last_check_time = 0.0
    _last_score = "medium"  # "good" | "medium" | "bad"
    _last_latency_ms = 100.0
    _probe_interval_sec = 30.0  # Re-probe every 30s to avoid overhead

    @classmethod
    async def probe(cls, force_refresh: bool = False) -> tuple[str, float]:
        """
        Run a quick network quality check.

        Args:
            force_refresh: if True, bypasses the 30s cache and re-measures now.
                           Use this at startup so the first row doesn't pay the
                           lazy-probe penalty.

        Returns:
            tuple of (score, latency_ms)
            score: "good" (< 100ms), "medium" (100-300ms), "bad" (> 300ms)
        """
        now = time.time()
        if not force_refresh and (now - cls._last_check_time < cls._probe_interval_sec):
            return cls._last_score, cls._last_latency_ms

        cls._last_check_time = now
        latency_ms = await cls._measure_latency()
        cls._last_latency_ms = latency_ms

        if latency_ms < 100:
            cls._last_score = "good"
        elif latency_ms < 300:
            cls._last_score = "medium"
        else:
            cls._last_score = "bad"

        logger.debug(
            f"[NetworkProbe] score={cls._last_score} latency={latency_ms:.0f}ms"
        )
        return cls._last_score, cls._last_latency_ms

    @staticmethod
    async def _measure_latency() -> float:
        """Measure TCP connect latency to a known host."""
        import socket

        test_host = "www.google.com"
        test_port = 443
        delays = []

        for _ in range(3):
            try:
                t0 = time.perf_counter()
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(5.0)
                sock.connect((test_host, test_port))
                sock.close()
                delays.append((time.perf_counter() - t0) * 1000)
            except Exception:
                delays.append(500.0)  # Fallback for connection failures

        return sum(delays) / len(delays) if delays else 500.0

    @classmethod
    def get_timeout_multiplier(cls) -> float:
        """Return a timeout multiplier based on current network score."""
        if cls._last_score == "good":
            return 1.0
        elif cls._last_score == "medium":
            return 1.5
        else:
            return 2.5
