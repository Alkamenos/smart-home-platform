"""
Metrics server for exposing Prometheus metrics via HTTP.

Provides a FastAPI-based server that exposes the /metrics endpoint
for Prometheus to scrape.
"""

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.responses import PlainTextResponse

from smart_home.core.metrics import MetricsCollector


def create_metrics_app(
    host: str = "0.0.0.0",
    port: int = 9090,
    prefix: str = "",
) -> FastAPI:
    """
    Create a FastAPI application for serving Prometheus metrics.

    Args:
        host: Host to bind the server to.
        port: Port to bind the server to.
        prefix: URL prefix for metrics endpoint.

    Returns:
        FastAPI application instance.
    """
    metrics_collector = MetricsCollector()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup
        yield
        # Shutdown

    app = FastAPI(
        title="Smart Home FSM Metrics",
        description="Prometheus metrics endpoint for Smart Home FSM Platform",
        version="1.0.0",
        lifespan=lifespan,
    )

    @app.get(f"{prefix}/metrics")
    async def get_metrics(request: Request) -> Response:
        """
        Expose Prometheus metrics.

        Returns metrics in the Prometheus text format.
        """
        start_time = time.perf_counter()
        try:
            metrics_data = metrics_collector.get_latest_metrics()
            latency = time.perf_counter() - start_time

            # Record the request itself
            metrics_collector.record_http_request(
                method=request.method,
                endpoint="/metrics",
                status_code=200,
                latency=latency,
            )

            return PlainTextResponse(
                content=metrics_data.decode("utf-8"),
                media_type="text/plain; charset=utf-8; version=0.0.4",
            )
        except Exception as e:
            latency = time.perf_counter() - start_time
            metrics_collector.record_http_request(
                method=request.method,
                endpoint="/metrics",
                status_code=500,
                latency=latency,
            )
            return PlainTextResponse(
                content=f"Error generating metrics: {str(e)}",
                status_code=500,
                media_type="text/plain",
            )

    @app.get(f"{prefix}/health")
    async def health_check() -> dict:
        """Health check endpoint."""
        return {"status": "healthy", "service": "metrics-server"}

    @app.get(f"{prefix}/ready")
    async def readiness_check() -> dict:
        """Readiness check endpoint."""
        return {"status": "ready"}

    return app


def run_metrics_server(
    host: str = "0.0.0.0",
    port: int = 9090,
    prefix: str = "",
) -> None:
    """
    Run the metrics server.

    Args:
        host: Host to bind the server to.
        port: Port to bind the server to.
        prefix: URL prefix for metrics endpoint.
    """
    import uvicorn

    app = create_metrics_app(host=host, port=port, prefix=prefix)
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    run_metrics_server()
