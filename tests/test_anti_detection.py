"""
tests/test_anti_detection.py

Unit tests for the GEMINI.md anti-detection architecture.
Run with:  pytest tests/test_anti_detection.py -v

Tests cover:
  Task 2 — Fingerprint bundle uniqueness (10 properties)
  Task 3 — Proxy state machine transitions
  Task 4 — Per-action delay bounds
  Task 5 — CAPTCHA type detection accuracy
  Task 6 — Alert system (INFO / WARN / CRITICAL)
  Layer 3 — HybridEngine URL classification
"""

import time
import pytest


# ─────────────────────────────────────────────────────────────────────────────
# TASK 2 — FINGERPRINT BUNDLE
# ─────────────────────────────────────────────────────────────────────────────

class TestFingerprintBundle:

    def test_bundle_has_all_10_properties(self):
        from common.anti_bot import get_fingerprint_bundle
        bundle = get_fingerprint_bundle()
        required_keys = [
            "user_agent", "viewport", "webgl_renderer", "webgl_vendor",
            "canvas_noise", "languages", "platform", "plugins_count",
            "hardware_concurrency", "device_memory",
        ]
        for key in required_keys:
            assert key in bundle, f"Missing fingerprint property: {key}"

    def test_viewport_within_configured_bounds(self):
        from core import config
        from common.anti_bot import get_fingerprint_bundle
        for _ in range(20):
            bundle = get_fingerprint_bundle()
            vp = bundle["viewport"]
            assert config.FINGERPRINT_VIEWPORT_MIN_W <= vp["width"]  <= config.FINGERPRINT_VIEWPORT_MAX_W
            assert config.FINGERPRINT_VIEWPORT_MIN_H <= vp["height"] <= config.FINGERPRINT_VIEWPORT_MAX_H

    def test_bundles_are_unique_across_sessions(self):
        from common.anti_bot import get_fingerprint_bundle
        bundles = [get_fingerprint_bundle() for _ in range(10)]
        # Collect all (UA, w, h) triples — should have at least 2 distinct ones in 10
        signatures = {
            (b["user_agent"], b["viewport"]["width"], b["viewport"]["height"])
            for b in bundles
        }
        assert len(signatures) > 1, "All 10 bundles have identical signatures — not random"

    def test_canvas_noise_in_valid_range(self):
        from common.anti_bot import get_fingerprint_bundle
        for _ in range(10):
            bundle = get_fingerprint_bundle()
            assert 0.0001 <= bundle["canvas_noise"] <= 0.002

    def test_cdp_script_is_non_empty_js(self):
        from common.anti_bot import get_fingerprint_bundle, build_cdp_injection_script
        bundle = get_fingerprint_bundle()
        script = build_cdp_injection_script(bundle)
        assert len(script) > 200
        assert "navigator.userAgent" in script
        assert "webdriver" in script          # present as 'webdriver' (escaped in f-string)
        assert "WebGLRenderingContext" in script

    def test_randomise_viewport_helper(self):
        from core import config
        from common.anti_bot import randomise_viewport
        for _ in range(20):
            w, h = randomise_viewport()
            assert config.FINGERPRINT_VIEWPORT_MIN_W <= w <= config.FINGERPRINT_VIEWPORT_MAX_W
            assert config.FINGERPRINT_VIEWPORT_MIN_H <= h <= config.FINGERPRINT_VIEWPORT_MAX_H


# ─────────────────────────────────────────────────────────────────────────────
# TASK 3 — PROXY STATE MACHINE
# ─────────────────────────────────────────────────────────────────────────────

