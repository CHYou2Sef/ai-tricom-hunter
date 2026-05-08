import asyncio
import os
import nodriver as nd

async def main():
    try:
        browser = await nd.start(
            headless=True,
            sandbox=False
        )
        print("Successfully started nodriver")
        browser.stop()
    except Exception as e:
        print(f"Error: {e}")

asyncio.run(main())
