"""
╔══════════════════════════════════════════════════════════════════════════╗
║  core/observability.py                                                   ║
║                                                                          ║
║  Observability & Monitoring Stack                                        ║
║  Integrates three industrial-grade telemetry systems:                    ║
║    1. Prometheus Metrics    — Counters/Gauges for scraping stats         ║
║    2. OpenTelemetry Tracing — Distributed request tracing (OTLP)         ║
║    3. Structured Logging    — JSON-formatted logs via structlog          ║
║                                                                          ║
║  HOW IT WORKS:                                                           ║
║    FastAPIInstrumentor auto-instruments all HTTP endpoints.              ║
║    Custom TracingMiddleware adds security headers + request IDs.         ║
║    SCRAPING_RESULTS counter tracks tier/method/status outcomes.          ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

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
        
        # Log structured request info (Skip /metrics to reduce noise)
        if request.url.path != "/metrics":
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
    # 1. Setup OpenTelemetry (Only if explicitly enabled via OTEL_EXPORTER_OTLP_ENDPOINT)
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if endpoint:
        provider = TracerProvider()
        otlp_exporter = OTLPSpanExporter(endpoint=endpoint)
        processor = BatchSpanProcessor(otlp_exporter)
        provider.add_span_processor(processor)
        trace.set_tracer_provider(provider)
        
        # Instrument FastAPI
        FastAPIInstrumentor.instrument_app(app)
    else:
        log.debug("OTLP Tracing disabled (no endpoint configured)")
    
    # 2. Add Custom Tracing Middleware (for headers & specific logs)
    app.add_middleware(TracingMiddleware)
    
    # 3. Add Prometheus Instrumentation
    from prometheus_fastapi_instrumentator import Instrumentator
    Instrumentator().instrument(app).expose(app, endpoint="/metrics")
    
    return app
