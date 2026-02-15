"""MCPTool controller.

Handles reconciliation of MCPTool resources. Responsible for:
- Validating service references exist
- Validating inputSchema is valid JSON Schema
- Resolving service endpoint (ClusterIP + port)
- Updating status with ready, resolvedEndpoint, conditions
- Triggering MCPServer reconciliation when tool changes
"""

from datetime import UTC, datetime
from typing import Any

import kopf
from kubernetes import client

from src.models.crds import MCPToolSpec
from src.utils.k8s_client import get_k8s_client
from src.utils.metrics import RECONCILIATION_DURATION, RECONCILIATION_TOTAL


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


@kopf.on.create("mcp.k8s.turd.ninja", "v1alpha1", "mcptools")
@kopf.on.update("mcp.k8s.turd.ninja", "v1alpha1", "mcptools")  # type: ignore[arg-type]
async def reconcile_mcptool(
    *,
    spec: dict[str, Any],
    name: str,
    namespace: str,
    logger: kopf.Logger,
    patch: kopf.Patch,
    **_: object,
) -> None:
    """Reconcile an MCPTool resource.

    Args:
        spec: The MCPTool spec.
        name: The MCPTool name.
        namespace: The MCPTool namespace.
        logger: The kopf logger.
        patch: The kopf patch object.
        **_: Additional kwargs from kopf.
    """
    logger.info(f"Reconciling MCPTool {namespace}/{name}")

    with RECONCILIATION_DURATION.labels(controller="mcptool").time():
        try:
            await _reconcile_mcptool_inner(
                spec=spec, name=name, namespace=namespace, logger=logger, patch=patch
            )
            RECONCILIATION_TOTAL.labels(controller="mcptool", result="success").inc()
        except Exception:
            RECONCILIATION_TOTAL.labels(controller="mcptool", result="error").inc()
            raise


async def _reconcile_mcptool_inner(
    *,
    spec: dict[str, Any],
    name: str,
    namespace: str,
    logger: kopf.Logger,
    patch: kopf.Patch,
) -> None:
    """Inner reconciliation logic for MCPTool."""
    # Parse and validate spec
    tool_spec = MCPToolSpec(**spec)

    # Determine the namespace to look up the service in
    service_namespace = tool_spec.service.namespace or namespace

    # Get K8s client and check if service exists
    k8s = get_k8s_client()
    service = k8s.get_service(tool_spec.service.name, service_namespace)

    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")

    if service is None:
        # Service not found
        logger.warning(
            f"Service {tool_spec.service.name} not found in namespace {service_namespace}"
        )
        patch.status["ready"] = False
        patch.status["resolvedEndpoint"] = None
        patch.status["lastSyncTime"] = now
        patch.status["conditions"] = [
            _create_condition(
                condition_type="Ready",
                status="False",
                reason="ServiceNotFound",
                message=f"Service {tool_spec.service.name} not found in namespace {service_namespace}",
            )
        ]
        return

    # Service exists - resolve endpoint
    base_endpoint = k8s.get_service_endpoint(
        tool_spec.service.name,
        service_namespace,
        tool_spec.service.port,
    )

    if tool_spec.tools:
        # Multi-tool mode: resolved endpoint is the base service URL
        resolved_endpoint = base_endpoint or ""
        tool_count = len(tool_spec.tools)
        logger.info(
            f"Resolved base endpoint for multi-tool MCPTool {name} "
            f"({tool_count} tools): {resolved_endpoint}"
        )
    else:
        # Single-tool mode: append path from spec
        resolved_endpoint = f"{base_endpoint}{tool_spec.service.path}"
        # Clean up double slashes (except in http://)
        resolved_endpoint = resolved_endpoint.replace("://", "___PROTO___")
        while "//" in resolved_endpoint:
            resolved_endpoint = resolved_endpoint.replace("//", "/")
        resolved_endpoint = resolved_endpoint.replace("___PROTO___", "://")
        logger.info(f"Resolved endpoint for MCPTool {name}: {resolved_endpoint}")

    patch.status["ready"] = True
    patch.status["resolvedEndpoint"] = resolved_endpoint
    patch.status["lastSyncTime"] = now
    patch.status["conditions"] = [
        _create_condition(
            condition_type="Ready",
            status="True",
            reason="ServiceResolved",
            message=f"Service {tool_spec.service.name} resolved to {resolved_endpoint}",
        )
    ]

    # Trigger MCPServer reconciliation
    await _trigger_mcpserver_reconciliation(namespace, logger)


@kopf.on.delete("mcp.k8s.turd.ninja", "v1alpha1", "mcptools")  # type: ignore[arg-type]
async def delete_mcptool(
    *,
    name: str,
    namespace: str,
    logger: kopf.Logger,
    **_: object,
) -> None:
    """Handle MCPTool deletion.

    Args:
        name: The MCPTool name.
        namespace: The MCPTool namespace.
        logger: The kopf logger.
        **_: Additional kwargs from kopf.
    """
    logger.info(f"Deleting MCPTool {namespace}/{name}")
    await _trigger_mcpserver_reconciliation(namespace, logger)


async def _trigger_mcpserver_reconciliation(namespace: str, logger: kopf.Logger) -> None:
    """Trigger MCPServer reconciliation when tools/prompts/resources change.

    Args:
        namespace: The namespace to search for MCPServers.
        logger: The kopf logger.
    """
    k8s = get_k8s_client()

    # Find all MCPServers in this namespace
    servers = k8s.list_by_label_selector(
        group="mcp.k8s.turd.ninja",
        version="v1alpha1",
        plural="mcpservers",
        namespace=namespace,
        label_selector={},  # Get all servers
    )

    if not servers:
        return

    # Patch each server to trigger reconciliation
    api = client.CustomObjectsApi()
    for server in servers:
        server_name = server["metadata"]["name"]
        try:
            # Touch the server's metadata to trigger reconcile
            patch = {
                "metadata": {
                    "annotations": {
                        "mcp.k8s.turd.ninja/last-child-update": datetime.now(UTC).isoformat()
                    }
                }
            }

            api.patch_namespaced_custom_object(
                group="mcp.k8s.turd.ninja",
                version="v1alpha1",
                namespace=namespace,
                plural="mcpservers",
                name=server_name,
                body=patch,
            )
            logger.info(f"Triggered reconciliation for MCPServer {namespace}/{server_name}")
        except Exception as e:
            logger.warning(f"Failed to trigger reconciliation for {server_name}: {e}")
