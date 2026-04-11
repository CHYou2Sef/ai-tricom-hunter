# AI Phone Hunter — Project Rules for Claude Code
## Stack: Python 3.10+, async/await, Patchright, Ollama, SQLite
## Key invariants:
- Never block the event loop: all IO is async or asyncio.to_thread()
- Browser agents are pooled: always return agent to _agent_pool
- Secrets live in .env only: never hardcode credentials
- Logs go through utils/logger.py get_logger(__name__)
- Phone numbers are always normalized via normalize_phone()
- Row status lifecycle: PENDING → DONE | NO TEL | SKIP
## Architecture layers (top to bottom):
Entry → Orchestration → Intelligence → LLM → Browser → Extract → Storage
## Token budget: use caveman prompt style for all internal LLM calls
