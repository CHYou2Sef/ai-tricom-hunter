# Phase 2 Implementation Plan: Docker, Redis & QA Standardization

This plan details the transition from a local, multi-threaded script (Phase 1) to a fully distributed, testing-hardened, containerized architecture (Phase 2). This architecture directly supports the end goal of a Multi-Agent system by establishing a clean separation between the Orchestrator (Watchdog), the Broker (Redis), and the Workers (Agent).

---

## 1. Quality Assurance & Test Tooling (Pre-QA Agent)
Before we shift to a complex distributed architecture, we must lock down code quality. We will establish a rigorous traditional QA pipeline. 

### [NEW] Tooling to Add to [requirements.txt](file:///home/youssef/ai_tricom_hunter/requirements.txt)
- **Linting & Formatting:** `ruff` (blazing fast linter) and `black` (opinionated formatter).
- **Unit Testing Validation:** `pytest-cov` to track our test coverage percentage.
- **Cross-Version Testing:** `tox` to verify the module runs safely if Python versions shift.

### [NEW] `tests/test_phase2.py`
We will create dedicated Mock-based tests to simulate Redis queues and prevent regressions before we even build the Docker images.
- Test that Redis tasks can be queued without a real server present (using `fakeredis` or mocks).
- Test the Docker config loading behavior.

---

## 2. Docker Containerization Architecture

We will make the project 100% OS-Agnostic without requiring local installations of Chromium or Playwright on the host machine.

### [NEW] `Dockerfile`
A lean Python image (e.g., `python:3.11-slim`) that:
- Installs the Python requirements.
- Copies the AI Tricom Hunter codebase.
- Serves as the base for Orchestrator and Worker instances.

### [NEW] `docker-compose.yml`
This file will orchestrate the entire Phase 2 stack locally:
- `redis-broker`: Standard Redis image (Alpine).
- `orchestrator`: Runs [pre_process.py](file:///home/youssef/ai_tricom_hunter/pre_process.py) and pushes discovered jobs to the Redis queue.
- `worker-1`: Runs [agent.py](file:///home/youssef/ai_tricom_hunter/agent.py) as a consumer listening to the Redis queue.
- `browserless`: A central `browserless/chrome` or `selenium/standalone-chromium` container. The agents will execute Playwright scripts via a WebSocket connection to this container, ensuring no host drivers are necessary.

---

## 3. Redis Task Queue Integration

### [MODIFY] [requirements.txt](file:///home/youssef/ai_tricom_hunter/requirements.txt)
- Add `redis` and `rq` (Redis Queue - simple and pythonic).

### [MODIFY] [config.py](file:///home/youssef/ai_tricom_hunter/config.py)
- Add settings for `REDIS_URL` (defaulting to `redis://localhost:6379/0`).
- Add settings for `BROWSER_WS_ENDPOINT` for containerized browser connections.

### [MODIFY] [pre_process.py](file:///home/youssef/ai_tricom_hunter/pre_process.py) (The Orchestrator)
- Instead of just moving the files to `ready_to_process`, the Orchestrator will enqueue a task to Redis: `queue.enqueue(process_file, filepath)`.

### [MODIFY] [agent.py](file:///home/youssef/ai_tricom_hunter/agent.py) & [main.py](file:///home/youssef/ai_tricom_hunter/main.py) (The Workers)
- Convert the script into an `rq` worker listening to the queue.
- Instead of using a local `ThreadPoolExecutor`, concurrency will be achieved simply by spinning up `worker-2`, `worker-3` via Docker Compose (true horizontal scaling).

---

## User Review Required
> [!IMPORTANT]
> The introduction of `RQ` and `Redis` fundamentally shifts the architecture from a "monolithic loop" to a **Pub/Sub Microservice Model**. 
> - Is `RQ` acceptable, or do you prefer `Celery` (heavier, but more robust for enterprise)? 
> - Are you comfortable moving the browser execution to a centralized Docker container (Browserless), which eliminates local browser popups?
