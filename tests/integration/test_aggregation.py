import contextlib
import json
import time

import pytest
from kubernetes import client

GROUP = "mcp.k8s.turd.ninja"
VERSION = "v1alpha1"
SERVER_PLURAL = "mcpservers"
TOOL_PLURAL = "mcptools"


@pytest.mark.integration
def test_aggregation_update(operator, k8s_client):
    """Test that creating a tool updates the MCPServer config."""
    api = client.CustomObjectsApi(k8s_client)
    core_v1 = client.CoreV1Api(k8s_client)

    namespace = "mcp-test"
    server_name = "agg-test-server"
    label_key = "app"
    label_value = "agg-test"

    # 1. Create MCPServer with selector
    mcpserver = {
        "apiVersion": f"{GROUP}/{VERSION}",
        "kind": "MCPServer",
        "metadata": {"name": server_name, "namespace": namespace},
        "spec": {
            "replicas": 1,
            "redis": {"serviceName": "mcp-redis"},
            "toolSelector": {"matchLabels": {label_key: label_value}},
        },
    }

    print(f"Creating MCPServer {server_name}")
    with contextlib.suppress(client.exceptions.ApiException):
        api.create_namespaced_custom_object(
            GROUP, VERSION, namespace, SERVER_PLURAL, body=mcpserver
        )

    # Wait for CM to be created
    cm_name = f"mcp-server-{server_name}-config"
    start = time.time()
    cm = None
    while time.time() - start < 30:
        with contextlib.suppress(client.exceptions.ApiException):
            cm = core_v1.read_namespaced_config_map(cm_name, namespace)
            break
        time.sleep(1)

    assert cm is not None
    tools = json.loads(cm.data["tools.json"])
    assert len(tools) == 0, "Expected 0 tools initially"

    # 2. Create MCPTool matching selector
    tool_name = "agg-tool"
    tool = {
        "apiVersion": f"{GROUP}/{VERSION}",
        "kind": "MCPTool",
        "metadata": {"name": tool_name, "namespace": namespace, "labels": {label_key: label_value}},
        "spec": {"name": "agg-tool", "service": {"name": "some-service", "port": 80}},
    }

    print(f"Creating MCPTool {tool_name}")
    api.create_namespaced_custom_object(GROUP, VERSION, namespace, TOOL_PLURAL, body=tool)

    # 3. Verify CM updates
    print("Waiting for ConfigMap update...")
    start = time.time()
    updated = False
    while time.time() - start < 30:
        cm = core_v1.read_namespaced_config_map(cm_name, namespace)
        tools = json.loads(cm.data["tools.json"])
        if any(t["name"] == "agg-tool" for t in tools):
            updated = True
            break
        time.sleep(1)

    assert updated, "ConfigMap was not updated with new tool"

    # Cleanup
    with contextlib.suppress(Exception):
        api.delete_namespaced_custom_object(
            GROUP, VERSION, namespace, SERVER_PLURAL, name=server_name
        )
        api.delete_namespaced_custom_object(GROUP, VERSION, namespace, TOOL_PLURAL, name=tool_name)
