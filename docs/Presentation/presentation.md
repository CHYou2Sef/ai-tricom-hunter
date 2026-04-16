# Style:

Minimalist Tech / Deep Tech AI Lab Research

# Colors:

Primary: Deep Blue #0B1F3A
Accent: Electric Cyan #00D1FF
Secondary: Soft Gray #F5F7FA

# Fonts:

Titles: Inter / Montserrat Bold
Body: Inter Regular

# Visual Rules:

- Apply the UI/UX Pro Max standards.
- 70% visuals / 30% text. Max 6 lines per slide.
- Use icons + diagrams over paragraphs.
- 1 slide = 1 idea. Avoid walls of text.

# Gamma Presentations Engine Instructions:

- Auto structure (12-15 slide frameworks)
- Final delivery presentation ready.

---

# 🚀 AI Tricom Hunter

### Architecting an Autonomous Multi-Agent B2B Data Enrichment Pipeline

**Final Year Engineering Project (PFE)**  
Distributed Systems & Applied AI

---

# 🚨 The Strategic Problem

**The Deterministic Bottleneck & Corporate Data Decay**

- 📉 Data degrades by ~30% annually.
- ❌ **Traditional Scraping Flaws:** Breaks instantly on UI updates.
- ❌ **Anti-Bot Systems:** Flag sequential linear scraping.
- ❌ **Monolithic Code:** High CPU load, slow sequential processing.

> _Result: High operational cost, low scalability, fractured data context._

---

# ⚠️ Existing Solutions Fall Short

| Tech Archetype                         | The Problem                                               |
| -------------------------------------- | --------------------------------------------------------- |
| **Static Data Aggregators** _(Apollo)_ | Fast, but frequently stale. Poor coverage for local SMBs. |
| **Cloud Automation** _(PhantomBuster)_ | Circumvents bot-checks but fails on DOM layout changes.   |
| **Pure LLM Generation** _(Perplexity)_ | Vulnerable to hallucinating specific arrays (SIRET, NAF). |

👉 **The Market Gap:** No system effectively marries deterministic validation with Generative AI inference at scale.

---

# 💡 The Solution

## A Bifurcated, Probabilistic Engine

Moving the paradigm from passive scraping to active context constraints:

- ✅ **Stateless Extraction:** The browser acts as a contextual sandbox, not a parser.
- ✅ **Async State Machine:** Event-driven, fault-tolerant orchestration.
- ✅ **Weighted Semantic Enrichment:** Multi-variable AI contextual synthesis.

---

# 🏗️ Global System Architecture

_Decoupled Ingestion & Asynchronous Execution_

```mermaid
graph TD
    classDef ioNode fill:#0B1F3A,stroke:#00D1FF,stroke-width:2px,color:#FFFFFF,font-family:Inter;
    classDef logicNode fill:#F5F7FA,stroke:#0B1F3A,stroke-width:2px,color:#0B1F3A,font-weight:bold,font-family:Inter;
    classDef queueNode fill:#00D1FF,stroke:#0B1F3A,stroke-width:2px,color:#0B1F3A,font-family:Inter;

    A[(Raw CSV/Excel)]:::ioNode --> B(Producer Daemon):::logicNode
    B --> C{Density Sort}:::logicNode
    C --> D[Queue: std_input]:::queueNode
    D --> E(Async Consumer Loop):::logicNode
    E --> F(Worker N: Headless Browser):::ioNode
    F --> G((EEAT Data Synthesis)):::logicNode
```

👉 Complete separation of File IO, Extraction, and State Persistence.

---

# 🧠 Generative Extraction Cascade Engine

_Hierarchical fallback strategies optimizing accuracy against computational costs._

```mermaid
flowchart LR
    classDef optimal fill:#0284C7,stroke:#38BDF8,stroke-width:2px,color:#FFFFFF;
    classDef fallback fill:#475569,stroke:#94A3B8,stroke-width:2px,color:#FFFFFF;

    A((Target)) --> B{Tier 0: Force SGE AI}:::optimal
    B -- Unavailable --> C{Tier 1: JSON-LD Graph}:::optimal
    C -- Unavailable --> D[Tier 2: Regex / Deep Scraping]:::fallback
    D --> E{Tier 3: Gemini RAG Injection}:::fallback
    E --> F((Output Excel Array))
```

👉 Never fails silently. The engine negotiates down to the most probabilistic model.

---

# 🧬 Semantic Data Validation

_The Probabilistic Truth Architecture._

- Extracted AI Strings often conflict. How does the machine decide?
- **Weighted Trust System:**
  - `Schema.org JSON-LD` = Weight 1.0
  - `Google AI Output` = Weight 0.75
  - `Deep DOM Guess` = Weight 0.30

👉 The orchestrator mathematically overrides low-confidence data with high-authority vectors.

---

# 🧪 The Technology Stack

Engineered for the Distributed Era:

- 🐍 **Python 3.x:** De-facto for AI/Data manipulation.
- ⚡ **Asyncio:** Lightweight concurrency. Eliminates RAM-bloat of multiprocessing.
- 🌐 **Chrome Playwright CDP:** Circumvents browser fingerprinting.
- 🧠 **Google Gemini API:** Utilized strictly as a bounded data formatter (RAG constraints), eliminating hallucinations.

---

# 📈 Impact & Performance

_Matrix: Sync Monolith vs Async Multi-Agent Array_

| Metric                  | "Day 0" Execution       | Current State Architecture   |
| ----------------------- | ----------------------- | ---------------------------- |
| **Max Concurrency**     | 1 Node (High RAM Block) | 25+ Nodes (Async WebSocket)  |
| **Extraction Fidelity** | ~45%                    | **>88%**                     |
| **Crash Recovery**      | Manual Readjustment     | Atomic Excel Data Check      |

⚡ Massive performance gain. Infinite continuity.

---

# 🛡️ Observability & EEAT Compliance

- **Threat Profiling:** Protected against Prompt-Injections (XSS-PI) via strict formatting limits.
- **Enterprise Ledger:** The output mapping explicitly registers the state of every variable.
  - _Strict `Etat_IA` Validation_
  - _Direct Excel Output Indexing_
  - _Mathematical Confidence Threshold_

👉 Absolute traceability for compliance and analytics.

---

# 🚀 The Next Horizon (Future Scope)

_Scaling to OS-Agnostic Topologies via Docker & Redis._

```mermaid
graph LR
    classDef docker fill:#E1F5FE,stroke:#0277BD,color:#01579B,font-family:Inter;
    classDef state fill:#FFF3E0,stroke:#E65100,color:#E65100,font-family:Inter;

    A[Master Node API]:::docker -->|Push| B[(Redis State Queue)]:::state
    C(Worker Node Alpha):::docker <-->|Pop & Ack| B
    D(Worker Node Beta):::docker <-->|Pop & Ack| B
```

- Replaces local `watchdog` with persistent distributed graphs.
- Decouples CPU scraping into `browserless/chrome` pods.

---

# 🎓 Conclusion

- The deterministic web is fading.
- **AI Tricom Hunter** proves contextual ML scraping solves structural breakages.

## Achievement:

✔ Fault-Tolerant Asynchronous Execution  
✔ Generative AI utilized purely for logic inference  
✔ Industrial-grade compliance and state recovery

---

# 🙏 Thank You

**Questions & Deep Dives?**
