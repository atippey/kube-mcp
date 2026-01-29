import contextlib
import json
import time
from pathlib import Path

import pytest
import yaml
from kubernetes import client, utils

GROUP = "mcp.k8s.turd.ninja"
VERSION = "v1alpha1"
PLURAL = "mcpservers"


def wait_for_resource(check_func, timeout=60):
    start = time.time()
    last_error = None
    while time.time() - start < timeout:
        try:
            res = check_func()
            if res:
                return res
        except client.exceptions.ApiException:
            pass
        except Exception as e:
            last_error = e
        time.sleep(1)
    if last_error:
        print(f"Wait failed with error: {last_error}")
    return None


@pytest.mark.integration
def test_mcpserver_lifecycle(operator, k8s_client):
    """Test the full lifecycle of an MCPServer."""
    api = client.CustomObjectsApi(k8s_client)
    apps_v1 = client.AppsV1Api(k8s_client)
    core_v1 = client.CoreV1Api(k8s_client)

    namespace = "mcp-test"
    name = "lifecycle-test"

    # 1. Create MCPServer
    mcpserver = {
        "apiVersion": f"{GROUP}/{VERSION}",
        "kind": "MCPServer",
        "metadata": {"name": name, "namespace": namespace},
        "spec": {
            "replicas": 1,
            "redis": {"serviceName": "mcp-redis"},
            "toolSelector": {"matchLabels": {"mcp-server": name}},
        },
    }

    print(f"Creating MCPServer {name}")
    try:
        api.create_namespaced_custom_object(
            group=GROUP, version=VERSION, namespace=namespace, plural=PLURAL, body=mcpserver
        )
    except client.exceptions.ApiException as e:
        pytest.fail(f"Failed to create MCPServer: {e}")

    # 2. Verify resources created
    print("Waiting for Deployment...")
    deployment = wait_for_resource(
        lambda: apps_v1.read_namespaced_deployment(f"mcp-server-{name}", namespace)
    )
    assert deployment is not None, "Deployment not created"

    print("Waiting for Service...")
    service = wait_for_resource(
        lambda: core_v1.read_namespaced_service(f"mcp-server-{name}", namespace)
    )
    assert service is not None, "Service not created"

    print("Waiting for ConfigMap...")
    cm = wait_for_resource(
        lambda: core_v1.read_namespaced_config_map(f"mcp-server-{name}-config", namespace)
    )
    assert cm is not None, "ConfigMap not created"

    # 3. Verify Owner References
    print("Verifying Owner References...")
    owner_refs = deployment.metadata.owner_references
    assert owner_refs
    assert owner_refs[0].kind == "MCPServer"
    assert owner_refs[0].name == name

    # 4. Delete MCPServer
    print(f"Deleting MCPServer {name}")
    api.delete_namespaced_custom_object(
        group=GROUP, version=VERSION, namespace=namespace, plural=PLURAL, name=name
    )

    # 5. Verify Cleanup
    # We verify the custom object is gone.
    print("Verifying cleanup...")

    def check_deleted():
        try:
            api.get_namespaced_custom_object(GROUP, VERSION, namespace, PLURAL, name)
            return False
        except client.exceptions.ApiException as e:
            if e.status == 404:
                return True
            raise

    is_deleted = wait_for_resource(check_deleted)
    assert is_deleted, "MCPServer not deleted"


@pytest.mark.integration
@pytest.mark.skip(reason="Blocked by cgroup v2 configuration issue in k3s container - pods cannot start")
def test_echo_server_integration(operator, k8s_client):
    """Deploy echo server and verify aggregation."""
    namespace = "mcp-test"

    # 1. Deploy Echo Backend
    root_dir = Path(__file__).parents[2]
    backend_manifest = root_dir / "samples/echo-server/manifests/echo-backend.yaml"

    print(f"Applying {backend_manifest}")
    # Note: echo-backend.yaml uses 'mcp-test' namespace.
    with contextlib.suppress(utils.FailToCreateError):
        utils.create_from_yaml(k8s_client, str(backend_manifest))

    # 2. Deploy Example Resources
    resources_manifest = root_dir / "samples/echo-server/manifests/example-resources.yaml"
    print(f"Applying {resources_manifest}")
    # Note: example-resources.yaml uses 'mcp-test' namespace.

    # Parse YAML and create custom resources manually
    with open(resources_manifest) as f:
        docs = list(yaml.safe_load_all(f))

    api = client.CustomObjectsApi(k8s_client)

    # Map kind to plural
    plural_map = {
        'MCPServer': 'mcpservers',
        'MCPTool': 'mcptools',
        'MCPPrompt': 'mcpprompts',
        'MCPResource': 'mcpresources',
    }

    for doc in docs:
        if not doc:
            continue

        kind = doc.get('kind')
        if kind not in plural_map:
            # Not a custom resource, use utils.create_from_yaml
            continue

        group, version = doc['apiVersion'].split('/')
        metadata = doc['metadata']
        resource_namespace = metadata['namespace']
        plural = plural_map[kind]

        with contextlib.suppress(client.exceptions.ApiException):
            api.create_namespaced_custom_object(
                group=group,
                version=version,
                namespace=resource_namespace,
                plural=plural,
                body=doc
            )

    # 3. Wait for MCPServer 'echo' to be ready
    print("Waiting for MCPServer 'echo' to be ready...")

    def check_status():
        try:
            obj = api.get_namespaced_custom_object(GROUP, VERSION, namespace, PLURAL, "echo")
            status = obj.get("status", {})
            conditions = status.get("conditions", [])
            return any(c["type"] == "Ready" and c["status"] == "True" for c in conditions)
        except client.exceptions.ApiException:
            return False

    # Increase timeout because image pull might be slow
    ready = wait_for_resource(check_status, timeout=120)

    if not ready:
        # Debug info
        with contextlib.suppress(Exception):
            obj = api.get_namespaced_custom_object(GROUP, VERSION, namespace, PLURAL, "echo")
            print(f"MCPServer status: {obj.get('status')}")

            apps_v1 = client.AppsV1Api(k8s_client)
            deploy = apps_v1.read_namespaced_deployment("mcp-server-echo", namespace)
            print(f"Deployment status: {deploy.status}")

        pytest.fail("Echo MCPServer did not become ready")

    # 4. Verify Aggregation in ConfigMap
    print("Verifying ConfigMap content...")
    core_v1 = client.CoreV1Api(k8s_client)
    cm_name = "mcp-server-echo-config"
    cm = core_v1.read_namespaced_config_map(cm_name, namespace)

    tools = json.loads(cm.data["tools.json"])
    prompts = json.loads(cm.data["prompts.json"])
    resources = json.loads(cm.data["resources.json"])

    # Verify tools (echo and calculator)
    tool_names = [t["name"] for t in tools]
    assert "echo" in tool_names
    assert "calculator" in tool_names

    # Verify prompts
    prompt_names = [p["name"] for p in prompts]
    assert "greeting" in prompt_names
    assert "code-review" in prompt_names

    # Verify resources
    resource_names = [r["name"] for r in resources]
    assert "sample-config" in resource_names
    assert "readme" in resource_names
