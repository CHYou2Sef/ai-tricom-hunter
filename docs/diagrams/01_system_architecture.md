# 🏗️ Global System Architecture
**Diagram 01: Producer-Consumer Paradigm & Data Lifecycle**

*Context: This macro-architecture diagram illustrates the decoupling of ingestion (Producer) from the asynchronous AI execution engines (Consumers) via file-based state queues.*

```mermaid
graph TD
    %% Styling - MIT / Deep Tech Aesthetic
    classDef ioNode fill:#0B1F3A,stroke:#00D1FF,stroke-width:2px,color:#FFFFFF,font-family:Inter;
    classDef logicNode fill:#F5F7FA,stroke:#0B1F3A,stroke-width:2px,color:#0B1F3A,font-weight:bold,font-family:Inter;
    classDef queueNode fill:#00D1FF,stroke:#0B1F3A,stroke-width:2px,color:#0B1F3A,font-family:Inter;
    classDef dbNode fill:#1E293B,stroke:#00D1FF,stroke-width:2px,color:#FFFFFF,font-family:Inter;

    %% Elements
    A[(Raw Data Ingestion\nCSV / Excel)]:::ioNode -->|File Watcher| B(Pre-Processor Daemon\npre_process.py):::logicNode
    
    subgraph "Producer Layer (Ingestion & Sanitization)"
        B --> C{Density Inference}:::logicNode
        C -- Rich Entity --> D[Queue: std_input/]:::queueNode
        C -- Sparse Entity --> E[Queue: RS_input/]:::queueNode
        C -- Anomaly --> F[Discard/Log]:::dbNode
    end

    subgraph "Consumer Layer (Async Orchestration)"
        D & E --> G(Async Event Loop\nMain Orchestrator):::logicNode
        G --> H(Worker 1\nHeadless Chrome):::ioNode
        G --> I(Worker 2\nHeadless Chrome):::ioNode
        G --> J(Worker N\nHeadless Chrome):::ioNode
    end

    subgraph "Output & Auditing Layer"
        H & I & J --> K((Aggregator\nrow_enricher.py)):::logicNode
        K --> L[(Enriched Data\nFINAL.xlsx)]:::ioNode
        K --> M[(EEAT Ledger\nAUDIT.json)]:::dbNode
    end
```

> **Usage:** Insert this diagram into slide "# ⚙️ Data Pipeline Workflow" to visualize the async Producer-Consumer decoupling.