class TestProxyStateMachine:

    def _make_manager(self):
        """Create an isolated ProxyManager with a stubbed proxy pool."""
        from common.proxy_manager import ProxyManager, ProxyRecord, ProxyState
        pm = ProxyManager()
        # Pre-populate with test proxies
        for i in range(5):
            addr = f"http://10.0.0.{i}:8080"
            pm._records[addr] = ProxyRecord(address=addr)
            pm._active_pool.append(addr)
        return pm, ProxyState

    def test_healthy_state_on_single_error(self):
        pm, PS = self._make_manager()
        addr = "http://10.0.0.0:8080"
        state = pm.mark_error(addr, 403)
        assert state == PS.HEALTHY

    def test_transitions_to_warn_at_threshold(self):
        from core import config
        pm, PS = self._make_manager()
        addr = "http://10.0.0.1:8080"
        for _ in range(config.PROXY_WARN_THRESHOLD):
            state = pm.mark_error(addr, 403)
        assert state == PS.WARN

    def test_transitions_to_ban_at_ban_threshold(self):
        from core import config
        pm, PS = self._make_manager()
        addr = "http://10.0.0.2:8080"
        # Prevent sleep by patching _rotate_with_backoff
        pm._rotate_with_backoff = lambda: None
        for _ in range(config.PROXY_BAN_THRESHOLD):
            pm.mark_error(addr, 429)
        assert pm._records[addr].state == PS.BAN

    def test_force_ban_immediately_sets_ban_state(self):
        pm, PS = self._make_manager()
        addr = "http://10.0.0.3:8080"
        pm._rotate_with_backoff = lambda: None
        pm.mark_banned(addr)
        assert pm._records[addr].state == PS.BAN

    def test_get_proxy_stats_returns_all_records(self):
        pm, PS = self._make_manager()
        stats = pm.get_proxy_stats()
        assert len(stats) == 5
        for data in stats.values():
            assert "state" in data
            assert "error_count" in data
            assert "last_status" in data


# ─────────────────────────────────────────────────────────────────────────────
# TASK 4 — PER-ACTION DELAY BOUNDS
# ─────────────────────────────────────────────────────────────────────────────

class TestActionDelays:

    @pytest.mark.parametrize("action", ["click", "type_char", "submit", "navigate", "scroll", "read_wait"])
    def test_action_delay_within_config_bounds(self, action):
        """
        Call get_random_delay directly with each profile — assert the result
        is within [min, max].  We patch time.sleep so the test runs instantly.
        """
        from core import config
        from common.anti_bot import get_random_delay
        profile = config.ACTION_DELAY_PROFILES[action]
        for _ in range(50):
            delay = get_random_delay(
                min_val=profile["min"],
                max_val=profile["max"],
                distribution="normal",
                mean=profile["mean"],
                std=profile["std"],
            )
            assert profile["min"] <= delay <= profile["max"], (
                f"action='{action}' delay {delay:.4f}s out of bounds "
                f"[{profile['min']}, {profile['max']}]"
            )

    def test_action_delay_does_not_crash_on_unknown_action(self, monkeypatch):
        """Unknown actions should fall back to human_delay without raising."""
        import common.anti_bot as ab
        monkeypatch.setattr("time.sleep", lambda _: None)
        ab.action_delay("unknown_action_xyz")  # Should not raise


# ─────────────────────────────────────────────────────────────────────────────
# TASK 5 — CAPTCHA TYPE DETECTION
# ─────────────────────────────────────────────────────────────────────────────

