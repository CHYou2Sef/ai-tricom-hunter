from fastapi import FastAPI
import config
from utils.health_check import check_all

app = FastAPI(title="AI Phone Hunter Monitor")

@app.get("/health")
async def health():
    return await check_all()

@app.get("/stats")
async def stats():
    # Placeholder for performance stats
    return {"status": "active", "workers": config.MAX_CONCURRENT_WORKERS}
