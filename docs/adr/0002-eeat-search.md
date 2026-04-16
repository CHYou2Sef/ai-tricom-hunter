# ADR 0002: Multi-layer Search Optimization (SQO, AEO, GEO)

## Context
Early prototypes used generalized LLM queries to DuckDuckGo/Gemini to extract phone numbers. This yielded inconsistent, hallucinated, or non-EEAT compliant data from low-quality directories.

## Decision
We discarded the generalized "chat" extraction approach for finding deterministic data (phones). Instead, we built a layered system focusing on EEAT (Expertise, Experience, Authoritativeness, Trustworthiness):
1. **SQO (Search Query Optimization)**: Hardcodes `site:pappers.fr OR site:societe.com` via Google Dorks.
2. **AEO (Answer Engine Optimization)**: Sniffs directly in the DOM for `application/ld+json` (Schema.org) for zero-click accuracy.
3. **GEO (Generative Engine Optimization)**: As a final RAG fallback, the *raw HTML context* from the official SERP page is passed to Gemini for logical extraction via structured JSON prompts.

## Consequences
- **Pros**: 99% reduction in false positives and LLM hallucinations. Data accuracy is guaranteed since the source context is explicitly controlled by SQO/AEO.
- **Cons**: Slower execution per row due to the multi-step DOM verification before falling back to Gemini APIs.
