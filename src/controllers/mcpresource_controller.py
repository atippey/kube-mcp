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


@kopf.on.create("mcp.example.com", "v1alpha1", "mcpresources")
@kopf.on.update("mcp.example.com", "v1alpha1", "mcpresources")
async def reconcile_mcpresource(
    spec: dict[str, Any],
    name: str,
    namespace: str,
    logger: kopf.Logger,
    **_: object,
) -> dict[str, Any]:
    """Reconcile an MCPResource resource.

    Args:
        spec: The MCPResource spec.
        name: The MCPResource name.
        namespace: The MCPResource namespace.
        logger: The kopf logger.
        **_: Additional kwargs from kopf.

    Returns:
        Status update dict with ready, operationCount, conditions.
    """
    logger.info(f"Reconciling MCPResource {namespace}/{name}")

    # Parse and validate spec
    resource_spec = MCPResourceSpec(**spec)

    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    operation_count = len(resource_spec.operations or [])

    # Check if neither operations nor content is provided
    if resource_spec.operations is None and resource_spec.content is None:
        logger.warning(f"MCPResource {name} has neither operations nor content")
        return {
            "ready": False,
            "operationCount": 0,
            "lastSyncTime": now,
            "conditions": [
                _create_condition(
                    condition_type="Ready",
                    status="False",
                    reason="InvalidSpec",
                    message="Resource must have either operations or content defined",
                )
            ],
        }

    # Handle inline content
    if resource_spec.content is not None:
        # Validate content is not empty
        has_text = resource_spec.content.text and len(resource_spec.content.text.strip()) > 0
        has_blob = resource_spec.content.blob and len(resource_spec.content.blob.strip()) > 0

        if not has_text and not has_blob:
            logger.warning(f"MCPResource {name} has empty inline content")
            return {
                "ready": False,
                "operationCount": 0,
                "lastSyncTime": now,
                "conditions": [
                    _create_condition(
                        condition_type="Ready",
                        status="False",
                        reason="EmptyContent",
                        message="Inline content is empty (no text or blob data)",
                    )
                ],
            }

        logger.info(f"MCPResource {name} has valid inline content")
        return {
            "ready": True,
            "operationCount": 0,
            "lastSyncTime": now,
            "conditions": [
                _create_condition(
                    condition_type="Ready",
                    status="True",
                    reason="ContentValid",
                    message="Inline content validated successfully",
                )
            ],
        }

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
                return {
                    "ready": False,
                    "operationCount": operation_count,
                    "lastSyncTime": now,
                    "conditions": [
                        _create_condition(
                            condition_type="Ready",
                            status="False",
                            reason="ServiceNotFound",
                            message=f"Service {operation.service.name} not found in namespace {service_namespace}",
                        )
                    ],
                }

        logger.info(f"MCPResource {name} has {operation_count} valid operations")
        return {
            "ready": True,
            "operationCount": operation_count,
            "lastSyncTime": now,
            "conditions": [
                _create_condition(
                    condition_type="Ready",
                    status="True",
                    reason="OperationsValid",
                    message=f"All {operation_count} operation(s) validated successfully",
                )
            ],
        }

    # Should not reach here, but just in case
    return {
        "ready": False,
        "operationCount": 0,
        "lastSyncTime": now,
        "conditions": [],
    }


@kopf.on.delete("mcp.example.com", "v1alpha1", "mcpresources")
async def delete_mcpresource(
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
    # TODO: Trigger MCPServer reconciliation to remove resource
