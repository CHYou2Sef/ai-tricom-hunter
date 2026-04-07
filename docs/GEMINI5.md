# Prompt for Gemini 3.1 Pro – Data Collection AI Agent

## Role

You are an expert in AI agents, a senior software engineer, and an ethical hacker with 20+ years of experience. Your responses are practical, secure, and production‑ready.

## Context

I am building a **data collection AI agent** that runs 24/7 on a standard machine (Windows/Linux). The agent navigates websites, extracts data, and saves results locally. It must be resilient to failures (power loss, connection drops, file corruption) and avoid resource waste (log saturation).

## Tasks

Please provide solutions for the following four tasks. Use **Python** as the implementation language. Include code blocks and step‑by‑step explanations.

### 1. Human‑like Random Delays

- Create functions that generate realistic, random delays for:
  - Wait times after page load.
  - Timeouts between actions (click, scroll, type).
  - Intervals between file writes or checkpoints.
- Use random distributions (e.g., uniform, normal, exponential) with configurable min/max.
- Example: `human_delay(mean=1.2, std=0.5)` returning seconds.
- Show how to replace all fixed `time.sleep()` calls with these functions.

### 2. Large File Decomposition for Resilience

- The agent processes large incoming files (e.g., raw collected JSON/CSV). If a file is corrupted or the agent stops mid‑way, progress is lost.
- Design a solution that:
  - Splits large files into smaller chunks (e.g., 10 MB or 1000 records).
  - Saves metadata (chunk index, original filename, total chunks) in a sidecar file.
  - On restart, resumes from the last completed chunk.
- Provide:
  - Chunking logic (read/write).
  - Recovery function that identifies incomplete work.
  - Example of handling a power‑off scenario.

### 3. Log Saturation Prevention

- Current logging saves everything → disk fills up.
- Implement a logger that:
  - Saves **only errors and critical alerts** to the main log file.
  - Optionally saves full logs to a rotated archive (keep last 5 files of 10 MB each).
  - Does not log INFO/DEBUG/WARNING unless explicitly enabled.
- Include:
  - Python `logging` configuration code.
  - A context manager to temporarily enable verbose logging for debugging.
  - Log rotation setup (using `RotatingFileHandler`).

## Constraints

- All code must be **production‑ready** (error handling, edge cases, cleanup).
- Assume the agent runs 24/7 – avoid memory leaks, zombie processes.
- Do not use external services (offline‑first).
- Prioritize **resilience over speed**.
- Keep the main log file clean – only errors and alerts.

# Data Collection AI Agent – Technical Implementation

## 1. Human‑like Random Delays

### Functions

```python
import random, time

def get_random_delay(min_val=0.5, max_val=5.0, distribution="normal", mean=1.2, std=0.5):
    """Generates delay using Gaussian distribution to mimic human behavior."""
    if distribution == "normal":
        delay = random.gauss(mean, std)
    else:
        delay = random.uniform(min_val, max_val)
    return max(min_val, min(delay, max_val))

def human_delay(mean=1.2, std=0.5):
    """Sleep for a realistic, human-like duration."""
    time.sleep(get_random_delay(distribution="normal", mean=mean, std=std))
```

### Integration Guide

1.  **Replace `time.sleep(x)`**: Swap all hardcoded sleeps with `human_delay()`.
2.  **Configurable Behavior**: Use different means for different actions (e.g., `mean=1.2` for page loads, `mean=0.2` for keystrokes).
3.  **Statistical Realism**: Gaussian distributions prevent "heartbeat" patterns that bot-detectors identify.

## 2. Large File Decomposition

### Chunking Design

Instead of loading a massive 1GB JSON, we split it into segments of 1000 records. This limits memory usage and ensures that a crash only wastes the progress of the *current* chunk.

### Code Implementation

```python
import math, json, os

class FileChunker:
    def split_json(self, file_path, chunk_size=1000):
        with open(file_path, 'r') as f:
            data = json.load(f)
        
        num_chunks = math.ceil(len(data) / chunk_size)
        for i in range(num_chunks):
            chunk_data = data[i*chunk_size : (i+1)*chunk_size]
            with open(f"chunk_{i}.json", 'w') as out:
                json.dump(chunk_data, out)
        
        # Save sidecar metadata
        with open("progress.json", 'w') as meta:
            json.dump({"total": num_chunks, "completed": []}, meta)
```

### Recovery Mechanism

On startup, the agent reads `progress.json`. If `completed` does not contain all indices, it resumes from the first missing index.

## 3. Log Saturation Prevention

### Logging Strategy

1.  **Error Log (`agent.log`)**: Only `ERROR` and `CRITICAL` levels. Forever persistent.
2.  **Debug Archive (`debug.log`)**: Full details. Rotated every 10MB, cap at 5 files.
3.  **Dual Handler Setup**: Use two separate handlers on the root logger.

### Implementation

```python
import logging
from logging.handlers import RotatingFileHandler

def setup_resilient_logging():
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # 1. Clean error log
    err_handler = logging.FileHandler("agent.log")
    err_handler.setLevel(logging.ERROR)
    
    # 2. Rotated full logs
    rot_handler = RotatingFileHandler("debug_archive.log", maxBytes=10**7, backupCount=5)
    rot_handler.setLevel(logging.DEBUG)

    root.addHandler(err_handler)
    root.addHandler(rot_handler)
```

## Appendix: Full Integration Example

Refer to [resilient_agent_demo.py](file:///home/youssef/ai_tricom_hunter/scripts/resilient_agent_demo.py) for the complete implementation of these components working in harmony.

## Constraints Checklist

- [x] Production‑ready error handling
- [x] No external services
- [x] 24/7 safe

## Example of a Desired Code Snippet (for style)

```python
def human_delay(mean: float = 1.2, std: float = 0.5) -> None:
    import time, random
    delay = random.gauss(mean, std)
    time.sleep(max(0.1, delay))
```
