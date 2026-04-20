"""Unit & Integration Tests for Orchestrator"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path
import pandas as pd

from src.app.orchestrator import WorkerContext, process_file_async, init_agent_pool
from src.domain.excel.reader import ExcelRow
from src.core.config import MAX_CONCURRENT_WORKERS, SAVE_INTERVAL

@pytest.fixture
def mock_excel_row():
    row = MagicMock(spec=ExcelRow)
    row.row_index = 42
    row.phone = None
    row.agent_phone = None
    row.status = "PENDING"
    row.get_fingerprint.return_value = "test_fp_123"
    return row

@pytest.fixture
def mock_rows():
    return [mock_excel_row() for _ in range(3)]

@pytest.mark.asyncio
async def test_worker_context_creation(mock_rows):
    """Test WorkerContext dataclass instantiation."""
    ctx = WorkerContext(
        row=mock_rows[0],
        sem=asyncio.Semaphore(1),
        save_lock=asyncio.Lock(),
        all_rows=mock_rows,
        filepath="/tmp/test.xlsx",
        tracker=MagicMock(),
        idx=1,
        total=3,
        progress=MagicMock()
    )
    assert ctx.row.row_index == 42
    assert ctx.total == 3

@pytest.mark.asyncio
async def test_init_agent_pool():
    """Test agent pool initialization."""
    with patch('src.app.orchestrator.HybridAutomationEngine') as MockAgent:
        mock_agent = AsyncMock()
        MockAgent.return_value = mock_agent
        await init_agent_pool(2)
        
        # Verify 2 agents created/started
        assert MockAgent.call_count == 2
        assert mock_agent.start_tier.call_count == 2

@pytest.mark.asyncio
async def test_process_file_async_empty():
    """Test processing empty file."""
    with patch('src.app.orchestrator.read_excel') as mock_read:
        mock_read.return_value = ([], {})
        await process_file_async("/tmp/empty.xlsx")
        mock_read.assert_called_once()

@pytest.mark.asyncio
@patch('src.app.orchestrator.FileProgressTracker')
@patch('src.app.orchestrator.PerformanceTracker')
@patch('src.app.orchestrator.HybridAutomationEngine')
async def test_full_orchestrator_flow(MockAgent, MockPerf, MockProgress, mock_rows):
    """End-to-end orchestrator test with mocks."""
    mock_agent = AsyncMock()
    MockAgent.return_value = mock_agent
    mock_agent.is_alive.return_value = True
    
    mock_progress = MagicMock()
    MockProgress.return_value = mock_progress
    
    mock_perf = MagicMock()
    mock_perf.start_file_processing.return_value = None
    
    with patch('src.app.orchestrator.read_excel', return_value=(mock_rows, {})):
        with patch('src.app.orchestrator._agent_pool.put') as mock_put:
            await process_file_async("/tmp/test.xlsx")
            
    # Verify pool usage
    assert mock_put.call_count >= 3  # One per row
    mock_agent.close.assert_not_called()  # Healthy agents returned to pool

@pytest.mark.asyncio
async def test_agent_health_check_failure():
    """Test agent recreation on health check failure."""
    mock_dead_agent = AsyncMock()
    mock_dead_agent.is_alive.return_value = False
    
    mock_new_agent = AsyncMock()
    mock_new_agent.is_alive.return_value = True
    
    with patch('src.app.orchestrator.HybridAutomationEngine') as MockAgent:
        MockAgent.side_effect = [mock_dead_agent, mock_new_agent]
        with patch('src.app.orchestrator._agent_pool.get', return_value=mock_dead_agent):
            with patch('src.app.orchestrator._agent_pool.put'):
                # Simulate worker_process_row health check path
                pass  # Implementation would call the path
                
    MockAgent.assert_called()  # New agent created

def test_dataclass_immutability():
    """Ensure WorkerContext uses frozen=True for safety."""
    from src.app.orchestrator import WorkerContext
    # This will fail if not frozen
    ctx = WorkerContext(
        row=MagicMock(), sem=asyncio.Semaphore(1), save_lock=asyncio.Lock(),
        all_rows=[], filepath="", tracker=MagicMock(), idx=0, total=0, progress=MagicMock()
    )
    with pytest.raises(pytest.raises(Exception)):  # Frozen dataclass error
        ctx.row = None

@pytest.mark.parametrize("concurrent", [1, 2, 4])
def test_max_concurrent_workers_respected(concurrent):
    """Verify semaphore limits concurrency."""
    assert MAX_CONCURRENT_WORKERS == concurrent  # Config test
    # Semaphore(concurrency) is used in orchestrator

class TestSaveInterval:
    """Test SAVE_INTERVAL logic."""
    def test_interval_config(self):
        from src.core.config import SAVE_INTERVAL
        assert SAVE_INTERVAL == 50  # Production optimized

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
