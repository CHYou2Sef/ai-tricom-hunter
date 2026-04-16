# 🧬 Semantic Data Validation and Enrichment
**Diagram 03: The Probabilistic Truth Engine**

*Context: Explains the internal communication between sub-routines when assigning missing corporate descriptors based on extracted AI strings.*

```mermaid
sequenceDiagram
    autonumber
    participant Agent as Async Worker (Agent)
    participant Extractor as field_extractor.py
    participant Truth as confidence.py
    participant Ledger as ExcelRow State
    participant Audit as writer.py (JSON)

    Agent->>Extractor: Pass Raw AI String Array (SGE, RAG, DOM)
    activate Extractor
    Extractor-->>Agent: Parse Null
    Extractor->>Extractor: Apply Regex/Micro-schema Patterning
    Extractor->>Truth: Yield Candidate Tuples (Value, Source)
    deactivate Extractor
    
    activate Truth
    Note over Truth: Calculate Effective Vector (Source Weight × Native Confidence)
    Truth-->>Truth: Schema.org JSON-LD (w=1.0) overrides DuckDuckGo (w=0.65)
    Truth->>Ledger: Mutate Row: Assign Winning Value 
    deactivate Truth
    
    activate Ledger
    Ledger->>Ledger: Update SIREN / Email / Tel attributes
    Ledger->>Audit: Append Full Contextual History
    deactivate Ledger
    
    Note over Audit: Final Output: Actionable Excel + Compliant EEAT JSON
```

> **Usage:** Useful for the Data Enrichment/Assurance section to prove data integrity and GDPR/EEAT compliance through algorithmic auditing.
