# 🏹 Project AI-Tricom Hunter: Next-Gen Architecture

This document provides a comprehensive overview of the new, industrialized system architecture for **AI-Tricom Hunter**. We've transitioned from a single-tier scraping script to a resilient, multi-agent AI engine designed for 24/7 autonomous operation.

---

## 🖼️ System Architecture Diagram (2026)

![System Architecture 2026](/home/youssef/ai_tricom_hunter/docs/images/System_Architecture_2026.svg)

> [!NOTE]
> The SVG above is fully vector-based and can be rendered in any modern browser for maximum clarity.

---

## 🛠️ The Three-Phase Workflow

### 1. Phase 1: Pre-Processor (The Gatekeeper)
The entry point of the system is `pre_process.py`, which acts as a strictly logical, non-AI filter to prepare data for the agent.

*   **File Decomposition (`FileChunker`)**: Large files (Excel/CSV/JSON) are automatically split into manageable chunks.
*   **Safety sidecars**: Every chunk generates a metadata sidecar. If the system crashes, it knows exactly which rows were processed, allowing for **zero-loss recovery**.
*   **Difficulty Bucketing**:
    *   **SIR Bucket**: Rows with SIRET + Name (Direct hits).
    *   **STD Bucket**: Rows with Name + Address (Standard search).
    *   **RS/Other Bucket**: Rows requiring "Expert Researcher" deep dives.

### 2. Phase 2: The Hunter (The Hybrid Brain)
This is the core execution engine (`main.py` + `HybridAutomationEngine`).

*   **Hybrid Waterfall Engine**:
    *   **Tier 1 (Playwright)**: Fast, high-scale scraping for standard sites.
    *   **Tier 2 (Nodriver)**: Advanced stealth mode to bypass Cloudflare and WAF protections.
    *   **Tier 3 (Crawl4AI)**: Hardened target extraction with LLM-ready markdown conversion.
*   **Expert Researcher (Tier 0)**: A recursive AI loop that handles the most difficult leads by cross-referencing multiple data sources.
*   **Anti-Detection Mechanisms**: Real-time **Gaussian random delays** simulate human interaction patterns to prevent IP bans.

### 3. Phase 3: The Harvest (Output Fulfillment)
The final stage ensures data persistence and archival.

*   **Resilient Output**: Results are written using a dictionary-mapping strategy to prevent column misalignment.
*   **Success vs. failure**: Rows are routed to `Archived_Results/` or `Archived_Failed/`.
*   **Dual-Logging**: A comprehensive logging system separates transient debug data (rotated) from critical persistent errors.

---

## 🚀 How to Start from Scratch

### Step 1: Initialize Environment
Ensure all directories are ready and configs are set.
```bash
python main.py --setup  # Creates dirs and validates API keys
```

### Step 2: Start Listeners (Terminal A)
Launch the pre-processor to watch for incoming data.
```bash
python pre_process.py
```

### Step 3: Run the Agent (Terminal B)
Start the main processing brain.
```bash
python main.py
```

---

> [!TIP]
> **Pro-Tip**: You can monitor the system health in real-time by checking the `Hybrid Engine Performance Report` printed in the terminal after each chunk completion.
