"""Pytest fixtures for MCP Operator tests."""

from typing import Any
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def mock_k8s_client() -> MagicMock:
    """Create a mock Kubernetes client."""
    return MagicMock()


@pytest.fixture
def mock_redis_client() -> MagicMock:
    """Create a mock Redis client."""
    client = MagicMock()
    client.ping.return_value = True
    return client


@pytest.fixture
def sample_mcpserver_spec() -> dict[str, Any]:
    """Return a sample MCPServer spec."""
    return {
        "replicas": 2,
        "redis": {"serviceName": "mcp-redis"},
        "ingress": {
            "host": "mcp.example.com",
            "tlsSecretName": "mcp-tls",
            "pathPrefix": "/mcp",
        },
        "toolSelector": {"matchLabels": {"mcp-server": "main"}},
        "config": {"requestTimeout": "30s", "maxConcurrentRequests": 100},
    }


@pytest.fixture
def sample_mcptool_spec() -> dict[str, Any]:
    """Return a sample MCPTool spec."""
    return {
        "name": "github-search",
        "description": "Search GitHub repositories",
        "service": {"name": "github-tool-svc", "port": 8080, "path": "/search"},
        "inputSchema": {
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": {"type": "string"},
                "language": {"type": "string"},
            },
        },
        "method": "POST",
        "ingressPath": "/tools/github/search",
    }


@pytest.fixture
def sample_mcpprompt_spec() -> dict[str, Any]:
    """Return a sample MCPPrompt spec."""
    return {
        "name": "github-query-helper",
        "description": "Helper for constructing GitHub searches",
        "template": "Search GitHub for {{query}}. Language: {{language}}",
        "variables": [
            {"name": "query", "description": "Search query", "required": True},
            {"name": "language", "description": "Language filter", "default": "any"},
        ],
        "ingressPath": "/prompts/github/query",
    }


@pytest.fixture
def sample_mcpresource_spec_operations() -> dict[str, Any]:
    """Return a sample MCPResource spec with operations."""
    return {
        "name": "github-docs",
        "description": "GitHub API documentation",
        "operations": [
            {
                "method": "GET",
                "ingressPath": "/resources/github/docs/{section}",
                "service": {
                    "name": "github-docs-svc",
                    "port": 8080,
                    "path": "/api/docs/{section}",
                },
                "parameters": [
                    {"name": "section", "in": "path", "required": True},
                    {"name": "version", "in": "query", "required": False},
                ],
            }
        ],
    }


@pytest.fixture
def sample_mcpresource_spec_inline() -> dict[str, Any]:
    """Return a sample MCPResource spec with inline content."""
    return {
        "name": "config-template",
        "description": "Sample configuration template",
        "content": {
            "uri": "config://template",
            "mimeType": "text/yaml",
            "text": "key: value\nother: data",
        },
    }
