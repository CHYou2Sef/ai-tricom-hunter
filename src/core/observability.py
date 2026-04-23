import time
import uuid
import structlog
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from core.logger import get_logger

import os
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from prometheus_client import Counter

# Custom Metrics for Industrial Agent
SCRAPING_RESULTS = Counter(
    "scraping_results_total",
    "Total number of scraping attempts by tier, method, and outcome status",
    ["tier", "scrap_method", "status"]
)

# Configure structured logging with all levels
structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    logger_factory=structlog.PrintLoggerFactory(),
)

log = structlog.get_logger()

class TracingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        start_time = time.perf_counter()
        
        # OpenTelemetry context is handled by FastAPIInstrumentor manually or via middleware
        response = await call_next(request)
        
        duration = time.perf_counter() - start_time
        
        # Log structured request info
        log.info(
            "http_request",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration=f"{duration:.4f}s",
            request_id=request_id
        )

        # Add Security Headers (DAST Compliance)
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = "default-src 'self'"
        response.headers["X-Request-ID"] = request_id
        return response

def setup_observability(app):
    """
    Integrates Prometheus metrics, OpenTelemetry Tracing, and Tracing middleware.
    """
    # 1. Setup OpenTelemetry
    provider = TracerProvider()
    
    # Export to OTLP collector (e.g. Jaeger / OTEL Collector)
    otlp_exporter = OTLPSpanExporter(endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317"))
    processor = BatchSpanProcessor(otlp_exporter)
    provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)
    
    # Instrument FastAPI
    FastAPIInstrumentor.instrument_app(app)
    
    # 2. Add Custom Tracing Middleware (for headers & specific logs)
    app.add_middleware(TracingMiddleware)
    
    # 3. Add Prometheus Instrumentation
    from prometheus_fastapi_instrumentator import Instrumentator
    Instrumentator().instrument(app).expose(app, endpoint="/metrics")
    
    return app
