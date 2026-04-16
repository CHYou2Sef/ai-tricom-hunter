# Migration to Async Playwright Architecture

This plan aims to resolve the "Cannot switch to a different thread" error by migrating the entire processing pipeline from a multi-threaded synchronous model to a single-threaded asynchronous model using `asyncio` and `async_playwright`.

## User Review Required

> [!IMPORTANT]
> This is a significant architectural shift. All primary processing functions ([process_row](file:///home/youssef/ai_tricom_hunter/agent.py#192-269), [process_file](file:///home/youssef/ai_tricom_hunter/agent.py#396-469), [main](file:///home/youssef/ai_tricom_hunter/main.py#198-308)) will become asynchronous. This improves performance and stability but requires `asyncio.run()` as the entry point.

## Proposed Changes

### [Component] Browser Engine
#### [MODIFY] [playwright_agent.py](file:///home/youssef/ai_tricom_hunter/browser/playwright_agent.py)
- Switch from `playwright.sync_api` to `playwright.async_api`.
- Convert [start](file:///home/youssef/ai_tricom_hunter/browser/playwright_agent.py#82-111), `stop`, [search_google_ai](file:///home/youssef/ai_tricom_hunter/browser/playwright_agent.py#206-234), [submit_google_search](file:///home/youssef/ai_tricom_hunter/browser/playwright_agent.py#235-259), and helper methods to `async def`.
- Implement `await` for all browser interactions.

---

### [Component] Core Agent Logic
#### [MODIFY] [agent.py](file:///home/youssef/ai_tricom_hunter/agent.py)
- Convert [process_row](file:///home/youssef/ai_tricom_hunter/agent.py#192-269) and [process_file](file:///home/youssef/ai_tricom_hunter/agent.py#396-469) to `async def`.
- Replace `ThreadPoolExecutor` with `asyncio.Semaphore(MAX_CONCURRENT_WORKERS)` to manage parallel row processing without OS threads.
- Use `asyncio.gather` to execute multiple rows concurrently.

---

### [Component] Entry Point
#### [MODIFY] [main.py](file:///home/youssef/ai_tricom_hunter/main.py)
- Refactor the main loop to be `async`.
- Use `asyncio.run(main())` for the application start.
- Update the watchdog handler to integrate with the `asyncio` event loop.

## Verification Plan

### Automated Tests
- Create a new test file `tests/test_async_agent.py` to verify async row processing with a mocked browser agent.
- Run with: `pytest tests/test_async_agent.py -v`

### Manual Verification
1. **Concurrency Check**: Run `python main.py` and verify in logs that multiple rows are being processed (e.g. "Processing row #1", "Processing row #2" appearing close together) without thread errors.
2. **Success Rate**: Verify that at least one "DONE" status is achieved in the output JSON for a known company (e.g. "Google" or "Microsoft").
3. **Shutdown**: Verify that `Ctrl+C` still performs a clean shutdown and saves partial results.
