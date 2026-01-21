"""MCPServer controller.

Handles reconciliation of MCPServer resources. Responsible for:
- Finding all MCPTool/MCPPrompt/MCPResource objects matching toolSelector
- Generating and applying Deployment, Service, Ingress, and ConfigMaps
- Setting owner references for cleanup
- Updating status with readyReplicas, toolCount, promptCount, resourceCount
"""

import json
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
        body: The full resource body (for owner references).
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

    # Generate ConfigMap
    tools_data = []
    for tool in tools:
        tool_spec = tool.get("spec", {})
        service_ref = tool_spec.get("service", {})

        svc_name = service_ref.get("name")
        svc_port = service_ref.get("port")
        svc_path = service_ref.get("path", "/")
        svc_ns = service_ref.get("namespace") or namespace

        if svc_name and svc_port:
            base_endpoint = k8s.get_service_endpoint(svc_name, svc_ns, svc_port)
            if base_endpoint:
                endpoint = f"{base_endpoint}{svc_path}"
                tools_data.append(
                    {
                        "name": tool_spec.get("name"),
                        "endpoint": endpoint,
                        "inputSchema": tool_spec.get("inputSchema"),
                    }
                )

    prompts_data = []
    for prompt in prompts:
        prompt_spec = prompt.get("spec", {})
        prompts_data.append(
            {
                "name": prompt_spec.get("name"),
                "template": prompt_spec.get("template"),
                "variables": prompt_spec.get("variables", []),
            }
        )

    resources_data = []
    for resource in resources:
        resource_spec = resource.get("spec", {})
        resources_data.append(
            {
                "name": resource_spec.get("name"),
                "content": resource_spec.get("content"),
                "operations": resource_spec.get("operations"),
            }
        )

    owner_ref = {
        "apiVersion": body.get("apiVersion"),
        "kind": body.get("kind"),
        "name": name,
        "uid": body.get("metadata", {}).get("uid"),
        "controller": True,
        "blockOwnerDeletion": True,
    }

    config_map_name = f"mcp-server-{name}-config"
    k8s.create_or_update_configmap(
        name=config_map_name,
        namespace=namespace,
        data={
            "tools.json": json.dumps(tools_data),
            "prompts.json": json.dumps(prompts_data),
            "resources.json": json.dumps(resources_data),
        },
        owner_reference=owner_ref,
    )
    logger.info(f"Updated ConfigMap {config_map_name}")

    # Create Ingress if configured
    if server_spec.ingress:
        logger.info(f"Creating/updating Ingress for MCPServer {name}")
        ingress_owner_ref = {
            "apiVersion": "mcp.k8s.turd.ninja/v1alpha1",
            "kind": "MCPServer",
            "name": name,
            "uid": body["metadata"]["uid"],
            "controller": True,
            "blockOwnerDeletion": True,
        }

        k8s.create_or_update_ingress(
            name=f"mcp-server-{name}",
            namespace=namespace,
            host=server_spec.ingress.host,
            path=server_spec.ingress.pathPrefix,
            service_name=f"mcp-server-{name}",
            service_port=8080,
            tls_secret_name=server_spec.ingress.tlsSecretName,
            owner_reference=ingress_owner_ref,
        )

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
                            "image": "ghcr.io/atippey/mcp-echo-server:latest",
                            "ports": [{"containerPort": 8080}],
                            "env": [
                                {
                                    "name": "REDIS_HOST",
                                    "value": server_spec.redis.serviceName,
                                },
                                {
                                    "name": "MCP_CONFIG_DIR",
                                    "value": "/etc/mcp/config",
                                },
                            ],
                            "volumeMounts": [
                                {
                                    "name": "config",
                                    "mountPath": "/etc/mcp/config",
                                    "readOnly": True,
                                }
                            ],
                        }
                    ],
                    "volumes": [
                        {
                            "name": "config",
                            "configMap": {
                                "name": config_map_name,
                            },
                        }
                    ],
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
