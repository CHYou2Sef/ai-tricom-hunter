import os
import sys
import asyncio
import aiohttp
from dotenv import load_dotenv

# Ensure we can load from src
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))
from core import config

# Load environment variables
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

# Formatting helpers
RESET = "\033[0m"
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"

async def test_openrouter(session):
    key = os.getenv("OPENROUTER_API_KEY")
    if not key or key == "your_openrouter_api_key_here": return "SKIPPED (No Key)"
    
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    payload = {"model": "meta-llama/llama-3-8b-instruct", "messages": [{"role": "user", "content": "Hi"}], "max_tokens": 1}
    
    try:
        async with session.post(url, headers=headers, json=payload, timeout=10) as resp:
            if resp.status == 200:
                return f"{GREEN}✅ OK (200){RESET}"
            elif resp.status in (401, 403):
                return f"{RED}❌ Unauthorized (Invalid Key){RESET}"
            else:
                return f"{YELLOW}⚠️ HTTP {resp.status}{RESET}"
    except Exception as e:
        return f"{RED}❌ Error: {e}{RESET}"

async def test_groq(session):
    key = os.getenv("GROQ_API_KEY")
    if not key or "your_groq" in key: return "SKIPPED (No Key)"
    
    url = "https://api.groq.com/openai/v1/models"
    headers = {"Authorization": f"Bearer {key}"}
    try:
        async with session.get(url, headers=headers, timeout=10) as resp:
            if resp.status == 200:
                return f"{GREEN}✅ OK (200){RESET}"
            elif resp.status in (401, 403):
                return f"{RED}❌ Unauthorized (Invalid Key){RESET}"
            else:
                return f"{YELLOW}⚠️ HTTP {resp.status}{RESET}"
    except Exception as e:
        return f"{RED}❌ Error: {e}{RESET}"

async def test_firecrawl(session):
    key = os.getenv("FIRECRAWL_API_KEY")
    if not key or "your_firecrawl" in key: return "SKIPPED (No Key)"
    
    # We use v1 scrape endpoint just to check auth
    url = "https://api.firecrawl.dev/v1/scrape"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    payload = {"url": "https://example.com"}
    
    try:
        async with session.post(url, headers=headers, json=payload, timeout=10) as resp:
            if resp.status == 200:
                return f"{GREEN}✅ OK (200){RESET}"
            elif resp.status in (401, 403):
                return f"{RED}❌ Unauthorized (Invalid Key or Out of Credits){RESET}"
            else:
                return f"{YELLOW}⚠️ HTTP {resp.status}{RESET}"
    except Exception as e:
        return f"{RED}❌ Error: {e}{RESET}"

async def test_jina(session):
    key = os.getenv("JINA_API_KEY")
    if not key or "your_jina" in key: return "SKIPPED (No Key - Public Mode)"
    
    url = "https://r.jina.ai/https://example.com"
    headers = {"Authorization": f"Bearer {key}"}
    try:
        async with session.get(url, headers=headers, timeout=10) as resp:
            if resp.status == 200:
                return f"{GREEN}✅ OK (200){RESET}"
            elif resp.status in (401, 402, 403):
                return f"{RED}❌ Unauthorized (Invalid Key){RESET}"
            else:
                return f"{YELLOW}⚠️ HTTP {resp.status}{RESET}"
    except Exception as e:
        return f"{RED}❌ Error: {e}{RESET}"

async def test_neutrino(session):
    user_id = os.getenv("NEUTRINO_USER_ID")
    api_key = os.getenv("NEUTRINO_API_KEY")
    if not api_key or not user_id or "your_" in api_key: return "SKIPPED (No Key)"
    
    url = "https://neutrinoapi.net/phone-validate"
    headers = {"user-id": user_id, "api-key": api_key}
    params = {"number": "+33612345678"}
    try:
        async with session.get(url, headers=headers, params=params, timeout=10) as resp:
            data = await resp.json()
            if resp.status != 200 or "api-error" in data:
                return f"{RED}❌ Error: {data.get('api-error-msg', 'Invalid Key/User')}{RESET}"
            return f"{GREEN}✅ OK (200) - Type: {data.get('type', 'Unknown')}{RESET}"
    except Exception as e:
        return f"{RED}❌ Error: {e}{RESET}"

async def main():
    print(f"\n{CYAN}=================================================={RESET}")
    print(f"{CYAN}        AI TRICOM HUNTER - API HEALTH CHECK       {RESET}")
    print(f"{CYAN}=================================================={RESET}\n")
    
    async with aiohttp.ClientSession() as session:
        print(f"Testing {CYAN}OpenRouter API{RESET} (LLM Parser) ... ", end="", flush=True)
        print(await test_openrouter(session))
        
        print(f"Testing {CYAN}Groq API{RESET}       (Debugger)   ... ", end="", flush=True)
        print(await test_groq(session))
        
        print(f"Testing {CYAN}Firecrawl API{RESET}  (Tier 6)     ... ", end="", flush=True)
        print(await test_firecrawl(session))
        
        print(f"Testing {CYAN}Jina AI API{RESET}    (Tier 7)     ... ", end="", flush=True)
        print(await test_jina(session))
        
        print(f"Testing {CYAN}Neutrino API{RESET}   (Validation) ... ", end="", flush=True)
        print(await test_neutrino(session))
        
    print(f"\n{CYAN}=================================================={RESET}\n")

if __name__ == "__main__":
    # Workaround for some Windows/Linux asyncio loops
    if sys.platform.startswith('win'):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
