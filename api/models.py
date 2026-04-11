from pydantic import BaseModel
from typing import Optional, List

class HealthReport(BaseModel):
    ollama: bool
    disk: bool
    dirs: bool
    proxy: bool

class StatsReport(BaseModel):
    status: str
    workers: int
    queue_depth: Optional[int] = 0
