# Optimization & Performance Scaling Plan

This plan aims to execute on the architectural vision by adding precise performance metrics, optimizing the core code to scale (pre-processing to output), and preparing the architecture for Langchain integration and asynchronous distributed scraping.

## Proposed Changes

### Core Metrics & Performance Tracking
We will introduce a robust metrics tracker to exactly measure the performance bottleneck and success rates.

#### [NEW] `utils/metrics.py`
Create a new module to handle performance calculation.
- Track `start_time` and `end_time` at both the row-level and file-level.
- Calculate:
  - **Total execution time** per file.
  - **Success rate**: `% de lignes "DONE"`.
  - **Speed**: Average time per row processed.
- Provide a formatted console report & write metrics to the final Excel/JSON file.

#### [MODIFY] [agent.py](file:///home/youssef/ai_tricom_hunter/agent.py)
- Integrate `utils.metrics` into [process_file()](file:///home/youssef/ai_tricom_hunter/agent.py#365-438).
- Record performance for each row and output the consolidated metrics report at the end of the file.
- **Architectural decoupling:** Refactor [process_row()](file:///home/youssef/ai_tricom_hunter/agent.py#176-260) to isolate the specific browser logic from the "decision making" logic, preparing the ground for Langchain agents (where an LLM Agent will dynamically select tools rather than running a rigid sequence).
- Implement an **async-ready wrapper structure** for batch processing. This moves away from the strictly sequential processing to a `chunk/batch` model based on `ThreadPoolExecutor` or `asyncio.gather()`, paving the way for distributed queues (Redis) and concurrent HTTPX/Crawl4AI scraping.

---

### Pre-Processing Optimizations

#### [MODIFY] [pre_process.py](file:///home/youssef/ai_tricom_hunter/pre_process.py)
- **Batch Mode:** Optimize the `clean_and_classify` flow so that it evaluates rows entirely in memory before doing heavy I/O operations.
- Introduce concurrent execution for pre-processing multiple Excel files in parallel instead of one by one.
- Simplify file movement (archive/ready) taking advantage of `shutil.move` in non-blocking threads to prevent watchdog hanging.

---

### Langchain & Output Data Structure Preparation

#### [MODIFY] [config.py](file:///home/youssef/ai_tricom_hunter/config.py)
- Add settings for `LANGCHAIN_ENABLED` (placeholder for next step).
- Add settings for `MAX_CONCURRENT_WORKERS` to control the multi-threading/async scale-up limit (defaulting to 3 to start).

#### [MODIFY] [excel/writer.py](file:///home/youssef/ai_tricom_hunter/excel/writer.py) (Output Files Structure)
- Adjust the output format to include a sheet/metadata block for the **Performance Metrics**.
- Ensure the data structure (JSON audits) is fully decoupled and ready for a Document Store / Vector DB approach (which Langchain often utilizes).

## Verification Plan

### Automated / Code-level Tests
- **Metrics Accuracy:** Run [agent.py](file:///home/youssef/ai_tricom_hunter/agent.py) against a sample file and verify that the console outputs: total elapsed time, average row processing time, and the exact `% of "DONE"` lines. Check the destination Excel file for the new Performance metadata. 
- **Pre-processor Speed:** Run [pre_process.py](file:///home/youssef/ai_tricom_hunter/pre_process.py) manually with multiple dummy excel files and benchmark the processing time compared to the previous version. Run `python pre_process.py` to ensure no syntax/runtime regressions.

### User Review Required
> [!IMPORTANT]
> The current system uses stateful browsers (Playwright/Selenium) which have high RAM requirements. As a first step to scaling, I will optimize the Python logic to process rows using multithreading (ThreadPoolExecutor) limited by `MAX_CONCURRENT_WORKERS`.
> 
> Later, when shifting completely to `Crawl4AI/Redis`, the architecture prepared here will easily adapt to a fully stateless distributed model. Does this approach align with your vision for Langchain integration?
