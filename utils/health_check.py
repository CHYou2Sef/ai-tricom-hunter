import asyncio
import logging
import shutil
import httpx
import config
from pathlib import Path

logger = logging.getLogger("HealthCheck")

async def check_ollama() -> bool:
    if not config.OLLAMA_ENABLED:
        return True
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.get(config.OLLAMA_BASE_URL)
            return response.status_code == 200
    except Exception:
        return False

def check_disk() -> bool:
    total, used, free = shutil.disk_usage(config.BASE_DIR)
    usage_pct = (used / total) * 100
    return usage_pct < 85

def check_directories() -> bool:
    required_dirs = [
        config.WORK_DIR.parent, # The project root
        config.WORK_DIR,
        config.INCOMING_DIR
    ]
    for d in required_dirs:
        if not d.exists():
            try:
                from utils.fs import safe_mkdir
                safe_mkdir(d)
            except Exception:
                return False
    return True

async def check_all() -> dict[str, bool]:
    """
    Startup validator:
    - check Ollama reachable
    - check disk usage < 85%
    - check WORK/ directories exist
    - check proxy if enabled (placeholder for simple ping)
    """
    results = {
        "ollama": await check_ollama(),
        "disk": check_disk(),
        "dirs": check_directories(),
        "proxy": True # Simplified
    }
    
    for key, status in results.items():
        icon = "✅" if status else "❌"
        logger.info(f"[HealthCheck] {key.upper()}: {icon}")
        
    return results
