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
from src.utils.metrics import MANAGED_RESOURCES, RECONCILIATION_DURATION, RECONCILIATION_TOTAL


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


def _resolve_tool_entry(
    tool_name: str | None,
    service_ref: dict[str, Any],
    input_schema: dict[str, Any] | None,
    namespace: str,
    k8s: Any,
) -> dict[str, Any] | None:
    """Resolve a tool's service reference to a ConfigMap entry.

    Args:
        tool_name: The MCP tool name.
        service_ref: Dict with name, port, path, namespace keys.
        input_schema: Optional JSON Schema for the tool.
        namespace: Default namespace if not specified in service_ref.
        k8s: The Kubernetes client.

    Returns:
        A dict with name, endpoint, inputSchema or None if unresolvable.
    """
    svc_name = service_ref.get("name")
    svc_port = service_ref.get("port")
    svc_path = service_ref.get("path", "/")
    svc_ns = service_ref.get("namespace") or namespace

    if svc_name and svc_port:
        base_endpoint = k8s.get_service_endpoint(svc_name, svc_ns, svc_port)
        if base_endpoint:
            return {
                "name": tool_name,
                "endpoint": f"{base_endpoint}{svc_path}",
                "inputSchema": input_schema,
            }
    return None


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
@kopf.on.update("mcp.k8s.turd.ninja", "v1alpha1", "mcpservers")  # type: ignore[arg-type]
async def reconcile_mcpserver(
    *,
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
    timer = RECONCILIATION_DURATION.labels(controller="mcpserver").time()
    timer.__enter__()

    try:
        await _reconcile_mcpserver_inner(
            spec=spec, name=name, namespace=namespace, logger=logger, patch=patch, body=body
        )
        RECONCILIATION_TOTAL.labels(controller="mcpserver", result="success").inc()
    except Exception:
        RECONCILIATION_TOTAL.labels(controller="mcpserver", result="error").inc()
        raise
    finally:
        timer.__exit__(None, None, None)


async def _reconcile_mcpserver_inner(
    *,
    spec: dict[str, Any],
    name: str,
    namespace: str,
    logger: kopf.Logger,
    patch: kopf.Patch,
    body: dict[str, Any],
) -> None:
    """Inner reconciliation logic for MCPServer."""
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
    logger.info(f"Found {len(tools)} MCPTool CRs matching selector")

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

    # Generate ConfigMap -- expand both single-tool and multi-tool MCPTool CRs
    tools_data: list[dict[str, Any]] = []
    for tool_cr in tools:
        tool_spec = tool_cr.get("spec", {})
        service_ref = tool_spec.get("service", {})

        if tool_spec.get("tools"):
            # Multi-tool MCPTool: each entry becomes a separate ConfigMap tool
            for tool_entry in tool_spec["tools"]:
                entry = _resolve_tool_entry(
                    tool_name=tool_entry.get("name"),
                    service_ref={**service_ref, "path": tool_entry.get("path", "/")},
                    input_schema=tool_entry.get("inputSchema"),
                    namespace=namespace,
                    k8s=k8s,
                )
                if entry:
                    tools_data.append(entry)
        else:
            # Single-tool MCPTool (existing behavior)
            entry = _resolve_tool_entry(
                tool_name=tool_spec.get("name"),
                service_ref=service_ref,
                input_schema=tool_spec.get("inputSchema"),
                namespace=namespace,
                k8s=k8s,
            )
            if entry:
                tools_data.append(entry)
    tool_count = len(tools_data)

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
                            "image": server_spec.image,
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

    MANAGED_RESOURCES.labels(kind="MCPServer").inc(0)  # ensure metric exists


@kopf.on.delete("mcp.k8s.turd.ninja", "v1alpha1", "mcpservers")  # type: ignore[arg-type]
async def delete_mcpserver(
    *,
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
