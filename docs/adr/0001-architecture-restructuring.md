# ADR 0001: Separation of Concerns - Pre-processing vs Crawler AI

## Context
The previous Jupyter notebook prototype had stability issues executing long-running Google data extraction inside a single blocking execution thread. File reading, cleaning, exception handling, and Playwright execution were mashed together. This caused corrupted states when the browser crashed.

## Decision
We implemented a strict two-stage architecture:
1. **Pre-processor** (`pre_process.py`): An event-driven watchdog that cleans, standardizes (SIREN padding, header detection), categorizes files, and queues them into "buckets".
2. **Crawler Agent** (`main.py` & `agent.py`): A stateless AI orchestration script that pulls from buckets and enriches them via localized DOM parsing and RAG.

## Consequences
- **Pros**: The system is resilient. If the browser fails, the uncompleted rows are not lost, and the raw source files are safely archived. Separation allows faster iteration on DOM selectors without touching Pandas/Excel mechanics.
- **Cons**: Users must run two scripts concurrently.
