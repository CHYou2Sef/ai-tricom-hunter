"""
╔══════════════════════════════════════════════════════════════════════════╗
║  domain/enrichment/confidence.py                                         ║
║                                                                          ║
║  Confidence Scoring Engine for Enrichment Fields                         ║
║                                                                          ║
║  ROLE:                                                                   ║
║    Assigns a confidence score (0.0–1.0) to each extracted field based    ║
║    on the reliability of its source.                                     ║
║                                                                          ║
║  SOURCE WEIGHTS (highest → lowest):                                      ║
║    aeo_schema   : 1.00  — structured JSON-LD from official sites         ║
║    gemini_json  : 0.90  — Google Gemini AI response in JSON format       ║
║    google_ai    : 0.75  — Google AI Overview text                        ║
║    web_scrap    : 0.60  — raw HTML scraping                              ║
║    ollama_local : 0.50  — local LLM fallback                             ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

SOURCE_WEIGHTS = {
    "aeo_schema":   1.00,   # JSON-LD structured data (Schema.org) — highest trust
    "gemini_json":  0.90,   # Gemini RAG returning clean JSON
    "google_ai":    0.75,   # Google AI Overview text (regex-extracted)
    "duckduckgo":   0.65,   # DuckDuckGo AI Chat text
    "gemini_text":  0.60,   # Gemini free-text (non-JSON response)
    "page_html":    0.45,   # Raw page HTML scrape
    "heuristic":    0.30,   # Fallback guess / pattern match on noisy text
}


def best_value(candidates: list) -> dict:
    """
    Given a list of candidates for one field:
      [{"value": "...", "source": "google_ai", "confidence": 0.75}, ...]
    Return the one with the highest effective score.
    Effective score = source_weight * field_confidence
    """
    if not candidates:
        return {}
    return max(
        candidates,
        key=lambda c: SOURCE_WEIGHTS.get(c["source"], 0.0) * c.get("confidence", 0.5)
    )
