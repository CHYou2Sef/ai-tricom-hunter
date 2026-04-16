# 🧠 Generative Extraction Cascade Engine
**Diagram 02: Heuristic Fallback & Cost-Optimization Routing**

*Context: This flowchart details the decision matrix the extraction agent uses to balance highest-accuracy/lowest-cost queries against probabilistic fallback generations.*

```mermaid
flowchart TD
    %% Styling - MIT / Deep Tech Aesthetic
    classDef initNode fill:#0B1F3A,stroke:#00D1FF,stroke-width:2px,color:#FFFFFF,font-family:Inter,font-weight:bold;
    classDef optimalNode fill:#0284C7,stroke:#38BDF8,stroke-width:2px,color:#FFFFFF,font-family:Inter;
    classDef fallbackNode fill:#475569,stroke:#94A3B8,stroke-width:2px,color:#FFFFFF,font-family:Inter;
    classDef failureNode fill:#7F1D1D,stroke:#FCA5A5,stroke-width:2px,color:#FFFFFF,font-family:Inter;
    classDef validationNode fill:#047857,stroke:#34D399,stroke-width:2px,color:#FFFFFF,font-family:Inter;

    A[Target Entity Initiated\nName + Geospatial Bound]:::initNode --> B{Force Google SGE\nudm=50}:::optimalNode
    
    B -- AI JSON Delivered --> V((Validation Regex)):::validationNode
    B -- SGE Unavailable --> C{Knowledge Panel Probe\ndata-dtype='d3ph'}:::optimalNode
    
    C -- Exact Match Found --> V
    C -- Node Null/Missing --> D[Deep DOM Text Scraping\nTop 3 Domain URLs]:::fallbackNode
    
    D --> E{Gemini RAG Inference\nZero-Shot Structuring}:::fallbackNode
    
    E -- Synthesis Success --> V
    E -- Hallucination / Target Null --> F[Register as NON_TROUVE\nTrigger Chunk Retry]:::failureNode
    
    V -->|Probability > 85%| G[Commit Vector Array\nto Active Memory]:::initNode
    V -->|Math/Logic Failure| F
```

> **Usage:** Insert this logic map into slide "# 🧠 Core Innovation" to illustrate the cascading safety net and why the system does not fail silently.
