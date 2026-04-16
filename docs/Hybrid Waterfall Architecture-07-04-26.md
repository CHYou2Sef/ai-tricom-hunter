# 🏛️ Hybrid Waterfall Architecture Explained

Your project uses a **Multi-Tier "Waterfall" Engine**. If a fast engine fails, it automatically escalates to a stealthier, slower engine.

### Tier 1: Playwright (The Racer)

- **How it works:** Uses the official `playwright` library. It is extremely fast for standard websites that don't have heavy "bot protection."
- **Status:** Currently, your engine skips this and starts at **Tier 2** by default (`HYBRID_DEFAULT_TIER = 2`) because you are targeting difficult sites like Google and LinkedIn.

### Tier 2: Nodriver (The Stealth Ghost)

- **How it works:** This is the most advanced part of your project. It talks to Chrome using raw CDP (Chrome DevTools Protocol) without the "Automation" flag that usually tells websites "Hey, I'm a bot!"
- **Status:** This is your primary engine. It is launched in **Headed mode** (visible) so it looks 100% like a human user.

### Tier 3: Crawl4AI (The Industrial Miner)

- **How it works:** A specialized engine that turns complex website code into clean Markdown. It is designed to "digest" large amounts of data for AI.
- **Status:** This kicks in only if Tier 1 and Tier 2 both fail to find a result.

# 📂 The Purpose of `@browser_profiles`

The `browser_profiles/` folder is your **Digital Fingerprint**.

### 1. Persistence (Staying Logged In)

Standard bots clear all cookies every time they start. **Your agent does not.** It saves your cookies, cache, and session data here.

- **Benefit:** If you solve a CAPTCHA or log into a site manually in the window, the agent will **stay logged in** for the next 1,000 rows.

### 2. Trust Building

Websites like Google track "Profile Age." A brand-new profile is suspicious. A profile used for 3 days with a history of searches is "Trusted." This folder builds that trust over time.

### 3. Worker Isolation

When scaling to **3 workers**, each worker gets its own folder (`Default_worker_1`, etc.) inside this directory so they can run simultaneously without crashing into each other.

# 📈 Scaling & Windows Strategy

### Scaling Performance on Linux

1.  **Disk Maintenance:** The biggest bottleneck on your Fedora system is disk space. I have added logic to clear logs, but you should periodically run `rm -rf /tmp/uc_*`.
2.  **Concurrency:** Once you confirm stability, set `MAX_CONCURRENT_WORKERS = 3` in `config.py`. This will open 3 separate browser windows.

### Moving to Windows (The Future)

Windows is actually **highly recommended** for this specific project because it handles Chrome profiles very efficiently.

- **Pathing:** In `config.py`, Change the `CHROMIUM_BINARY_PATH` to your `chrome.exe` path.
- **Stability:** Windows doesn't suffer from the "Sandbox" crashes we saw on Linux, making it much more reliable for 24/7 operation.
- **Headless Mode:** On Windows, you can more safely try `headless=True` for Playwright if you want it to run invisibly in the background.
