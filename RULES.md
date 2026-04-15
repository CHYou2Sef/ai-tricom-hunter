# RULES.md - Hard Constraints

This document supersedes all previous rule files (e.g., CLAUDE.md, GEMINI.md). Violating these rules will cause `gitagent validate` to fail during CI/CD.

## 1. Architectural Invariants
- **Non-blocking Event Loop:** All IO must be `async` or wrapped in `asyncio.to_thread()`.
- **Pooled Browsers:** Browser agents must be pooled and returned to `_agent_pool` gracefully upon completion or failure.
- **Data Normalization:** Extracted phone numbers are ALWAYS normalized via standard parsing utilities (`normalize_phone()`).
- **Row Lifecycle:** Rows must follow strict state transitions: `PENDING` → `DONE` | `NO TEL` | `ERROR` | `SKIP`.

## 2. Security (Non-Negotiable)
- **Zero Secrets:** Never hardcode credentials, API keys, or proxies. All secrets must live in `.env` or GitHub Secrets.
- **SQLi Prevention:** Use parameterized queries or ORM equivalents for all database interactions.
- **File System Safety:** Verify file paths before read/write operations. Write output only to the specific `WORK/` directories.

## 3. Knowledge Graph integration (MCP)
- **Always check the graph before Grep/Read:** Use `semantic_search_nodes` or `query_graph` to explore the codebase.
- **Understand Impact:** Run `get_impact_radius` to see the blast radius of changes before modifying core functions like the `HybridEngine`.
- **Code Review:** Rely on `detect_changes` and `get_review_context` instead of blindly reading files.

## 4. Code Quality
- maximum function length: 50 lines (unless heavily documented and justified).
- 80% test coverage minimum for newly introduced business logic.
- Commit messages must follow the **Conventional Commits** standard (e.g., `feat:`, `fix:`, `refactor:`).