class TestCaptchaDetection:

    def test_detects_turnstile(self):
        from common.captcha_solver import detect_captcha_type
        html = '<div class="cf-turnstile" data-sitekey="abc123"></div>'
        assert detect_captcha_type(html) == "turnstile"

    def test_detects_hcaptcha(self):
        from common.captcha_solver import detect_captcha_type
        html = '<div class="h-captcha" data-sitekey="xyz789"></div>'
        assert detect_captcha_type(html) == "hcaptcha"

    def test_detects_recaptcha_v2(self):
        from common.captcha_solver import detect_captcha_type
        html = '<div class="g-recaptcha" data-sitekey="6Lc..."></div>'
        assert detect_captcha_type(html) == "recaptcha_v2"

    def test_detects_generic_captcha(self):
        from common.captcha_solver import detect_captcha_type
        html = "<html><body>unusual traffic from your computer network</body></html>"
        assert detect_captcha_type(html) == "manual"

    def test_returns_none_on_clean_page(self):
        from common.captcha_solver import detect_captcha_type
        html = "<html><body><h1>Welcome to our shop!</h1></body></html>"
        assert detect_captcha_type(html) is None

    def test_priority_turnstile_over_recaptcha(self):
        """Turnstile should win even if recaptcha text also appears."""
        from common.captcha_solver import detect_captcha_type
        html = '<div cf-turnstile></div><div class="g-recaptcha"></div>'
        assert detect_captcha_type(html) == "turnstile"

    def test_extract_sitekey_from_html(self):
        from common.captcha_solver import _extract_sitekey
        html = '<div class="g-recaptcha" data-sitekey="6LdMyKEpAAAAAA"></div>'
        key  = _extract_sitekey(html, "recaptcha_v2")
        assert key == "6LdMyKEpAAAAAA"


# ─────────────────────────────────────────────────────────────────────────────
# TASK 6 — THREE-TIER ALERT SYSTEM
# ─────────────────────────────────────────────────────────────────────────────

class TestAlertSystem:

    def test_alert_info_does_not_print_to_stdout(self, capsys):
        from core.logger import alert
        alert("INFO", "Test info message")
        captured = capsys.readouterr()
        assert "Test info message" not in captured.out  # INFO → log only, no console print

    def test_alert_warn_prints_banner(self, capsys):
        from core.logger import alert
        alert("WARN", "Test warning message", {"url": "https://example.com"})
        captured = capsys.readouterr()
        assert "WARN" in captured.out
        assert "Test warning message" in captured.out

    def test_alert_critical_prints_banner(self, capsys):
        from core.logger import alert
        alert("CRITICAL", "Test critical message")
        captured = capsys.readouterr()
        assert "CRITICAL" in captured.out
        assert "Test critical message" in captured.out

    def test_stale_connection_alert_warn_on_first_attempt(self, capsys):
        from core.logger import stale_connection_alert
        stale_connection_alert(attempt=1, max_attempts=3, detail="Connection reset")
        captured = capsys.readouterr()
        assert "WARN" in captured.out

    def test_stale_connection_alert_critical_on_last_attempt(self, capsys):
        from core.logger import stale_connection_alert
        stale_connection_alert(attempt=3, max_attempts=3, detail="Timeout")
        captured = capsys.readouterr()
        assert "CRITICAL" in captured.out


# ─────────────────────────────────────────────────────────────────────────────
# HYBRID ENGINE — URL CLASSIFICATION
# ─────────────────────────────────────────────────────────────────────────────

class TestHybridEngineClassification:

    def test_tier1_for_generic_url(self):
        from infra.browsers.hybrid_engine import classify_url
        assert classify_url("https://www.google.com") == 1

    def test_tier2_for_linkedin(self):
        from infra.browsers.hybrid_engine import classify_url
        assert classify_url("https://www.linkedin.com/in/john-doe") == 2

    def test_tier2_for_facebook(self):
        from infra.browsers.hybrid_engine import classify_url
        assert classify_url("https://www.facebook.com/acme-corp") == 2

    def test_tier3_for_amazon(self):
        from infra.browsers.hybrid_engine import classify_url
        assert classify_url("https://www.amazon.fr/product/12345") == 3

    def test_tier3_for_fnac(self):
        from infra.browsers.hybrid_engine import classify_url
        assert classify_url("https://www.fnac.com/search?q=laptop") == 3

    def test_tier3_takes_priority_over_tier2(self):
        """A URL matching both tier3 and tier2 rules → Tier 3 wins (checked first)."""
        from infra.browsers.hybrid_engine import classify_url
        # Simulate a URL with both markers
        url = "https://amazon.cloudflare-protected.com/product"
        assert classify_url(url) == 3
