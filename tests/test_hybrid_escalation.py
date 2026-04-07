"""
Tests for HybridAutomationEngine verifying explicit browser closing and waterfall execution.
Run with: pytest tests/test_hybrid_escalation.py -v
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, patch

from browser.hybrid_engine import HybridAutomationEngine

def test_hybrid_engine_explicitly_closes_tier_on_escalation():
    """
    Verifies that when a Tier fails, the engine EXPLICITLY calls stop_tier() 
    for that tier before moving to the next tier.
    """
    async def run_test():
        engine = HybridAutomationEngine(worker_id=1)
        
        # Track the stop_tier calls without actual browser actions
        engine.stop_tier = AsyncMock()
        
        # Fake start_tier to return True and inject mock agents
        async def mock_start_tier(tier: int) -> bool:
            if tier == 1:
                m = AsyncMock()
                m.search_google_ai_mode.return_value = None  # Fails (returns None)
                engine._tier1 = m
            elif tier == 2:
                m = AsyncMock()
                m.search_google_ai_mode.return_value = '{"success": true}' # Succeeds
                engine._tier2 = m
            return True
        
        engine.start_tier = AsyncMock(side_effect=mock_start_tier)
        
        result = await engine.search_google_ai_mode("Test Prompt")
        
        # 1. Did it get the result from Tier 2?
        assert result == '{"success": true}'
        
        # 2. Did it explicitly stop Tier 1?
        engine.stop_tier.assert_any_call(1)
        
        # 3. Did it advance the current tier pointer?
        assert engine._current_tier == 2

    asyncio.run(run_test())

def test_hybrid_engine_delegates_to_agent():
    """
    Verifies that the delegation wrapper calls the active agent's method and tracks stats.
    """
    async def run_test():
        engine = HybridAutomationEngine()
        engine.start_tier = AsyncMock(return_value=True)
        engine.stop_tier = AsyncMock()
        
        tier1_mock = AsyncMock()
        tier1_mock.submit_google_search.return_value = True
        engine._tier1 = tier1_mock
        
        result = await engine.submit_google_search("Test Query")
        
        assert result is True
        assert engine.get_engine_stats()[1]["successes"] == 1
        assert engine.get_engine_stats()[1]["attempts"] == 1
        
    asyncio.run(run_test())
