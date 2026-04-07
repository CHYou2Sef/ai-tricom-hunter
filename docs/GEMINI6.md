# 🧠 Anti-Detection Chrome Automation – Solution Architecture

## For AI Agents – No Bans, No CAPTCHAs

## 👤 Role

You are a **senior anti‑detection automation architect** with 15+ years of experience in web scraping, bot mitigation bypass, and browser fingerprinting. Your expertise includes Playwright, Nodriver, CDP protocols, residential proxies, and CAPTCHA solving strategies.
You do **not** write full code; you produce **clear architecture, decision matrices, and actionable task lists** for AI agents to implement later.

> **Objective:** Define a complete, production‑ready strategy that allows an AI agent to navigate Chrome browsers without triggering IP bans, security checks, blocks, or CAPTCHAs.  
> **Based on:** Playwright, Selenium, Firecrawl, Nodriver.  
> **Output format:** Clear instructions + structured tasks for Gemini3.1pro to implement.

---

## 📌 Core Principles (Do Not Violate)

1. **No WebDriver fingerprints** – Use CDP‑only tools (Nodriver, not vanilla Selenium).
2. **Residential IP rotation** – Mandatory for high‑value targets.
3. **Human‑like behavior** – Random delays, mouse movements, viewport sizes.
4. **CAPTCHA fallback** – External solver (2Captcha) as last resort.
5. **Progressive tiering** – Route targets based on protection level.

---

## 🧩 Task 1: Technology Selection (Decision Table)

| Target Type                   | Recommended Tool                                  | Reason                                        |
| ----------------------------- | ------------------------------------------------- | --------------------------------------------- |
| Internal / no protection      | Playwright (fast, WebSockets)                     | Speed, modern API                             |
| Basic anti‑bot (Cloudflare)   | Nodriver (CDP only)                               | Removes all WebDriver signatures              |
| High‑value (LinkedIn, Amazon) | Firecrawl (API) or Nodriver + residential proxies | Managed bypass or full stealth + rotating IPs |

**Your task:** For each tool, define:

- Installation method
- Launch arguments to hide automation
- How to verify it passes `bot.sannysoft.com`

---

## 🧩 Task 2: Fingerprint Randomisation (Per Session)

Each session must have **unique**:

- User‑agent (latest Chrome on Windows/macOS)
- Viewport size (random between 1366x768 and 1920x1080)
- WebGL / canvas fingerprints (injected via CDP)
- Navigator properties (`plugins`, `languages`, `platform`)

**Your task:** Create a checklist of 10 fingerprint properties to spoof, and a method to randomise them without restarting the browser.

---

## 🧩 Task 3: Proxy & IP Rotation Strategy

- Use **residential proxy pool** (BrightData, IPRoyal, or similar)
- Rotate IP after every 50 requests or when 403/429 is received
- Bind proxy per browser context (not globally)

**Your task:** Define the state machine for IP rotation (healthy → warn → ban → rotate). Include a backoff algorithm.

---

## 🧩 Task 4: Human‑Like Behaviour Layer

Mandatory delays before / after actions:

- Gaussian distribution (mean 1.5s, σ 0.5s)
- Random mouse movement (not instant click)
- Scroll with random speed

**Your task:** List all actions (click, type, submit) and specify the exact delay pattern for each.

---

## 🧩 Task 5: CAPTCHA Handling Workflow

- Detect CAPTCHA (by image presence or iframe)
- Pause automation
- Send screenshot + sitekey to 2Captcha / Capsolver
- Inject solution
- Resume with extra random delay

**Your task:** Write a decision tree for CAPTCHA types (Recaptcha v2, hCaptcha, Turnstile) and which solver to use.

---

## 🧩 Task 6: Monitoring & Logging (Anti‑Block Alerts)

Log only:

- 403 / 429 responses
- CAPTCHA occurrences
- Proxy rotation events
- Session duration before ban

**Your task:** Define three alert levels (INFO, WARN, CRITICAL) and what triggers each.

---

## ✅ Expected Output from Gemini (Final `.md`)

After receiving this prompt, Gemini 3.1 Pro will produce a **single Markdown file** containing:

1. **Architecture diagram** (text‑based or Mermaid)
2. **Step‑by‑step setup instructions** (no code – just commands, config files, environment variables)
3. **Decision matrix** for routing URLs to the right tool
4. **Testing protocol** (how to verify invisibility on real anti‑bot pages)
5. **Error recovery playbook** (what to do when a ban occurs mid‑task)

