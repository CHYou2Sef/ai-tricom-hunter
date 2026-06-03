import asyncio
import sys
sys.path.append('src')
from dotenv import load_dotenv
load_dotenv()
from infra.browsers.nodriver_agent import NodriverAgent
import nodriver as nd
from core import config

async def test_sandbox_false():
    nd_path = config.CHROMIUM_BINARY_PATH
    print(f"Using path: {nd_path}")
    browser = await nd.start(
        browser_executable_path=nd_path,
        headless=True,
        sandbox=False
    )
    print("SUCCESS: Started with sandbox=False")
    browser.stop()
if __name__ == "__main__":
    asyncio.run(test_sandbox_false())

