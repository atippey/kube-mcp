"""MCPServer controller.

Handles reconciliation of MCPServer resources. Responsible for:
- Finding all MCPTool/MCPPrompt/MCPResource objects matching toolSelector
- Generating and applying Deployment, Service, Ingress, and ConfigMaps
- Setting owner references for cleanup
- Updating status with readyReplicas, toolCount, promptCount, resourceCount
"""

from datetime import UTC, datetime
from typing import Any

import kopf

from src.models.crds import MCPServerSpec
from src.utils.k8s_client import get_k8s_client


def _create_condition(
    condition_type: str,
    status: str,
    reason: str,
    message: str,
) -> dict[str, Any]:
    """Create a Kubernetes-style condition dict.

    Args:
        condition_type: The condition type (e.g., "Ready").
        status: The condition status ("True", "False", "Unknown").
        reason: The reason code.
        message: Human-readable message.

    Returns:
        A condition dict.
    """
    return {
        "type": condition_type,
        "status": status,
        "lastTransitionTime": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "reason": reason,
        "message": message,
    }


def _selector_to_dict(selector: Any) -> dict[str, Any]:
    """Convert a LabelSelector model to a dict.

    Args:
        selector: The LabelSelector model.

    Returns:
        A dict with matchLabels and/or matchExpressions.
    """
    result: dict[str, Any] = {}
    if selector.matchLabels:
        result["matchLabels"] = selector.matchLabels
    if selector.matchExpressions:
        result["matchExpressions"] = [
            {
                "key": expr.key,
                "operator": expr.operator,
                "values": expr.values,
            }
            for expr in selector.matchExpressions
        ]
    return result


@kopf.on.create("mcp.k8s.turd.ninja", "v1alpha1", "mcpservers")
@kopf.on.update("mcp.k8s.turd.ninja", "v1alpha1", "mcpservers")
async def reconcile_mcpserver(
    spec: dict[str, Any],
    name: str,
    namespace: str,
    logger: kopf.Logger,
    patch: kopf.Patch,
    body: dict[str, Any],
    **_: object,
) -> None:
    """Reconcile an MCPServer resource.

    Args:
        spec: The MCPServer spec.
        name: The MCPServer name.
        namespace: The MCPServer namespace.
        logger: The kopf logger.
        patch: The kopf patch object.
        body: The full resource body.
        **_: Additional kwargs from kopf.
    """
    logger.info(f"Reconciling MCPServer {namespace}/{name}")

    # Parse and validate spec
    server_spec = MCPServerSpec(**spec)

    # Get K8s client
    k8s = get_k8s_client()

    # Convert tool selector to dict for API calls
    selector_dict = _selector_to_dict(server_spec.toolSelector)

    # Find matching MCPTools
    tools = k8s.list_by_label_selector(
        group="mcp.k8s.turd.ninja",
        version="v1alpha1",
        plural="mcptools",
        namespace=namespace,
        label_selector=selector_dict,
    )
    tool_count = len(tools)
    logger.info(f"Found {tool_count} MCPTools matching selector")

    # Find matching MCPPrompts
    prompts = k8s.list_by_label_selector(
        group="mcp.k8s.turd.ninja",
        version="v1alpha1",
        plural="mcpprompts",
        namespace=namespace,
        label_selector=selector_dict,
    )
    prompt_count = len(prompts)
    logger.info(f"Found {prompt_count} MCPPrompts matching selector")

    # Find matching MCPResources
    resources = k8s.list_by_label_selector(
        group="mcp.k8s.turd.ninja",
        version="v1alpha1",
        plural="mcpresources",
        namespace=namespace,
        label_selector=selector_dict,
    )
    resource_count = len(resources)
    logger.info(f"Found {resource_count} MCPResources matching selector")

    # Create Deployment
    deployment_name = f"mcp-server-{name}"
    deployment_labels = {
        "app.kubernetes.io/name": "mcp-server",
        "app.kubernetes.io/instance": name,
        "mcp.k8s.turd.ninja/server": name,
    }

    deployment_body = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {
            "name": deployment_name,
            "namespace": namespace,
            "labels": deployment_labels,
        },
        "spec": {
            "replicas": server_spec.replicas,
            "selector": {
                "matchLabels": {
                    "app.kubernetes.io/name": "mcp-server",
                    "app.kubernetes.io/instance": name,
                }
            },
            "template": {
                "metadata": {
                    "labels": deployment_labels,
                },
                "spec": {
                    "containers": [
                        {
                            "name": "server",
                            "image": "ghcr.io/atippey/mcp-server:latest",
                            "ports": [{"containerPort": 8080}],
                            "env": [
                                {
                                    "name": "REDIS_HOST",
                                    "value": server_spec.redis.serviceName,
                                }
                            ],
                        }
                    ]
                },
            },
        },
    }

    # Set owner reference
    kopf.adopt(deployment_body)

    # Create or update deployment
    k8s.create_or_update_deployment(deployment_name, namespace, deployment_body)

    # Create Service
    service_name = f"mcp-server-{name}"
    owner_reference = {
        "apiVersion": "mcp.k8s.turd.ninja/v1alpha1",
        "kind": "MCPServer",
        "name": name,
        "uid": body["metadata"]["uid"],
        "controller": True,
        "blockOwnerDeletion": True,
    }

    k8s.create_or_update_service(
        name=service_name,
        namespace=namespace,
        ports=[{"name": "http", "port": 8080, "targetPort": 8080, "protocol": "TCP"}],
        selector={
            "app.kubernetes.io/name": "mcp-server",
            "app.kubernetes.io/instance": name,
        },
        owner_reference=owner_reference,
    )

    # Check deployment status
    deployment = k8s.get_deployment(deployment_name, namespace)

    ready_replicas = 0
    if deployment and deployment.get("status"):
        ready_replicas = deployment["status"].get("readyReplicas") or 0

    # Determine ready status
    is_ready = ready_replicas > 0

    logger.info(
        f"MCPServer {name}: ready_replicas={ready_replicas}, "
        f"tools={tool_count}, prompts={prompt_count}, resources={resource_count}"
    )

    # Create condition based on deployment status
    if is_ready:
        condition = _create_condition(
            condition_type="Ready",
            status="True",
            reason="DeploymentReady",
            message=f"Deployment has {ready_replicas} ready replica(s)",
        )
    else:
        condition = _create_condition(
            condition_type="Ready",
            status="False",
            reason="DeploymentNotReady",
            message="Deployment has no ready replicas",
        )

    patch.status["readyReplicas"] = ready_replicas
    patch.status["toolCount"] = tool_count
    patch.status["promptCount"] = prompt_count
    patch.status["resourceCount"] = resource_count
    patch.status["conditions"] = [condition]


@kopf.on.delete("mcp.k8s.turd.ninja", "v1alpha1", "mcpservers")
async def delete_mcpserver(
    name: str,
    namespace: str,
    logger: kopf.Logger,
    **_: object,
) -> None:
    """Handle MCPServer deletion.

    Args:
        name: The MCPServer name.
        namespace: The MCPServer namespace.
        logger: The kopf logger.
        **_: Additional kwargs from kopf.
    """
    logger.info(f"Deleting MCPServer {namespace}/{name}")
    # Owner references handle cleanup automatically
