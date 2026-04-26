"""
╔══════════════════════════════════════════════════════════════════════════╗
║  app/monitoring/models.py                                                ║
║                                                                          ║
║  Pydantic Data Models for Monitoring API                                 ║
║                                                                          ║
║  ROLE:                                                                   ║
║    Defines the JSON schema for health checks and statistics responses.   ║
║    Pydantic auto-validates incoming/outgoing data and generates docs.    ║
║                                                                          ║
║  MODELS:                                                                 ║
║    HealthReport → System health status (Ollama, disk, dirs, proxy)      ║
║    StatsReport  → Agent performance metrics (workers, queue depth)       ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

from pydantic import BaseModel
from typing import Optional, List


class HealthReport(BaseModel):
    """System health check result."""
    ollama: bool   # Local LLM reachable
    disk: bool     # Disk space OK
    dirs: bool     # Required directories exist
    proxy: bool    # Proxy pool available


class StatsReport(BaseModel):
    """Agent performance statistics."""
    status: str           # "active" | "idle" | "error"
    workers: int          # Number of concurrent workers
    queue_depth: Optional[int] = 0  # Pending tasks in queue
