"""MCP Operator Pydantic models."""

from src.models.crds import (
    MCPPromptSpec,
    MCPResourceSpec,
    MCPServerSpec,
    MCPToolSpec,
)

__all__ = [
    "MCPServerSpec",
    "MCPToolSpec",
    "MCPPromptSpec",
    "MCPResourceSpec",
]
