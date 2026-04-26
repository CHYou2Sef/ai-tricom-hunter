"""
╔══════════════════════════════════════════════════════════════════════════╗
║  infra/intelligence/ollama_client.py                                     ║
║                                                                          ║
║  Role: Local LLM gateway via Ollama (Vector-less RAG fallback).          ║
║  Tech:  Ollama REST API + AsyncClient, exponential backoff, timeout.     ║
║  Why:   Cloud extraction may fail or leak PII; local inference is free   ║
║         and keeps data on-prem.  3B models (qwen2.5:3b) fit in 8 GB RAM. ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import asyncio
import logging
from core import config

# Graceful degradation: if ollama package is absent, stub it out so imports succeed
try:
    from ollama import AsyncClient
except ImportError:
    class AsyncClient:
        def __init__(self, *args, **kwargs):
            pass
        async def generate(self, *args, **kwargs):
            return {"response": ""}

logger = logging.getLogger("OllamaClient")

class OllamaClient:
    """
    Thin wrapper around Ollama's AsyncClient.
    Handles: model selection, 60 s timeout, 3-attempt retry with backoff.
    """
    def __init__(self):
        self.model = config.OLLAMA_MODEL          # e.g. "qwen2.5:3b"
        self.base_url = config.OLLAMA_BASE_URL    # usually http://localhost:11434
        self.client = AsyncClient(host=self.base_url)

    async def complete(self, prompt: str, model: str = None) -> str:
        """
        Send a prompt to the local Ollama instance and return the text response.

        Args:
            prompt : Raw user/system prompt (already templated).
            model  : Optional override (defaults to config.OLLAMA_MODEL).

        Returns:
            Model output string, or "" on total failure.
        """
        target_model = model or self.model
        max_attempts = 3
        
        for attempt in range(max_attempts):
            try:
                # asyncio.wait_for adds a hard ceiling so a hung model
                # does not block the whole agent pipeline
                response = await asyncio.wait_for(
                    self.client.generate(model=target_model, prompt=prompt, stream=False),
                    timeout=60.0
                )
                return response.get('response', '')
            
            except asyncio.TimeoutError:
                logger.warning(f"Ollama timeout on attempt {attempt+1}/{max_attempts}")
            except Exception as e:
                logger.warning(f"Ollama error on attempt {attempt+1}/{max_attempts}: {str(e)}")
            
            # Exponential backoff: 1s → 2s → 4s before next retry
            if attempt < max_attempts - 1:
                wait_time = 2 ** attempt
                await asyncio.sleep(wait_time)
        
        logger.error(f"Ollama failed after {max_attempts} attempts.")
        return ""

# Singleton instance — imported by phone_hunter.py
ollama_client = OllamaClient()
