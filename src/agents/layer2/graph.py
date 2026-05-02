"""
Layer 2 — Social URL Fallback LangGraph Graph Definition

Graph flow:
  classify_urls → scrape_facebook  ─┐
                → scrape_linkedin  ─┤→ aggregate → validate → END (FOUND)
                → scrape_website   ─┘           → dead_letter → END

The router in _route_to_scrapers runs sequentially through source types
in priority order (facebook > linkedin > website).  For parallel scraping,
replace with langgraph.graph.Send().
"""
from langgraph.graph import StateGraph, END

from .state import Layer2State
from .nodes import (
    classify_urls_node,
    scrape_facebook_node,
    scrape_linkedin_node,
    scrape_website_node,
    aggregate_node,
    validate_node,
    dead_letter_node,
)


def _route_to_scrapers(state: Layer2State) -> str:
    """
    Sequential router: return the first scraper node that has matching URLs.
    Falls through to 'aggregate' if no URLs match any enabled source.
    """
    urls    = state.get("urls_to_scrape", [])
    enabled = set(state.get("enabled_sources", ["facebook", "linkedin", "website"]))

    for item in urls:
        src = item.get("source_type", "")
        if src in enabled:
            return f"scrape_{src}"

    return "aggregate"


def build_layer2_graph():
    """Build and compile the Layer 2 social URL fallback state machine."""
    g = StateGraph(Layer2State)

    # ── Register nodes ────────────────────────────────────────────
    g.add_node("classify_urls",   classify_urls_node)
    g.add_node("scrape_facebook", scrape_facebook_node)
    g.add_node("scrape_linkedin", scrape_linkedin_node)
    g.add_node("scrape_website",  scrape_website_node)
    g.add_node("aggregate",       aggregate_node)
    g.add_node("validate",        validate_node)
    g.add_node("dead_letter",     dead_letter_node)

    # ── Entry point ───────────────────────────────────────────────
    g.set_entry_point("classify_urls")

    # ── Route to first matching scraper (or directly to aggregate) ─
    g.add_conditional_edges(
        "classify_urls",
        _route_to_scrapers,
        {
            "scrape_facebook": "scrape_facebook",
            "scrape_linkedin": "scrape_linkedin",
            "scrape_website":  "scrape_website",
            "aggregate":       "aggregate",
        },
    )

    # ── Each scraper drains into aggregate ────────────────────────
    for scraper in ("scrape_facebook", "scrape_linkedin", "scrape_website"):
        g.add_edge(scraper, "aggregate")

    # ── Aggregate → validate ──────────────────────────────────────
    g.add_edge("aggregate", "validate")

    # ── Terminal conditional: phone found → END | not → dead_letter ─
    g.add_conditional_edges(
        "validate",
        lambda s: "END" if s.get("best_phone") else "DEAD_LETTER",
        {"END": END, "DEAD_LETTER": "dead_letter"},
    )
    g.add_edge("dead_letter", END)

    return g.compile()
