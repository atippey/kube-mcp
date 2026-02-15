"""Prometheus metrics for MCP operator observability."""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram, start_http_server

RECONCILIATION_TOTAL = Counter(
    "mcp_reconciliation_total",
    "Total reconciliation attempts",
    ["controller", "result"],
)

RECONCILIATION_DURATION = Histogram(
    "mcp_reconciliation_duration_seconds",
    "Time spent in reconciliation",
    ["controller"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)

MANAGED_RESOURCES = Gauge(
    "mcp_managed_resources",
    "Number of managed resources by kind",
    ["kind"],
)


def start_metrics_server(port: int = 9090) -> None:
    """Start the Prometheus metrics HTTP server."""
    start_http_server(port)
