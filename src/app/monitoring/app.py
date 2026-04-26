"""
╔══════════════════════════════════════════════════════════════════════════╗
║  app/monitoring/app.py                                                   ║
║                                                                          ║
║  FastAPI Monitoring & Health API                                         ║
║                                                                          ║
║  ROLE:                                                                   ║
║    Exposes HTTP endpoints for Kubernetes health probes, Prometheus       ║
║    metrics, and real-time agent status monitoring.                       ║
║                                                                          ║
║  ENDPOINTS:                                                              ║
║    GET /health  → Liveness/Readiness probe (K8s compatible)              ║
║    GET /stats   → Agent throughput & worker pool status                  ║
║    GET /metrics → Prometheus metrics (auto-exposed by setup_observability)║
║                                                                          ║
║  SECURITY:                                                               ║
║    Swagger docs disabled in production (DOCKER_ENV=true)                 ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import os
from fastapi import FastAPI
from core import config
from common.health_check import check_all
from core.observability import setup_observability

# Disable docs in production environments for security
show_docs = os.getenv("DOCKER_ENV", "false").lower() != "true"

app = FastAPI(
    title="AI Phone Hunter Monitor",
    docs_url="/docs" if show_docs else None,
    redoc_url="/redoc" if show_docs else None
)

# Apply Metrics & Tracing
setup_observability(app)

@app.get("/health")
async def health():
    """Endpoint for Liveness/Readiness probes."""
    return await check_all()

@app.get("/stats")
async def stats():
    """Exposes high-level agent performance metrics."""
    # Placeholder for actual agent throughput stats
    return {"status": "active", "workers": config.MAX_CONCURRENT_WORKERS}
