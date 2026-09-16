"""Prometheus metrics HTTP server for the smart home FSM platform.

This module provides an HTTP server that exposes Prometheus metrics
at the /metrics endpoint.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

from aiohttp import web


if TYPE_CHECKING:
    from .metrics import MetricsCollector

__all__ = [
    "MetricsServer",
    "start_metrics_server",
]


class MetricsServer:
    """HTTP server for exposing Prometheus metrics."""

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 9090,
        metrics_collector: MetricsCollector | None = None,
    ) -> None:
        """Initialize the metrics server.

        Args:
            host: Host address to bind to.
            port: Port number to listen on.
            metrics_collector: Optional metrics collector instance.
        """
        self._host: str = host
        self._port: int = port
        self._app: web.Application | None = None
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._metrics_collector: MetricsCollector | None = metrics_collector

    async def start(self) -> None:
        """Start the metrics HTTP server."""

        self._app = web.Application()
        self._app.router.add_get("/metrics", self._handle_metrics)
        self._app.router.add_get("/health", self._handle_health)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()

        self._site = web.TCPSite(self._runner, self._host, self._port)
        await self._site.start()

        # Initialize metrics collector if provided
        if self._metrics_collector:
            self._metrics_collector.initialize()

    async def stop(self) -> None:
        """Stop the metrics HTTP server."""
        if self._runner:
            await self._runner.cleanup()
        self._site = None
        self._runner = None
        self._app = None

    async def _handle_metrics(self, request: web.Request) -> web.Response:
        """Handle GET /metrics request.

        Args:
            request: The incoming HTTP request.

        Returns:
            HTTP response with Prometheus metrics in text format.
        """
        from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

        try:
            metrics_data = generate_latest()
            return web.Response(
                body=metrics_data,
                content_type=CONTENT_TYPE_LATEST,
            )
        except Exception as e:
            return web.Response(
                body=f"Error generating metrics: {e}",
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
                content_type="text/plain",
            )

    async def _handle_health(self, request: web.Request) -> web.Response:
        """Handle GET /health request.

        Args:
            request: The incoming HTTP request.

        Returns:
            HTTP response indicating server health status.
        """
        is_ready = self._metrics_collector is not None and self._metrics_collector.is_initialized()
        status = {"status": "healthy" if is_ready else "degraded"}
        return web.json_response(status)


async def start_metrics_server(
    host: str = "0.0.0.0",
    port: int = 9090,
    metrics_collector: MetricsCollector | None = None,
) -> MetricsServer:
    """Start a Prometheus metrics HTTP server.

    Args:
        host: Host address to bind to.
        port: Port number to listen on.
        metrics_collector: Optional metrics collector instance to initialize.

    Returns:
        The running MetricsServer instance.
    """
    server = MetricsServer(host=host, port=port, metrics_collector=metrics_collector)
    await server.start()
    return server
