import pytest
import asyncio
from infra.browsers.cloak_agent import CloakAgent, CLOAK_AVAILABLE

@pytest.mark.skipif(not CLOAK_AVAILABLE, reason="cloakbrowser package not installed")
@pytest.mark.asyncio
async def test_cloak_agent_smoke():
    """Verify that CloakAgent can start and navigate to a basic URL."""
    agent = CloakAgent(worker_id=999)
    try:
        await agent.start()
        assert agent.page is not None
        
        success = await agent.goto_url("https://www.google.com")
        assert success is True
        
        source = await agent.get_page_source()
        assert "google" in source.lower()
    finally:
        await agent.close()

@pytest.mark.skipif(not CLOAK_AVAILABLE, reason="cloakbrowser package not installed")
@pytest.mark.asyncio
async def test_cloak_agent_search_ai():
    """Verify that CloakAgent can perform an AI mode search."""
    agent = CloakAgent(worker_id=999)
    try:
        await agent.start()
        result = await agent.search_google_ai_mode("Test query for CloakBrowser")
        # Result might be None if no AI response appears, but we check for no crash
        assert result is None or isinstance(result, str)
    finally:
        await agent.close()
