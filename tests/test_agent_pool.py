import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest

from agent import init_agent_pool, close_agent_pool, _agent_pool

@pytest.mark.asyncio
async def test_pool_init_close():
    count = 2
    await init_agent_pool(count)
    assert _agent_pool.qsize() == count
    
    await close_agent_pool()
    assert _agent_pool.empty()

# Run with: pytest tests/test_agent_pool.py -v

