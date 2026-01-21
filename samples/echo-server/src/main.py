"""Echo/Debug MCP Server.

A simple FastAPI server that:
- Echoes tool calls with debug information
- Serves prompts and resources from the ConfigMap
- Provides health endpoints for Kubernetes probes
"""

import json
import os
import socket
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="MCP Echo Server", version="0.1.0")

# Configuration
CONFIG_DIR = Path(os.getenv("MCP_CONFIG_DIR", "/etc/mcp/config"))
REDIS_HOST = os.getenv("REDIS_HOST", "")
HOSTNAME = socket.gethostname()

# Cached config data
_config_cache: dict[str, Any] = {}


def load_config() -> dict[str, Any]:
    """Load configuration from ConfigMap mount."""
    global _config_cache

    if _config_cache:
        return _config_cache

    config: dict[str, Any] = {
        "tools": [],
        "prompts": [],
        "resources": [],
        "loaded": False,
        "error": None,
    }

    if not CONFIG_DIR.exists():
        config["error"] = f"Config directory {CONFIG_DIR} does not exist"
        return config

    try:
        tools_file = CONFIG_DIR / "tools.json"
        if tools_file.exists():
            config["tools"] = json.loads(tools_file.read_text())

        prompts_file = CONFIG_DIR / "prompts.json"
        if prompts_file.exists():
            config["prompts"] = json.loads(prompts_file.read_text())

        resources_file = CONFIG_DIR / "resources.json"
        if resources_file.exists():
            config["resources"] = json.loads(resources_file.read_text())

        config["loaded"] = True
    except Exception as e:
        config["error"] = str(e)

    _config_cache = config
    return config


def reload_config() -> dict[str, Any]:
    """Force reload configuration."""
    global _config_cache
    _config_cache = {}
    return load_config()


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint for Kubernetes probes."""
    return {"status": "healthy"}


@app.get("/ready")
async def ready() -> dict[str, Any]:
    """Readiness check - verifies config is loaded."""
    config = load_config()
    if config["loaded"]:
        return {"status": "ready", "config_loaded": True}
    return JSONResponse(
        status_code=503,
        content={"status": "not_ready", "error": config.get("error")},
    )


@app.get("/debug")
async def debug() -> dict[str, Any]:
    """Return server configuration and environment info."""
    config = load_config()
    return {
        "hostname": HOSTNAME,
        "redis_host": REDIS_HOST,
        "config_dir": str(CONFIG_DIR),
        "config_loaded": config["loaded"],
        "config_error": config.get("error"),
        "tool_count": len(config["tools"]),
        "prompt_count": len(config["prompts"]),
        "resource_count": len(config["resources"]),
        "env": {
            "MCP_CONFIG_DIR": os.getenv("MCP_CONFIG_DIR", "(default)"),
            "REDIS_HOST": REDIS_HOST or "(not set)",
        },
    }


@app.post("/reload")
async def reload() -> dict[str, Any]:
    """Reload configuration from ConfigMap."""
    config = reload_config()
    return {
        "reloaded": True,
        "config_loaded": config["loaded"],
        "tool_count": len(config["tools"]),
        "prompt_count": len(config["prompts"]),
        "resource_count": len(config["resources"]),
    }


# Tools endpoints


@app.get("/tools")
async def list_tools() -> list[dict[str, Any]]:
    """List all loaded tools."""
    config = load_config()
    return [{"name": t.get("name"), "endpoint": t.get("endpoint")} for t in config["tools"]]


@app.post("/tools/{name}")
async def call_tool(name: str, request: Request) -> dict[str, Any]:
    """Echo a tool call with debug information."""
    config = load_config()

    # Find the tool
    tool = next((t for t in config["tools"] if t.get("name") == name), None)

    # Parse request body
    try:
        body = await request.json()
    except Exception:
        body = {}

    return {
        "tool": name,
        "found": tool is not None,
        "input": body,
        "timestamp": datetime.now(UTC).isoformat(),
        "server": HOSTNAME,
        "tool_config": tool,
        "echo": {
            "message": f"Tool '{name}' called successfully",
            "would_forward_to": tool.get("endpoint") if tool else None,
        },
    }


# Prompts endpoints


@app.get("/prompts")
async def list_prompts() -> list[dict[str, Any]]:
    """List all loaded prompts."""
    config = load_config()
    return [
        {
            "name": p.get("name"),
            "variables": [v.get("name") for v in p.get("variables", [])],
        }
        for p in config["prompts"]
    ]


@app.get("/prompts/{name}")
async def get_prompt(name: str, request: Request) -> dict[str, Any]:
    """Render a prompt with query parameters as variables."""
    config = load_config()

    # Find the prompt
    prompt = next((p for p in config["prompts"] if p.get("name") == name), None)
    if not prompt:
        raise HTTPException(status_code=404, detail=f"Prompt '{name}' not found")

    template = prompt.get("template", "")
    variables = {v.get("name"): v.get("default", "") for v in prompt.get("variables", [])}

    # Override with query params
    for key, value in request.query_params.items():
        variables[key] = value

    # Simple template substitution
    rendered = template
    for var_name, var_value in variables.items():
        rendered = rendered.replace(f"{{{{{var_name}}}}}", str(var_value))

    return {
        "name": name,
        "template": template,
        "variables": variables,
        "rendered": rendered,
        "timestamp": datetime.now(UTC).isoformat(),
        "server": HOSTNAME,
    }


# Resources endpoints


@app.get("/resources")
async def list_resources() -> list[dict[str, Any]]:
    """List all loaded resources."""
    config = load_config()
    return [
        {
            "name": r.get("name"),
            "has_content": r.get("content") is not None,
            "has_operations": r.get("operations") is not None,
        }
        for r in config["resources"]
    ]


@app.get("/resources/{name}")
async def get_resource(name: str) -> dict[str, Any]:
    """Return resource content or operations info."""
    config = load_config()

    # Find the resource
    resource = next((r for r in config["resources"] if r.get("name") == name), None)
    if not resource:
        raise HTTPException(status_code=404, detail=f"Resource '{name}' not found")

    result: dict[str, Any] = {
        "name": name,
        "timestamp": datetime.now(UTC).isoformat(),
        "server": HOSTNAME,
    }

    if resource.get("content"):
        content = resource["content"]
        result["content"] = {
            "uri": content.get("uri"),
            "mimeType": content.get("mimeType"),
            "text": content.get("text"),
            "has_blob": content.get("blob") is not None,
        }
    elif resource.get("operations"):
        result["operations"] = [
            {
                "method": op.get("method"),
                "path": op.get("ingressPath"),
            }
            for op in resource["operations"]
        ]

    return result


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)
