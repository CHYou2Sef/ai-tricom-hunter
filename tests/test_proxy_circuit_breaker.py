import pytest
from unittest.mock import MagicMock, patch
from common.proxy_manager import ProxyManager, ProxyState, ProxyRecord

@pytest.fixture
def manager():
    # Patch config to have predictable thresholds for testing
    with patch('core.config.PROXY_WARN_THRESHOLD', 2), \
         patch('core.config.PROXY_BAN_THRESHOLD', 4), \
         patch('core.config.PROXY_BACKOFF_DELAYS', [0.1]), \
         patch('core.config.PROXY_PREEMPTIVE_ROTATE_ON_WARN', False):
        yield ProxyManager()

def test_proxy_url_validation(manager):
    assert manager._validate_proxy_url("http://1.2.3.4:8080") is True
    assert manager._validate_proxy_url("https://proxy.com:443") is True
    assert manager._validate_proxy_url("socks5://user:pass@1.1.1.1:1080") is True
    
    # Invalid schemes
    assert manager._validate_proxy_url("ftp://1.2.3.4") is False
    # Invalid hostnames/IPs
    assert manager._validate_proxy_url("http://localhost:8080") is False
    assert manager._validate_proxy_url("http://127.0.0.1:8080") is False
    # Malformed
    assert manager._validate_proxy_url("not-a-url") is False

def test_proxy_state_machine_transitions(manager):
    addr = "http://1.2.3.4:8080"
    
    # 1. First error -> Still HEALTHY (threshold is 2)
    state = manager.mark_error(addr)
    assert state == ProxyState.HEALTHY
    assert manager._records[addr].error_count == 1
    
    # 2. Second error -> Reach WARN
    state = manager.mark_error(addr)
    assert state == ProxyState.WARN
    
    # 3. Third error -> Still WARN (ban threshold is 4)
    state = manager.mark_error(addr)
    assert state == ProxyState.WARN
    
    # 4. Fourth error -> BAN
    with patch('time.sleep'): # Avoid delay in test
        state = manager.mark_error(addr)
        assert state == ProxyState.BAN

def test_preemptive_rotation_on_warn(manager):
    # Enable preemptive rotation
    addr = "http://1.2.3.4:8080"
    
    with patch('core.config.PROXY_PREEMPTIVE_ROTATE_ON_WARN', True), \
         patch('core.config.PROXY_WARN_THRESHOLD', 2), \
         patch('time.sleep'):
        
        manager.mark_error(addr) # error 1 (healthy)
        state = manager.mark_error(addr) # error 2 (warn -> triggers ban immediately)
        
        assert state == ProxyState.BAN
        assert manager._records[addr].state == ProxyState.BAN

def test_force_ban(manager):
    addr = "http://2.2.2.2:8080"
    with patch('time.sleep'):
        manager.mark_banned(addr)
        assert manager._records[addr].state == ProxyState.BAN
