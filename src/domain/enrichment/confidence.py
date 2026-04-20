"""
enrichment/confidence.py

Source reliability scores used when multiple sources provide the same field.
Higher = more trustworthy.
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
