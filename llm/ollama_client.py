import asyncio
import logging
import config
from ollama import AsyncClient

logger = logging.getLogger("OllamaClient")

class OllamaClient:
    """
    Local LLM Client for Vector-less RAG using Ollama.
    Used as a fail-safe fallback for extraction tasks.
    """
    def __init__(self):
        self.model = config.OLLAMA_MODEL
        self.base_url = config.OLLAMA_BASE_URL
        self.client = AsyncClient(host=self.base_url)

    async def complete(self, prompt: str, model: str = None) -> str:
        """
        Completes a prompt using the local Ollama instance.
        Implements 3 attempts with exponential backoff.
        """
        target_model = model or self.model
        max_attempts = 3
        
        for attempt in range(max_attempts):
            try:
                # We use a wrap with wait_for to satisfy the 60s timeout requirement
                response = await asyncio.wait_for(
                    self.client.generate(model=target_model, prompt=prompt, stream=False),
                    timeout=60.0
                )
                return response.get('response', '')
            
            except asyncio.TimeoutError:
                logger.warning(f"Ollama timeout on attempt {attempt+1}/{max_attempts}")
            except Exception as e:
                logger.warning(f"Ollama error on attempt {attempt+1}/{max_attempts}: {str(e)}")
            
            if attempt < max_attempts - 1:
                wait_time = 2 ** attempt
                await asyncio.sleep(wait_time)
        
        logger.error(f"Ollama failed after {max_attempts} attempts.")
        return ""

# Singleton instance
ollama_client = OllamaClient()