---

## 🚫 Constraints (Strict)

- No full code blocks (only pseudo‑code or configuration snippets if absolutely necessary)
- Focus on **architecture, patterns, and tasks**
- Output must be scannable (bullet points, tables, short paragraphs)
- Assume the reader (AI agent) will implement the code later based on these instructions

---

exemple of hybrid solution (not to implement but to analyze and inspect )
'''
import os
import asyncio
import time
import json
import random
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

# Mocking/Importing necessary libraries

# Note: In a real environment, ensure 'pip install firecrawl-py nodriver playwright google-genai'

from firecrawl import Firecrawl
from playwright.async_api import async_playwright
import nodriver as nd

# Global Configuration

GEMINI_MODEL = "gemini-2.5-flash-preview-09-2025"
API_KEY = "" # Environment provides this at runtime

class AutomationResponse(BaseModel):
tool_used: str
content: str
status: str
confidence: float

async def call_gemini_with_backoff(prompt: str, system_instruction: str = "") -> str:
"""
Implements Gemini API call with exponential backoff (1s, 2s, 4s, 8s, 16s).
"""
url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={API_KEY}"
payload = {
"contents": [{"parts": [{"text": prompt}]}],
"systemInstruction": {"parts": [{"text": system_instruction}]},
"tools": [{"google_search": {}}]
}

    delays = [1, 2, 4, 8, 16]
    for i, delay in enumerate(delays):
        try:
            # Using a generic request pattern for the simulation environment
            # In production: use 'import requests' or the 'google-genai' SDK
            import requests
            response = requests.post(url, json=payload)
            if response.status_code == 200:
                result = response.json()
                return result.get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text', "")
            elif response.status_code == 429:
                time.sleep(delay)
            else:
                response.raise_for_status()
        except Exception as e:
            if i == len(delays) - 1:
                return f"Error after retries: {str(e)}"
            time.sleep(delay)
    return "Failed to get response from Gemini."

class HybridAutomationEngine:
def **init**(self):
self.firecrawl = Firecrawl(api_key=os.getenv("FIRECRAWL_API_KEY", "fc-mock"))

    async def tier1_playwright(self, url: str) -> str:
        """Fast, WebSocket-based scraping for unprotected sites."""
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(url, wait_until="networkidle")
            content = await page.content()
            await browser.close()
            return content

    async def tier2_nodriver(self, url: str) -> str:
        """Stealth scraping using CDP directly (no WebDriver signatures)."""
        browser = await nd.start()
        page = await browser.get(url)
        # Wait for some content to ensure it's not a blank challenge page
        await asyncio.sleep(2)
        content = await page.get_content()
        return content

    async def tier3_firecrawl(self, url: str) -> Dict[str, Any]:
        """Managed AI-native scraping for high-protection targets."""
        return self.firecrawl.scrape(url, formats=['markdown'])

    async def execute_task(self, target_url: str, objective: str):
        """
        Main orchestration loop:
        1. Ask Gemini which tool to start with.
        2. Execute and verify.
        3. Escalate if necessary.
        """
        system_prompt = "You are an Automation Architect. Decide which tool to use: 'playwright' (internal/fast), 'nodriver' (stealth), or 'firecrawl' (hardened)."
        decision_prompt = f"Target URL: {target_url}\nObjective: {objective}\nWhich tool is best for initial attempt?"

        tool_choice = await call_gemini_with_backoff(decision_prompt, system_prompt)

        print(f"Gemini (Antigravity) Decision: {tool_choice}")

        try:
            if "firecrawl" in tool_choice.lower():
                data = await self.tier3_firecrawl(target_url)
                return data
            elif "nodriver" in tool_choice.lower():
                return await self.tier2_nodriver(target_url)
            else:
                return await self.tier1_playwright(target_url)
        except Exception as e:
            print(f"Tier failure: {e}. Escalating to Firecrawl...")
            return await self.tier3_firecrawl(target_url)

# Example Usage

if **name** == "**main**":
engine = HybridAutomationEngine()

    # Task: Extract pricing from a potentially protected site
    async def main():
        result = await engine.execute_task(
            target_url="https://www.example-shop.com/prices",
            objective="Extract the price of the latest 2026 Laptop model."
        )
        print("Final Extracted Content Sample:")
        print(str(result)[:500])

    asyncio.run(main())

'''
