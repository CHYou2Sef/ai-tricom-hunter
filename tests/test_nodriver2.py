import asyncio
import os
import nodriver as nd
import sys
sys.path.append('src')
from core.config import CHROMIUM_BINARY_PATH

async def main():
    try:
        print(f"CHROMIUM_BINARY_PATH: {CHROMIUM_BINARY_PATH}")
        browser = await nd.start(
            browser_executable_path=CHROMIUM_BINARY_PATH if CHROMIUM_BINARY_PATH else None,
            headless=True,
            sandbox=False
        )
        print("Successfully started nodriver")
        browser.stop()
    except Exception as e:
        print(f"Error: {e}")

asyncio.run(main())
