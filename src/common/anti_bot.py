"""
╔══════════════════════════════════════════════════════════════════════════╗
║  utils/anti_bot.py                                                       ║
║                                                                          ║
║  All tricks to make the agent look like a real human user:               ║
║    ✓ Random delays between actions (per-action Gaussian profiles)        ║
║    ✓ Human-like typing (character by character)                          ║
║    ✓ User-Agent rotation                                                 ║
║    ✓ CAPTCHA detection + manual pause/resume                             ║
║    ✓ CDP fingerprint bundle (WebGL, Canvas, Navigator, Viewport)         ║
║                                                                          ║
║  TASK 2 & 4 from GEMINI.md:                                              ║
║    Fingerprint Randomisation + Human-Like Behaviour Layer                ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import time
import random
import json
from typing import Union, Dict, Any, Tuple

from core import config
from core.logger import get_logger

logger = get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# USER-AGENT ROTATION
# A "User-Agent" is a string the browser sends to every website to say
# "I am Firefox on Windows" or "I am Chrome on macOS", etc.
# Bots usually have fake or missing User-Agents — rotating real ones helps.
# ─────────────────────────────────────────────────────────────────────────────

# A pool of real, recent User-Agent strings (Chrome / Chromium based)
USER_AGENT_POOL = [
    # Chrome 120 – Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",

    # Chrome 119 – macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",

    # Chrome 118 – Linux
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",

    # Edge 120 – Windows (Chromium-based, extra cover)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",

    # Chrome 121 – Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
]


def get_random_user_agent() -> str:
    """
    Return a random User-Agent string from the pool.

    BEGINNER NOTE:
        random.choice(list) picks one element at random from a list.
    """
    ua = random.choice(USER_AGENT_POOL)
    logger.debug(f"[AntiBot] Using User-Agent: {ua[:60]}...")
    return ua


# ─────────────────────────────────────────────────────────────────────────────
# HUMAN-LIKE RANDOM DELAYS
# ─────────────────────────────────────────────────────────────────────────────

def get_random_delay(
    min_val: float = 0.5,
    max_val: float = 5.0,
    distribution: str = "uniform",
    mean: float = 1.2,
    std: float = 0.5,
    lambd: float = 0.5,
) -> float:
    """
    Generate a random delay based on various statistical distributions.

    Args:
        min_val      : Minimum absolute delay (clamped)
        max_val      : Maximum absolute delay (clamped)
        distribution : "uniform", "normal" (gauss), or "exponential"
        mean         : Mean value for 'normal' distribution
        std          : Standard deviation for 'normal' distribution
        lambd        : Lambda for 'exponential' distribution (1/mean)

    Returns:
        float : The calculated delay in seconds
    """
    if distribution == "uniform":
        delay = random.uniform(min_val, max_val)
    elif distribution == "normal":
        delay = random.gauss(mean, std)
    elif distribution == "exponential":
        # Exponential distribution often models 'inter-event' times well
        delay = random.expovariate(lambd)
    else:
        # Fallback to simple uniform
        delay = random.uniform(min_val, max_val)

    # Always clamp between absolute min/max to ensure safety
    return max(min_val, min(delay, max_val))


def human_delay(
    mean: float = config.MIN_DELAY_SECONDS + 1.0,
    std: float = 1.5,
    min_sec: float = config.MIN_DELAY_SECONDS,
    max_sec: float = config.MAX_DELAY_SECONDS,
) -> None:
    """
    Sleep for a realistic, human-like duration using a Normal (Gaussian) distribution.
    This creates a "bell curve" where most delays are around the mean.

    Example: human_delay(mean=4.0, std=1.0) usually sleeps around 4s.

    BEGINNER NOTE:
        True human behavior isn't perfectly 'uniform' (e.g. exactly between 3 and 9s).
        It's usually centered around a common speed with rare fast/slow spikes.
    """
    delay = get_random_delay(
        min_val=min_sec,
        max_val=max_sec,
        distribution="normal",
        mean=mean,
        std=std
    )
    logger.debug(f"[AntiBot] Sleeping {delay:.2f}s (Gaussian delay, mean={mean})")
    time.sleep(delay)


def short_delay() -> None:
    """Quick pause (0.3 – 1.2 seconds) for small actions like clicking."""
    time.sleep(random.uniform(0.3, 1.2))


# ─────────────────────────────────────────────────────────────────────────────
# HUMAN TYPING SIMULATION
# ─────────────────────────────────────────────────────────────────────────────

def human_type(element, text: str) -> None:
    """
    Type `text` into a Selenium WebElement, one character at a time,
    with a small random delay between keystrokes.

    This mimics a real person typing at ~300 characters/minute.

    Args:
        element : Selenium WebElement (e.g. the search input box)
        text    : The string to type

    BEGINNER NOTE:
        We import selenium here only if Selenium is being used.
        The 'element' can be any object with a .send_keys() method.
    """
    if not config.HUMAN_TYPING:
        # If human typing is disabled, just send everything at once
        element.send_keys(text)
        return

    for char in text:
        element.send_keys(char)
        delay = random.uniform(
            config.TYPING_MIN_DELAY_SEC,
            config.TYPING_MAX_DELAY_SEC
        )
        time.sleep(delay)


async def human_type_async(page, selector: str, text: str) -> None:
    """
    Same as human_type() but for Playwright (async version).

    In Playwright we use page.type() which already supports delay,
    but we add our own timing for more control.

    Args:
        page     : Playwright Page object
        selector : CSS selector of the input element
        text     : The string to type
    """
    if not config.HUMAN_TYPING:
        await page.fill(selector, text)
        return

    # Playwright's built-in type() with delay in milliseconds
    delay_ms = int(
        random.uniform(
            config.TYPING_MIN_DELAY_SEC,
            config.TYPING_MAX_DELAY_SEC
        ) * 1000
    )
    await page.type(selector, text, delay=delay_ms)


# ─────────────────────────────────────────────────────────────────────────────
# CAPTCHA DETECTION AND MANUAL PAUSE
# ─────────────────────────────────────────────────────────────────────────────

# Strings that typically appear on Google/DuckDuckGo CAPTCHA pages
CAPTCHA_INDICATORS = [
    "unusual traffic",           # Google reCAPTCHA message
    "trafic inhabituel",         # French version
    "are you a robot",
    "êtes-vous un robot",
    "i'm not a robot",
    "je ne suis pas un robot",
    "verify you are human",
    "recaptcha",
    "captcha",
    "access denied",
    "blocked",
]


def is_captcha_page(page_source: str) -> bool:
    """
    Check if the current page HTML contains CAPTCHA indicators.

    Args:
        page_source : The raw HTML of the current browser page

    Returns:
        True  → CAPTCHA detected
        False → Normal page, no CAPTCHA

    BEGINNER NOTE:
        We convert everything to lowercase before checking,
        so "CAPTCHA" and "captcha" both match.
    """
    lower = page_source.lower()
    for indicator in CAPTCHA_INDICATORS:
        if indicator in lower:
            logger.warning(f"[AntiBot] CAPTCHA detected! Indicator: '{indicator}'")
            return True
    return False


def wait_for_human_captcha_solve(timeout: int = config.CAPTCHA_WAIT_SECONDS) -> bool:
    """
    Pause the agent and wait for the USER to manually solve the CAPTCHA
    in the browser window.

    The function checks every 5 seconds if the user pressed ENTER to
    signal they solved it.

    Args:
        timeout : Max seconds to wait before giving up

    Returns:
        True  → User pressed ENTER (CAPTCHA solved)
        False → Timeout reached (skipping this row)

    BEGINNER NOTE:
        In a 24/7 headless scenario you would connect this to a notification
        system (email, Telegram bot, etc.) to alert the user.
        For now, we use a simple console prompt.
    """
    print("\n" + "═" * 60)
    print("⚠️  CAPTCHA DETECTED in the browser window!")
    print("   Please solve it manually, then press ENTER here.")
    print(f"   You have {timeout} seconds before the agent skips this row.")
    print("═" * 60)

    import threading

    # Flag that the user pressed ENTER
    solved = [False]

    def wait_input():
        input("")   # blocks until user presses ENTER
        solved[0] = True

    # Run input() in a separate thread so we can timeout
    t = threading.Thread(target=wait_input, daemon=True)
    t.start()
    t.join(timeout=timeout)

    if solved[0]:
        logger.info("[AntiBot] User confirmed CAPTCHA solved. Resuming.")
        print("✅ Resuming agent...\n")
        return True
    else:
        logger.warning("[AntiBot] CAPTCHA timeout reached. Skipping row.")
        print("⏰ Timeout reached. Skipping this row.\n")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# TASK 4: PER-ACTION DELAY MATRIX  (GEMINI.md § Task 4)
# Each browser action has its own Gaussian delay profile,
# reflecting how humans differ in pause length between clicking,
# typing, submitting a form, or waiting for a page to load.
# ─────────────────────────────────────────────────────────────────────────────

def action_delay(action: str) -> None:
    """
    Sleep for a realistic duration tailored to the given browser action.

    Args:
        action : One of  "click" | "type_char" | "submit" |
                         "navigate" | "scroll" | "read_wait"

    The profile (mean, std, min, max) is read from config.ACTION_DELAY_PROFILES.
    Falls back to a generic human_delay() if the action key is unknown.

    Example:
        await page.click("#submit")
        action_delay("click")          # short human pause after clicking

        await page.goto(url)
        action_delay("navigate")       # longer pause while page loads
    """
    profile = config.ACTION_DELAY_PROFILES.get(action)
    if not profile:
        logger.debug(f"[AntiBot] Unknown action '{action}', using generic delay.")
        human_delay()
        return

    delay = get_random_delay(
        min_val=profile["min"],
        max_val=profile["max"],
        distribution="normal",
        mean=profile["mean"],
        std=profile["std"],
    )
    logger.debug(f"[AntiBot] action_delay('{action}') → {delay:.3f}s")
    time.sleep(delay)


async def action_delay_async(action: str) -> None:
    """
    Async version of action_delay() for use inside Playwright / Nodriver coroutines.

    Example:
        await page.click(selector)
        await action_delay_async("click")
    """
    import asyncio
    profile = config.ACTION_DELAY_PROFILES.get(action)
    if not profile:
        await asyncio.sleep(random.uniform(0.5, 2.0))
        return

    delay = get_random_delay(
        min_val=profile["min"],
        max_val=profile["max"],
        distribution="normal",
        mean=profile["mean"],
        std=profile["std"],
    )
    logger.debug(f"[AntiBot] async action_delay('{action}') → {delay:.3f}s")
    await asyncio.sleep(delay)


# ─────────────────────────────────────────────────────────────────────────────
# TASK 2: CDP FINGERPRINT BUNDLE  (GEMINI.md § Task 2)
# Each new browser session must have unique values for ALL 10 properties below.
# The bundle is injected via Page.addScriptToEvaluateOnNewDocument (CDP)
# so every tab and frame is covered before any JS runs.
#
# Properties spoofed (10):
#   1.  User-Agent string
#   2.  Viewport width
#   3.  Viewport height
#   4.  WebGL renderer string
#   5.  WebGL vendor string
#   6.  Canvas noise (random per-pixel offset)
#   7.  navigator.languages
#   8.  navigator.platform
#   9.  navigator.plugins count (stub)
#  10.  navigator.hardwareConcurrency
# ─────────────────────────────────────────────────────────────────────────────

def get_fingerprint_bundle() -> Dict[str, Any]:
    """
    Generate a complete, randomised fingerprint bundle for a browser session.

    Returns a dict with all 10 spoofed properties:
    {
        "user_agent": str,
        "viewport":   {"width": int, "height": int},
        "webgl_renderer": str,
        "webgl_vendor":   str,
        "canvas_noise":   float,        # 0.0001–0.002 — sub-pixel noise intensity
        "languages":      list[str],
        "platform":       str,
        "plugins_count":  int,          # always 3–7 (realistic stub)
        "hardware_concurrency": int,    # CPU core count (2,4,8,12,16)
        "device_memory":  int,          # GB (1,2,4,8)
    }
    """
    vw = random.randint(
        config.FINGERPRINT_VIEWPORT_MIN_W,
        config.FINGERPRINT_VIEWPORT_MAX_W,
    )
    vh = random.randint(
        config.FINGERPRINT_VIEWPORT_MIN_H,
        config.FINGERPRINT_VIEWPORT_MAX_H,
    )
    bundle = {
        "user_agent":           get_random_user_agent(),
        "viewport":             {"width": vw, "height": vh},
        "webgl_renderer":       random.choice(config.WEBGL_RENDERER_POOL),
        "webgl_vendor":         random.choice(config.WEBGL_VENDOR_POOL),
        "canvas_noise":         round(random.uniform(0.0001, 0.002), 6),
        "languages":            random.choice(config.NAVIGATOR_LANGUAGES_POOL),
        "platform":             random.choice(config.NAVIGATOR_PLATFORM_POOL),
        "plugins_count":        random.randint(3, 7),
        "hardware_concurrency": random.choice([2, 4, 4, 8, 8, 12, 16]),
        "device_memory":        random.choice([1, 2, 4, 4, 8]),
    }
    logger.debug(
        f"[Fingerprint] Bundle: UA=...{bundle['user_agent'][-30:]} "
        f"| {vw}×{vh} | {bundle['webgl_renderer'][:40]}"
    )
    return bundle


def build_cdp_injection_script(bundle: Dict[str, Any]) -> str:
    """
    Convert a fingerprint bundle into a JavaScript string ready for
    Page.addScriptToEvaluateOnNewDocument (CDP) or
    page.add_init_script() (Playwright).

    The script overrides all browser APIs before any page JS can read them,
    making the spoofed values appear as real hardware characteristics.

    Args:
        bundle : Output of get_fingerprint_bundle()

    Returns:
        str : Complete JS injection script
    """
    langs_json   = json.dumps(bundle["languages"])
    vendor_json  = json.dumps(bundle["webgl_vendor"])
    renderer_json = json.dumps(bundle["webgl_renderer"])

    return f"""
