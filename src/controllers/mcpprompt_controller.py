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

from src.models.crds import MCPPromptSpec


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
@kopf.on.update("mcp.k8s.turd.ninja", "v1alpha1", "mcpprompts")
async def reconcile_mcpprompt(
    spec: dict[str, Any],
    name: str,
    namespace: str,
    logger: kopf.Logger,
    **_: object,
) -> dict[str, Any]:
    """Reconcile an MCPPrompt resource.

    Args:
        spec: The MCPPrompt spec.
        name: The MCPPrompt name.
        namespace: The MCPPrompt namespace.
        logger: The kopf logger.
        **_: Additional kwargs from kopf.

    Returns:
        Status update dict with validated, conditions.
    """
    logger.info(f"Reconciling MCPPrompt {namespace}/{name}")

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
        return {
            "validated": False,
            "lastValidationTime": now,
            "conditions": [
                _create_condition(
                    condition_type="Validated",
                    status="False",
                    reason="UndeclaredVariables",
                    message=f"Template uses undeclared variables: {', '.join(sorted(undeclared_vars))}",
                )
            ],
        }

    # Check for unused variables (declared but not in template)
    unused_vars = declared_vars - template_vars
    if unused_vars:
        logger.warning(f"MCPPrompt {name} has unused declared variables: {unused_vars}")
        return {
            "validated": False,
            "lastValidationTime": now,
            "conditions": [
                _create_condition(
                    condition_type="Validated",
                    status="False",
                    reason="UnusedVariables",
                    message=f"Declared variables not used in template: {', '.join(sorted(unused_vars))}",
                )
            ],
        }

    # Template is valid
    logger.info(f"MCPPrompt {name} validated successfully")

    return {
        "validated": True,
        "lastValidationTime": now,
        "conditions": [
            _create_condition(
                condition_type="Validated",
                status="True",
                reason="TemplateValid",
                message="Template and variables validated successfully",
            )
        ],
    }


@kopf.on.delete("mcp.k8s.turd.ninja", "v1alpha1", "mcpprompts")
async def delete_mcpprompt(
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
    # TODO: Trigger MCPServer reconciliation to remove prompt
