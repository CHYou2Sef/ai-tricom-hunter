import asyncio
from infra.scrapers.agent_scraper import run_ai_spider

async def main():
    print("Running scrapy...")
    result = await run_ai_spider("https://example.com")
    print("Result:", result)

if __name__ == "__main__":
    asyncio.run(main())
