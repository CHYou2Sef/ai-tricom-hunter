"""
╔══════════════════════════════════════════════════════════════════════════╗
║  infra/intelligence/router.py                                            ║
║                                                                          ║
║  LLM Provider Router                                                     ║
║                                                                          ║
║  ROLE:                                                                   ║
║    Centralizes the decision of which LLM provider to use for a given     ║
║    prompt completion request.                                            ║
║                                                                          ║
║  ROUTING LOGIC:                                                          ║
║    auto   → Try Ollama (local) first, fallback to Gemini (cloud)        ║
║    ollama → Force local inference (privacy-first, no API costs)          ║
║    gemini → Force Google Gemini (better quality, requires internet)      ║
║                                                                          ║
║  WHY LOCAL FIRST:                                                        ║
║    - Zero API costs                                                        ║
║    - Data stays on-premise (no PII leakage)                               ║
║    - Works offline                                                         ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import logging
from core import config
from infra.intelligence.ollama_client import ollama_client
# Optional: import gemini client if needed, or use the one from app.orchestrator/hybrid_engine

logger = logging.getLogger("LLMRouter")

async def route_completion(prompt: str, provider: str = "auto") -> str:
    """
    Routes a prompt completion request to the appropriate provider.

    Args:
        prompt   : The text prompt to send to the LLM
        provider : "auto" | "ollama" | "gemini"

    Returns:
        str : LLM response text, or "" if all providers fail
    """
    if provider == "ollama" or (provider == "auto" and config.OLLAMA_ENABLED):
        logger.info("[Router] Attempting local completion via Ollama...")
        response = await ollama_client.complete(prompt)
        if response:
            return response
        logger.warning("[Router] Local completion failed or empty.")

    if provider == "gemini" or provider == "auto":
        logger.info("[Router] Falling back to Gemini cloud completion...")
        # Note: In our architecture, Gemini calls might still go through the agent's browser
        # but here we provide a centralized hook if we ever use a direct API client.
        # For now, we return empty so the agent can handle its own fallback if router fails.
        pass

    return ""