(function() {{
  // ── 1. User-Agent (navigator.userAgent) ──────────────────────────────
  Object.defineProperty(navigator, 'userAgent', {{
    get: () => '{bundle["user_agent"]}',
    configurable: true
  }});

  // ── 2 & 3. Viewport (screen dimensions) ─────────────────────────────
  Object.defineProperty(screen, 'width',  {{ get: () => {bundle["viewport"]["width"]} }});
  Object.defineProperty(screen, 'height', {{ get: () => {bundle["viewport"]["height"]} }});
  Object.defineProperty(screen, 'availWidth',  {{ get: () => {bundle["viewport"]["width"]} }});
  Object.defineProperty(screen, 'availHeight', {{ get: () => {bundle["viewport"]["height"] - 40} }});

  // ── 4 & 5. WebGL renderer + vendor ──────────────────────────────────
  const getParam = WebGLRenderingContext.prototype.getParameter;
  WebGLRenderingContext.prototype.getParameter = function(param) {{
    if (param === 37445) return {vendor_json};   // UNMASKED_VENDOR_WEBGL
    if (param === 37446) return {renderer_json}; // UNMASKED_RENDERER_WEBGL
    return getParam.call(this, param);
  }};

  // ── 6. Canvas noise — sub-pixel randomisation ───────────────────────
  const origToDataURL = HTMLCanvasElement.prototype.toDataURL;
  HTMLCanvasElement.prototype.toDataURL = function(type) {{
    const ctx = this.getContext('2d');
    if (ctx) {{
      const imageData = ctx.getImageData(0, 0, this.width, this.height);
      for (let i = 0; i < imageData.data.length; i += 4) {{
        imageData.data[i]     += Math.floor(Math.random() * {bundle["canvas_noise"] * 10000:.0f} / 1000);
        imageData.data[i + 1] += Math.floor(Math.random() * {bundle["canvas_noise"] * 10000:.0f} / 1000);
        imageData.data[i + 2] += Math.floor(Math.random() * {bundle["canvas_noise"] * 10000:.0f} / 1000);
      }}
      ctx.putImageData(imageData, 0, 0);
    }}
    return origToDataURL.apply(this, arguments);
  }};

  // ── 7. navigator.languages ───────────────────────────────────────────
  Object.defineProperty(navigator, 'languages', {{
    get: () => {langs_json},
    configurable: true
  }});

  // ── 8. navigator.platform ────────────────────────────────────────────
  Object.defineProperty(navigator, 'platform', {{
    get: () => '{bundle["platform"]}',
    configurable: true
  }});

  // ── 9. navigator.plugins count (stub — realistic non-zero value) ─────
  Object.defineProperty(navigator, 'plugins', {{
    get: () => {{ return {{ length: {bundle["plugins_count"]} }}; }},
    configurable: true
  }});

  // ── 10. navigator.hardwareConcurrency + deviceMemory ─────────────────
  Object.defineProperty(navigator, 'hardwareConcurrency', {{
    get: () => {bundle["hardware_concurrency"]},
    configurable: true
  }});
  Object.defineProperty(navigator, 'deviceMemory', {{
    get: () => {bundle["device_memory"]},
    configurable: true
  }});

  // ── Bonus: remove WebDriver flag (critical for Playwright) ───────────
  Object.defineProperty(navigator, 'webdriver', {{
    get: () => undefined,
    configurable: true
  }});

}})();
"""


def randomise_viewport() -> Tuple[int, int]:
    """
    Return a random (width, height) tuple within the configured bounds.
    Convenience wrapper around get_fingerprint_bundle() when only
    the viewport is needed.
    """
    return (
        random.randint(config.FINGERPRINT_VIEWPORT_MIN_W, config.FINGERPRINT_VIEWPORT_MAX_W),
        random.randint(config.FINGERPRINT_VIEWPORT_MIN_H, config.FINGERPRINT_VIEWPORT_MAX_H),
    )


def create_proxy_auth_extension(proxy_url: str, worker_id: int = 0) -> str:
    """
    Creates a temporary Chrome extension to handle proxy authentication
    (bypasses the native 'Sign In' popup).

    Args:
        proxy_url : http://user:pass@host:port
        worker_id : To isolate temporary extension folders

    Returns:
        str : Path to the created extension folder
    """
    import zipfile
    import shutil
    import os
    from pathlib import Path

    try:
        # Parse: http://user:pass@host:port
        auth_part, host_port = proxy_url.split("@")
        username, password = auth_part.replace("http://", "").replace("https://", "").split(":")
        host, port = host_port.split(":")

        manifest_json = """
        {
            "version": "1.0.0",
            "manifest_version": 2,
            "name": "Chrome Proxy Auth",
            "permissions": [
                "proxy", "tabs", "unlimitedStorage", "storage",
                "<all_urls>", "webRequest", "webRequestBlocking"
            ],
            "background": { "scripts": ["background.js"] },
            "minimum_chrome_version":"22.0.0"
        }
        """

        background_js = """
        var config = {
            mode: "fixed_servers",
            rules: {
              singleProxy: {
                scheme: "http",
                host: "%(host)s",
                port: parseInt(%(port)s)
              },
              bypassList: ["localhost"]
            }
          };
        chrome.proxy.settings.set({value: config, scope: "regular"}, function() {});
        function callbackFn(details) {
            return {
                authCredentials: {
                    username: "%(username)s",
                    password: "%(password)s"
                }
            };
        }
        chrome.webRequest.onAuthRequired.addListener(
            callbackFn, {urls: ["<all_urls>"]}, ['blocking']
        );
        """ % {"host": host, "port": port, "username": username, "password": password}

        ext_dir = Path("browser_profiles") / f"proxy_auth_ext_{worker_id}"
        if ext_dir.exists():
            try:
                shutil.rmtree(ext_dir)
            except Exception:
                pass
        ext_dir.mkdir(parents=True, exist_ok=True)

        with open(ext_dir / "manifest.json", "w") as f:
            f.write(manifest_json)
        with open(ext_dir / "background.js", "w") as f:
            f.write(background_js)

        return str(ext_dir.absolute())
    except Exception as exc:
        logger.error(f"[AntiBot] Failed to create proxy auth extension: {exc}")
        return ""
