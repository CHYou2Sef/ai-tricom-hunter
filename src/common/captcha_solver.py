"""
╔══════════════════════════════════════════════════════════════════════════╗
║  utils/captcha_solver.py                                                 ║
║                                                                          ║
║  TASK 5 from GEMINI.md — CAPTCHA Handling Workflow                       ║
║                                                                          ║
║  Strategy (prevention-first, no paid API required):                     ║
║    1. PREVENT  — Nodriver/stealth eliminates ~90% of CAPTCHAs            ║
║    2. DETECT   — classify type: reCAPTCHA v2 / hCaptcha / Turnstile     ║
║    3. SOLVE    — manual fallback (always works)                          ║
║                  OR 2Captcha / Capsolver (add API key to .env to enable) ║
║    4. INJECT   — insert solution token into the page                     ║
║    5. RESUME   — extra random delay before continuing                    ║
║                                                                          ║
║  Decision tree (GEMINI.md § Task 5):                                     ║
║    CAPTCHA detected?                                                     ║
║      ├─ Turnstile cf-turnstile attr? → Capsolver/2Captcha Turnstile     ║
║      ├─ hCaptcha iframe? → Capsolver/2Captcha hCaptcha                  ║
║      ├─ reCAPTCHA v2 iframe? → 2Captcha image / audio solver            ║
║      └─ Unknown / fallback → manual pause (existing system)             ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import asyncio
import random
import re
import time
from typing import Optional

from core import config
from core.logger import get_logger, alert

logger = get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# CAPTCHA TYPE DETECTION
# ─────────────────────────────────────────────────────────────────────────────

# HTML markers used to identify each CAPTCHA provider
_RECAPTCHA_MARKERS  = ["recaptcha", "grecaptcha", "g-recaptcha", "reCAPTCHA"]
_HCAPTCHA_MARKERS   = ["hcaptcha", "h-captcha", "hCaptcha"]
_TURNSTILE_MARKERS  = ["cf-turnstile", "challenges.cloudflare.com/turnstile"]
_GENERIC_MARKERS    = [
    "unusual traffic", "trafic inhabituel",
    "are you a robot", "êtes-vous un robot",
    "verify you are human", "access denied", "blocked",
    "captcha", "i'm not a robot",
]


def detect_captcha_type(page_source: str) -> Optional[str]:
    """
    Identify the CAPTCHA type from the raw HTML source.

    Decision tree (GEMINI.md § Task 5):
      1. Turnstile (Cloudflare) → "turnstile"
      2. hCaptcha               → "hcaptcha"
      3. reCAPTCHA v2           → "recaptcha_v2"
      4. Generic / unknown      → "manual"
      5. No CAPTCHA found       → None

    Args:
        page_source : Raw HTML of the current browser page

    Returns:
        str | None : CAPTCHA type identifier, or None if no CAPTCHA found
    """
    lower = page_source.lower()

    # Priority order: Turnstile → hCaptcha → reCAPTCHA → generic
    for marker in _TURNSTILE_MARKERS:
        if marker.lower() in lower:
            logger.warning("[CaptchaSolver] 🟡 Detected: Cloudflare Turnstile")
            alert("WARN", "CAPTCHA detected: Cloudflare Turnstile",
                  {"type": "turnstile", "solver": config.CAPTCHA_SOLVER})
            return "turnstile"

    for marker in _HCAPTCHA_MARKERS:
        if marker.lower() in lower:
            logger.warning("[CaptchaSolver] 🟡 Detected: hCaptcha")
            alert("WARN", "CAPTCHA detected: hCaptcha",
                  {"type": "hcaptcha", "solver": config.CAPTCHA_SOLVER})
            return "hcaptcha"

    for marker in _RECAPTCHA_MARKERS:
        if marker.lower() in lower:
            logger.warning("[CaptchaSolver] 🟡 Detected: reCAPTCHA v2")
            alert("WARN", "CAPTCHA detected: reCAPTCHA v2",
                  {"type": "recaptcha_v2", "solver": config.CAPTCHA_SOLVER})
            return "recaptcha_v2"

    for marker in _GENERIC_MARKERS:
        if marker in lower:
            logger.warning(f"[CaptchaSolver] 🟡 Detected: generic CAPTCHA ('{marker}')")
            alert("WARN", "CAPTCHA detected: unknown type — using manual fallback",
                  {"indicator": marker})
            return "manual"

    return None  # No CAPTCHA detected


# ─────────────────────────────────────────────────────────────────────────────
# CAPTCHA SOLVING — PREVENTION-FIRST APPROACH
# ─────────────────────────────────────────────────────────────────────────────

async def solve_captcha_async(page, captcha_type: str) -> bool:
    """
    Attempt to solve the detected CAPTCHA.

    Solver selection (GEMINI.md § Task 5):
    ┌────────────────┬──────────────────────────────────────────────────────┐
    │ CAPTCHA Type   │ Solver Used                                          │
    ├────────────────┼──────────────────────────────────────────────────────┤
    │ turnstile      │ Capsolver > 2Captcha > manual fallback              │
    │ hcaptcha       │ Capsolver > 2Captcha > manual fallback              │
    │ recaptcha_v2   │ 2Captcha image/audio > Capsolver > manual fallback  │
    │ manual         │ Manual pause (always available)                     │
    └────────────────┴──────────────────────────────────────────────────────┘

    Args:
        page         : Playwright/Nodriver page object
        captcha_type : Output of detect_captcha_type()

    Returns:
        True  → CAPTCHA solved and session can continue
        False → Failed to solve (row will be skipped)
    """
    solver = config.CAPTCHA_SOLVER
    api_key = config.CAPTCHA_API_KEY

    # ── Route to the correct solver ──────────────────────────────────
    if solver in ("2captcha", "capsolver") and api_key:
        logger.info(f"[CaptchaSolver] Using {solver} API for '{captcha_type}'...")
        token = await _api_solve(page, captcha_type, solver, api_key)
        if token:
            await _inject_token(page, captcha_type, token)
            await asyncio.sleep(random.uniform(1.5, 3.0))  # Extra random delay after solve
            alert("INFO", f"CAPTCHA auto-solved via {solver}",
                  {"type": captcha_type})
            return True
        else:
            logger.warning(f"[CaptchaSolver] API solve failed — falling back to manual.")

    # ── Manual fallback (always available, no API needed) ────────────
    return await _manual_solve_async(captcha_type)


def solve_captcha_sync(page_source: str, captcha_type: str) -> bool:
    """
    Synchronous version for Selenium-based agents.
    Always uses manual fallback (cannot inject tokens in sync mode easily).

    Args:
        page_source  : Current page HTML (for detection log)
        captcha_type : Output of detect_captcha_type()

    Returns:
        True if user confirmed solved, False if timeout.
    """
    from common.anti_bot import wait_for_human_captcha_solve
    logger.info(f"[CaptchaSolver] Sync mode — manual fallback for '{captcha_type}'")
    return wait_for_human_captcha_solve(timeout=config.CAPTCHA_WAIT_SECONDS)


# ─────────────────────────────────────────────────────────────────────────────
# API SOLVER STUBS (activated when CAPTCHA_API_KEY is set in .env)
# ─────────────────────────────────────────────────────────────────────────────

async def _api_solve(page, captcha_type: str, solver: str, api_key: str) -> Optional[str]:
    """
    Submit the CAPTCHA to the chosen external API and poll for the token.

    This is a production-ready stub. To activate:
      1. Create an account at 2captcha.com OR capsolver.com
      2. Add to .env:
           CAPTCHA_SOLVER=2captcha   (or capsolver)
           CAPTCHA_API_KEY=your_key

    Args:
        page         : Live browser page (for sitekey extraction)
        captcha_type : "turnstile" | "hcaptcha" | "recaptcha_v2"
        solver       : "2captcha" | "capsolver"
        api_key      : Your API key

    Returns:
        str | None : Solution token or None on failure
    """
    try:
        # Extract sitekey from page source
        html     = await _get_page_html(page)
        sitekey  = _extract_sitekey(html, captcha_type)
        page_url = await _get_page_url(page)

        if not sitekey:
            logger.warning("[CaptchaSolver] Could not extract sitekey — skipping API solve.")
            return None

        logger.info(f"[CaptchaSolver] Sitekey: {sitekey[:30]}... → sending to {solver}")

        if solver == "2captcha":
            return await _submit_to_2captcha(sitekey, page_url, captcha_type, api_key)
        elif solver == "capsolver":
            return await _submit_to_capsolver(sitekey, page_url, captcha_type, api_key)

    except Exception as exc:
        logger.error(f"[CaptchaSolver] API solve error: {exc}")
    return None


async def _submit_to_2captcha(sitekey: str, url: str, captcha_type: str, api_key: str) -> Optional[str]:
    """
    2Captcha API integration (https://2captcha.com/api-docs).
    Costs ~$1–3 per 1000 CAPTCHAs. Free trial available.
    Install: pip install 2captcha-python
    """
    try:
        # Import only if user has installed it
        from twocaptcha import TwoCaptcha  # type: ignore
        solver = TwoCaptcha(api_key)

        if captcha_type == "recaptcha_v2":
            result = solver.recaptcha(sitekey=sitekey, url=url)
        elif captcha_type == "hcaptcha":
            result = solver.hcaptcha(sitekey=sitekey, url=url)
        elif captcha_type == "turnstile":
            result = solver.turnstile(sitekey=sitekey, url=url)
        else:
            return None

        return result.get("code")

    except ImportError:
        logger.warning("[CaptchaSolver] 2captcha-python not installed. Run: pip install 2captcha-python")
        return None
    except Exception as exc:
        logger.error(f"[CaptchaSolver] 2Captcha error: {exc}")
        return None


async def _submit_to_capsolver(sitekey: str, url: str, captcha_type: str, api_key: str) -> Optional[str]:
    """
    Capsolver API integration (https://capsolver.com — has free tier).
    Install: pip install capsolver
    """
    try:
        import capsolver  # type: ignore
        capsolver.api_key = api_key

        if captcha_type == "turnstile":
            solution = capsolver.solve({
                "type": "AntiTurnstileTaskProxyLess",
                "websiteURL": url,
                "websiteKey": sitekey,
            })
        elif captcha_type == "hcaptcha":
            solution = capsolver.solve({
                "type": "HCaptchaTaskProxyLess",
                "websiteURL": url,
                "websiteKey": sitekey,
            })
        elif captcha_type == "recaptcha_v2":
            solution = capsolver.solve({
                "type": "ReCaptchaV2TaskProxyLess",
                "websiteURL": url,
                "websiteKey": sitekey,
            })
        else:
            return None

        return solution.get("gRecaptchaResponse") or solution.get("token")

    except ImportError:
        logger.warning("[CaptchaSolver] capsolver not installed. Run: pip install capsolver")
        return None
    except Exception as exc:
        logger.error(f"[CaptchaSolver] Capsolver error: {exc}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# TOKEN INJECTION
# ─────────────────────────────────────────────────────────────────────────────

async def _inject_token(page, captcha_type: str, token: str) -> None:
    """
    Inject the solved CAPTCHA token back into the page.
    Works for reCAPTCHA v2, hCaptcha, and Turnstile.

    Args:
        page         : Playwright/Nodriver page object
        captcha_type : Determines which DOM element to target
        token        : Solution token from 2Captcha or Capsolver
    """
    try:
        if captcha_type in ("recaptcha_v2", "hcaptcha"):
            # Standard injection via the hidden textarea
            await page.evaluate(
                f"""document.querySelector('[name="g-recaptcha-response"], """
                f"""[name="h-captcha-response"]').value = '{token}';"""
            )
        elif captcha_type == "turnstile":
            # Cloudflare Turnstile uses a hidden input
            await page.evaluate(
                f"""document.querySelector('[name="cf-turnstile-response"]').value = '{token}';"""
            )
        logger.info("[CaptchaSolver] ✅ Token injected into page.")
    except Exception as exc:
        logger.warning(f"[CaptchaSolver] Token injection failed: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
# MANUAL FALLBACK
# ─────────────────────────────────────────────────────────────────────────────

async def _manual_solve_async(captcha_type: str) -> bool:
    """
    Async manual fallback: pause automation and wait for the user to solve
    the CAPTCHA in the browser window, then press Enter.

    Returns True if user confirmed, False if timed out.
    """
    timeout = config.CAPTCHA_WAIT_SECONDS
    print("\n" + "═" * 60)
    print(f"⚠️  CAPTCHA DETECTED ({captcha_type.upper()}) in the browser window!")
    print("   Please solve it manually, then press ENTER here.")
    print(f"   You have {timeout} seconds before the agent skips this row.")
    print("═" * 60)

    import threading
    solved = [False]

    def wait_input():
        input("")
        solved[0] = True

    t = threading.Thread(target=wait_input, daemon=True)
    t.start()

    # Poll every 0.5s instead of blocking the event loop
    elapsed = 0
    while elapsed < timeout and not solved[0]:
        await asyncio.sleep(0.5)
        elapsed += 0.5

    if solved[0]:
        logger.info("[CaptchaSolver] Manual CAPTCHA solved. Resuming.")
        alert("INFO", "CAPTCHA manually solved", {"type": captcha_type})
        print("✅ Resuming agent...\n")
        return True
    else:
        logger.warning("[CaptchaSolver] Manual CAPTCHA timeout. Skipping row.")
        alert("CRITICAL", "CAPTCHA unsolvable — manual timeout reached",
              {"type": captcha_type, "timeout": timeout})
        print("⏰ Timeout reached. Skipping this row.\n")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# PAGE UTILITIES (compatible with Playwright and Nodriver)
# ─────────────────────────────────────────────────────────────────────────────

async def _get_page_html(page) -> str:
    """Get page HTML from any async page object."""
    try:
        if hasattr(page, "content"):
            return await page.content()       # Playwright
        elif hasattr(page, "get_content"):
            return await page.get_content()   # Nodriver
    except Exception:
        pass
    return ""


async def _get_page_url(page) -> str:
    """Get current URL from any async page object."""
    try:
        if hasattr(page, "url"):
            return page.url                   # Playwright (property)
        elif hasattr(page, "target"):
            return page.target.url if hasattr(page.target, "url") else ""
    except Exception:
        pass
    return ""


def _extract_sitekey(html: str, captcha_type: str) -> Optional[str]:
    """
    Extract sitekey/data-sitekey from page HTML using regex.

    Handles reCAPTCHA, hCaptcha, and Cloudflare Turnstile variations.
    """
    patterns = [
        r'data-sitekey=["\']([^"\']+)["\']',
        r'sitekey=["\']([^"\']+)["\']',
        r'"sitekey"\s*:\s*"([^"]+)"',
        r'k=([A-Za-z0-9_\-]{20,})',
    ]
    for pattern in patterns:
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            return match.group(1)
    return None
