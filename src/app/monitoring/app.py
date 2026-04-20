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
