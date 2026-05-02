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

## MCP Tools: code-review-graph

**IMPORTANT: This project has a knowledge graph. ALWAYS use the
code-review-graph MCP tools BEFORE using Grep/Glob/Read to explore
the codebase.** The graph is faster, cheaper (fewer tokens), and gives
you structural context (callers, dependents, test coverage) that file
scanning cannot.

### When to use graph tools FIRST

- **Exploring code**: `semantic_search_nodes` or `query_graph` instead of Grep
- **Understanding impact**: `get_impact_radius` instead of manually tracing imports
- **Code review**: `detect_changes` + `get_review_context` instead of reading entire files
- **Finding relationships**: `query_graph` with callers_of/callees_of/imports_of/tests_for
- **Architecture questions**: `get_architecture_overview` + `list_communities`

Fall back to Grep/Glob/Read **only** when the graph doesn't cover what you need.

### Key Tools

| Tool                        | Use when                                               |
| --------------------------- | ------------------------------------------------------ |
| `detect_changes`            | Reviewing code changes — gives risk-scored analysis    |
| `get_review_context`        | Need source snippets for review — token-efficient      |
| `get_impact_radius`         | Understanding blast radius of a change                 |
| `get_affected_flows`        | Finding which execution paths are impacted             |
| `query_graph`               | Tracing callers, callees, imports, tests, dependencies |
| `semantic_search_nodes`     | Finding functions/classes by name or keyword           |
| `get_architecture_overview` | Understanding high-level codebase structure            |
| `refactor_tool`             | Planning renames, finding dead code                    |

### Workflow

1. The graph auto-updates on file changes (via hooks).
2. Use `detect_changes` for code review.
3. Use `get_affected_flows` to understand impact.
4. Use `query_graph` pattern="tests_for" to check coverage.
