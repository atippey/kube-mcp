"""MCP Operator entry point.

This module serves as the main entry point for the kopf operator.
It imports all controllers to register their handlers with kopf.
"""

import logging

import kopf
from pythonjsonlogger.json import JsonFormatter

# Import controllers to register handlers
from src.controllers import (
    mcpprompt_controller,
    mcpresource_controller,
    mcpserver_controller,
    mcptool_controller,
)
from src.utils.metrics import start_metrics_server

# Re-export to satisfy linters (controllers register via decorators)
__all__ = [
    "mcpserver_controller",
    "mcptool_controller",
    "mcpprompt_controller",
    "mcpresource_controller",
]


def _json_default(obj: object) -> str:
    """Fallback serializer for objects that json can't handle (e.g. kopf settings)."""
    return str(obj)


def configure_logging() -> None:
    """Configure structured JSON logging for all operator output."""
    handler = logging.StreamHandler()
    handler.setFormatter(
        JsonFormatter(
            fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
            rename_fields={"asctime": "timestamp", "levelname": "level"},
            json_default=_json_default,
        )
    )
    logging.root.handlers = [handler]
    logging.root.setLevel(logging.INFO)


configure_logging()


@kopf.on.startup()
async def startup_handler(logger: kopf.Logger, **_: object) -> None:
    """Handle operator startup."""
    start_metrics_server()
    logger.info("MCP Operator starting up (metrics on :9090, health on :8080)")


@kopf.on.probe(id="operator")
def probe_operator(**_: object) -> dict[str, str]:
    """Report operator health status."""
    return {"status": "running"}


@kopf.on.cleanup()
async def cleanup_handler(logger: kopf.Logger, **_: object) -> None:
    """Handle operator cleanup."""
    logger.info("MCP Operator shutting down")
