"""MCPPrompt controller.

Handles reconciliation of MCPPrompt resources. Responsible for:
- Validating template syntax ({{variable}} format)
- Ensuring all variables in template are declared in variables array
- Updating status with validated, conditions
- Triggering MCPServer reconciliation when prompt changes
"""

import re
from datetime import UTC, datetime
from typing import Any

import kopf
from kubernetes import client

from src.models.crds import MCPPromptSpec
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
        condition_type: The condition type (e.g., "Validated").
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


def _extract_template_variables(template: str) -> set[str]:
    """Extract variable names from a template string.

    Variables are in the format {{variable_name}}.

    Args:
        template: The template string to parse.

    Returns:
        A set of variable names found in the template.
    """
    pattern = r"\{\{([a-zA-Z0-9_]+)\}\}"
    return set(re.findall(pattern, template))


@kopf.on.create("mcp.k8s.turd.ninja", "v1alpha1", "mcpprompts")
@kopf.on.update("mcp.k8s.turd.ninja", "v1alpha1", "mcpprompts")  # type: ignore[arg-type]
async def reconcile_mcpprompt(
    *,
    spec: dict[str, Any],
    name: str,
    namespace: str,
    logger: kopf.Logger,
    patch: kopf.Patch,
    **_: object,
) -> None:
    """Reconcile an MCPPrompt resource.

    Args:
        spec: The MCPPrompt spec.
        name: The MCPPrompt name.
        namespace: The MCPPrompt namespace.
        logger: The kopf logger.
        patch: The kopf patch object.
        **_: Additional kwargs from kopf.
    """
    logger.info(f"Reconciling MCPPrompt {namespace}/{name}")

    with RECONCILIATION_DURATION.labels(controller="mcpprompt").time():
        try:
            await _reconcile_mcpprompt_inner(spec=spec, name=name, logger=logger, patch=patch)
            RECONCILIATION_TOTAL.labels(controller="mcpprompt", result="success").inc()
        except Exception:
            RECONCILIATION_TOTAL.labels(controller="mcpprompt", result="error").inc()
            raise


async def _reconcile_mcpprompt_inner(
    *,
    spec: dict[str, Any],
    name: str,
    logger: kopf.Logger,
    patch: kopf.Patch,
) -> None:
    """Inner reconciliation logic for MCPPrompt."""
    # Parse and validate spec
    prompt_spec = MCPPromptSpec(**spec)

    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")

    # Extract variables from template
    template_vars = _extract_template_variables(prompt_spec.template)

    # Get declared variable names
    declared_vars = {v.name for v in prompt_spec.variables}

    # Check for undeclared variables (in template but not declared)
    undeclared_vars = template_vars - declared_vars
    if undeclared_vars:
        logger.warning(f"MCPPrompt {name} has undeclared template variables: {undeclared_vars}")
        patch.status["validated"] = False
        patch.status["lastValidationTime"] = now
        patch.status["conditions"] = [
            _create_condition(
                condition_type="Validated",
                status="False",
                reason="UndeclaredVariables",
                message=f"Template uses undeclared variables: {', '.join(sorted(undeclared_vars))}",
            )
        ]
        return

    # Check for unused variables (declared but not in template)
    unused_vars = declared_vars - template_vars
    if unused_vars:
        logger.warning(f"MCPPrompt {name} has unused declared variables: {unused_vars}")
        patch.status["validated"] = False
        patch.status["lastValidationTime"] = now
        patch.status["conditions"] = [
            _create_condition(
                condition_type="Validated",
                status="False",
                reason="UnusedVariables",
                message=f"Declared variables not used in template: {', '.join(sorted(unused_vars))}",
            )
        ]
        return

    # Template is valid
    logger.info(f"MCPPrompt {name} validated successfully")

    patch.status["validated"] = True
    patch.status["lastValidationTime"] = now
    patch.status["conditions"] = [
        _create_condition(
            condition_type="Validated",
            status="True",
            reason="TemplateValid",
            message="Template and variables validated successfully",
        )
    ]


@kopf.on.delete("mcp.k8s.turd.ninja", "v1alpha1", "mcpprompts")  # type: ignore[arg-type]
async def delete_mcpprompt(
    *,
    name: str,
    namespace: str,
    logger: kopf.Logger,
    **_: object,
) -> None:
    """Handle MCPPrompt deletion.

    Args:
        name: The MCPPrompt name.
        namespace: The MCPPrompt namespace.
        logger: The kopf logger.
        **_: Additional kwargs from kopf.
    """
    logger.info(f"Deleting MCPPrompt {namespace}/{name}")
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
