# Agent Behavior Specification
## PhoneHunterAgent
- PRIMARY path: AI Mode search → JSON parse → phone extract
- FALLBACK 1: Knowledge Panel (UUE heuristic)
- FALLBACK 2: Domain scrape → local Ollama GEO extraction
- SKIP condition: row already DONE in progress tracker
- RETRY condition: config.REPROCESS_FAILED_ROWS = True
## HybridEngine waterfall
Tier 1 (Patchright) → Tier 2 (Nodriver) → Tier 3 (Crawl4AI) → Tier 4 (Camoufox)
Each tier: start → execute → if None → stop → cool 5s → next tier
Circuit breaker: 5 consecutive total failures → pause 300s → proxy rotate
## Enricher
Source priority: google_ai_mode (0.97) > aeo_schema (1.00) > gemini_json (0.90)
Never overwrite field with existing non-empty value
