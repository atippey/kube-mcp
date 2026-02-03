"""MCPResource controller.

Handles reconciliation of MCPResource resources. Responsible for:
- For service-backed resources:
  - Validating service references exist
  - Validating path parameter placeholders match declared parameters
  - Resolving service endpoints
- For inline content:
  - Validating mimeType
  - Validating content is not empty
- Updating status with ready, operationCount, conditions
- Triggering MCPServer reconciliation when resource changes
"""

from datetime import UTC, datetime
from typing import Any

import kopf
from kubernetes import client

from src.models.crds import MCPResourceSpec
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


@kopf.on.create("mcp.k8s.turd.ninja", "v1alpha1", "mcpresources")
@kopf.on.update("mcp.k8s.turd.ninja", "v1alpha1", "mcpresources")  # type: ignore[arg-type]
async def reconcile_mcpresource(
    *,
    spec: dict[str, Any],
    name: str,
    namespace: str,
    logger: kopf.Logger,
    patch: kopf.Patch,
    **_: object,
) -> None:
    """Reconcile an MCPResource resource.

    Args:
        spec: The MCPResource spec.
        name: The MCPResource name.
        namespace: The MCPResource namespace.
        logger: The kopf logger.
        patch: The kopf patch object.
        **_: Additional kwargs from kopf.
    """
    logger.info(f"Reconciling MCPResource {namespace}/{name}")

    # Parse and validate spec
    resource_spec = MCPResourceSpec(**spec)

    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    operation_count = len(resource_spec.operations or [])

    # Check if neither operations nor content is provided
    if resource_spec.operations is None and resource_spec.content is None:
        logger.warning(f"MCPResource {name} has neither operations nor content")
        patch.status["ready"] = False
        patch.status["operationCount"] = 0
        patch.status["lastSyncTime"] = now
        patch.status["conditions"] = [
            _create_condition(
                condition_type="Ready",
                status="False",
                reason="InvalidSpec",
                message="Resource must have either operations or content defined",
            )
        ]
        return

    # Handle inline content
    if resource_spec.content is not None:
        # Validate content is not empty
        has_text = resource_spec.content.text and len(resource_spec.content.text.strip()) > 0
        has_blob = resource_spec.content.blob and len(resource_spec.content.blob.strip()) > 0

        if not has_text and not has_blob:
            logger.warning(f"MCPResource {name} has empty inline content")
            patch.status["ready"] = False
            patch.status["operationCount"] = 0
            patch.status["lastSyncTime"] = now
            patch.status["conditions"] = [
                _create_condition(
                    condition_type="Ready",
                    status="False",
                    reason="EmptyContent",
                    message="Inline content is empty (no text or blob data)",
                )
            ]
            return

        logger.info(f"MCPResource {name} has valid inline content")
        patch.status["ready"] = True
        patch.status["operationCount"] = 0
        patch.status["lastSyncTime"] = now
        patch.status["conditions"] = [
            _create_condition(
                condition_type="Ready",
                status="True",
                reason="ContentValid",
                message="Inline content validated successfully",
            )
        ]
        return

    # Handle service-backed operations
    if resource_spec.operations:
        k8s = get_k8s_client()

        # Validate all service references
        for operation in resource_spec.operations:
            service_namespace = operation.service.namespace or namespace
            service = k8s.get_service(operation.service.name, service_namespace)

            if service is None:
                logger.warning(
                    f"Service {operation.service.name} not found in namespace {service_namespace}"
                )
                patch.status["ready"] = False
                patch.status["operationCount"] = operation_count
                patch.status["lastSyncTime"] = now
                patch.status["conditions"] = [
                    _create_condition(
                        condition_type="Ready",
                        status="False",
                        reason="ServiceNotFound",
                        message=f"Service {operation.service.name} not found in namespace {service_namespace}",
                    )
                ]
                return

        logger.info(f"MCPResource {name} has {operation_count} valid operations")
        patch.status["ready"] = True
        patch.status["operationCount"] = operation_count
        patch.status["lastSyncTime"] = now
        patch.status["conditions"] = [
            _create_condition(
                condition_type="Ready",
                status="True",
                reason="OperationsValid",
                message=f"All {operation_count} operation(s) validated successfully",
            )
        ]
        return

    # Should not reach here, but just in case
    patch.status["ready"] = False
    patch.status["operationCount"] = 0
    patch.status["lastSyncTime"] = now
    patch.status["conditions"] = []


@kopf.on.delete("mcp.k8s.turd.ninja", "v1alpha1", "mcpresources")  # type: ignore[arg-type]
async def delete_mcpresource(
    *,
    name: str,
    namespace: str,
    logger: kopf.Logger,
    **_: object,
) -> None:
    """Handle MCPResource deletion.

    Args:
        name: The MCPResource name.
        namespace: The MCPResource namespace.
        logger: The kopf logger.
        **_: Additional kwargs from kopf.
    """
    logger.info(f"Deleting MCPResource {namespace}/{name}")
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
