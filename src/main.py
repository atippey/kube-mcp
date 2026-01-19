"""MCP Operator entry point.

This module serves as the main entry point for the kopf operator.
It imports all controllers to register their handlers with kopf.
"""

import kopf

# Import controllers to register handlers
from src.controllers import (
    mcpprompt_controller,
    mcpresource_controller,
    mcpserver_controller,
    mcptool_controller,
)

# Re-export to satisfy linters (controllers register via decorators)
__all__ = [
    "mcpserver_controller",
    "mcptool_controller",
    "mcpprompt_controller",
    "mcpresource_controller",
]


@kopf.on.startup()
async def startup_handler(logger: kopf.Logger, **_: object) -> None:
    """Handle operator startup."""
    logger.info("MCP Operator starting up")


@kopf.on.cleanup()
async def cleanup_handler(logger: kopf.Logger, **_: object) -> None:
    """Handle operator cleanup."""
    logger.info("MCP Operator shutting down")
