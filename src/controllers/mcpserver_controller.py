"""MCPServer controller.

Handles reconciliation of MCPServer resources. Responsible for:
- Finding all MCPTool/MCPPrompt/MCPResource objects matching toolSelector
- Generating and applying Deployment, Service, Ingress, and ConfigMaps
- Setting owner references for cleanup
- Updating status with readyReplicas, toolCount, promptCount, resourceCount
"""

import json
import os
from datetime import UTC, datetime
from ipaddress import ip_network
from typing import Any

import kopf

from src.models.crds import MCPServerSpec
from src.utils.k8s_client import get_k8s_client
from src.utils.metrics import MANAGED_RESOURCES, RECONCILIATION_DURATION, RECONCILIATION_TOTAL

EGRESS_MODE_ANNOTATION = "mcp.k8s.turd.ninja/egress-mode"
EGRESS_PORTS_ANNOTATION = "mcp.k8s.turd.ninja/egress-ports"
EGRESS_CIDRS_ANNOTATION = "mcp.k8s.turd.ninja/egress-cidrs"
OPERATOR_API_SERVER_CIDR_ENV = "MCP_OPERATOR_API_SERVER_CIDR"
DEFAULT_OPERATOR_API_SERVER_CIDR = "0.0.0.0/0"
DEFAULT_OPERATOR_NAMESPACE = "mcp-system"


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
    if not tool_name:
        return None

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


def _parse_egress_ports(raw_ports: str | None, default_port: Any) -> list[int]:
    """Parse egress ports annotation, or fall back to service ref port."""
    if not raw_ports:
        return [int(default_port)] if default_port else []

    ports: list[int] = []
    for item in raw_ports.split(","):
        token = item.strip()
        if not token:
            continue
        port = int(token)
        if port < 1 or port > 65535:
            raise ValueError(f"Invalid egress port: {port}")
        ports.append(port)
    return sorted(set(ports))


def _parse_egress_cidrs(raw_cidrs: str | None) -> list[str]:
    """Parse and validate CIDR annotation values."""
    if not raw_cidrs:
        return []
    cidrs: list[str] = []
    for item in raw_cidrs.split(","):
        token = item.strip()
        if not token:
            continue
        cidrs.append(str(ip_network(token, strict=False)))
    return sorted(set(cidrs))


def _resolve_service_target(
    *,
    source_kind: str,
    source_name: str,
    service_ref: dict[str, Any],
    annotations: dict[str, str],
    namespace: str,
    k8s: Any,
) -> dict[str, Any] | None:
    """Resolve one service reference into a NetworkPolicy egress target."""
    svc_name = service_ref.get("name")
    svc_ns = service_ref.get("namespace") or namespace
    svc_port = service_ref.get("port")
    if not svc_name or not svc_port:
        return None

    svc = k8s.get_service(svc_name, svc_ns)
    if not isinstance(svc, dict):
        return None

    svc_spec = svc.get("spec")
    if not isinstance(svc_spec, dict):
        return None

    mode = annotations.get(EGRESS_MODE_ANNOTATION, "selector").strip().lower()
    if mode not in {"selector", "namespace", "cidr"}:
        raise ValueError(
            f"{source_kind} {source_name}: invalid {EGRESS_MODE_ANNOTATION}={mode!r}, "
            "expected selector|namespace|cidr"
        )

    ports = _parse_egress_ports(annotations.get(EGRESS_PORTS_ANNOTATION), svc_port)
    if not ports:
        raise ValueError(
            f"{source_kind} {source_name}: no egress ports resolved for {svc_ns}/{svc_name}"
        )

    svc_type = (svc_spec.get("type") or "ClusterIP").strip()
    selector_raw = svc_spec.get("selector")
    selector: dict[str, str] = selector_raw if isinstance(selector_raw, dict) else {}

    if svc_type == "ExternalName" and mode != "cidr":
        raise ValueError(
            f"{source_kind} {source_name}: service {svc_ns}/{svc_name} is ExternalName; "
            f"set {EGRESS_MODE_ANNOTATION}=cidr and {EGRESS_CIDRS_ANNOTATION}"
        )

    if mode == "selector":
        if not selector:
            raise ValueError(
                f"{source_kind} {source_name}: service {svc_ns}/{svc_name} has no selector; "
                f"use {EGRESS_MODE_ANNOTATION}=namespace or cidr"
            )
        return {"mode": "selector", "namespace": svc_ns, "selector": selector, "ports": ports}

    if mode == "namespace":
        return {"mode": "namespace", "namespace": svc_ns, "ports": ports}

    cidrs = _parse_egress_cidrs(annotations.get(EGRESS_CIDRS_ANNOTATION))
    if not cidrs:
        raise ValueError(
            f"{source_kind} {source_name}: {EGRESS_MODE_ANNOTATION}=cidr requires {EGRESS_CIDRS_ANNOTATION}"
        )
    return {"mode": "cidr", "cidrs": cidrs, "ports": ports}


def _collect_service_targets(
    tools: list[dict[str, Any]],
    resources: list[dict[str, Any]],
    namespace: str,
    k8s: Any,
) -> list[dict[str, Any]]:
    """Collect unique service targets from MCPTool and MCPResource CRs."""
    targets: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()

    def _add_target(target: dict[str, Any]) -> None:
        mode = target["mode"]
        key: tuple[Any, ...]
        if mode == "selector":
            key = (
                mode,
                target["namespace"],
                tuple(sorted(target["selector"].items())),
                tuple(target["ports"]),
            )
        elif mode == "namespace":
            key = (mode, target["namespace"], tuple(target["ports"]))
        else:
            key = (mode, tuple(target["cidrs"]), tuple(target["ports"]))

        if key not in seen:
            seen.add(key)
            targets.append(target)

    for tool_cr in tools:
        metadata = tool_cr.get("metadata", {})
        annotations = metadata.get("annotations", {}) if isinstance(metadata, dict) else {}
        if not isinstance(annotations, dict):
            annotations = {}
        tool_spec = tool_cr.get("spec", {})
        target = _resolve_service_target(
            source_kind="MCPTool",
            source_name=metadata.get("name", "<unknown>"),
            service_ref=tool_spec.get("service", {}),
            annotations=annotations,
            namespace=namespace,
            k8s=k8s,
        )
        if target:
            _add_target(target)

    for resource_cr in resources:
        metadata = resource_cr.get("metadata", {})
        annotations = metadata.get("annotations", {}) if isinstance(metadata, dict) else {}
        if not isinstance(annotations, dict):
            annotations = {}
        resource_spec = resource_cr.get("spec", {})
        for operation in resource_spec.get("operations", []) or []:
            target = _resolve_service_target(
                source_kind="MCPResource",
                source_name=metadata.get("name", "<unknown>"),
                service_ref=operation.get("service", {}),
                annotations=annotations,
                namespace=namespace,
                k8s=k8s,
            )
            if target:
                _add_target(target)

    return targets


def _build_server_networkpolicy(
    name: str,
    namespace: str,
    server_name: str,
    service_targets: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build an egress NetworkPolicy for MCP server pods.

    Generates precise egress rules for Redis, DNS, and each discovered
    tool service (by namespace + pod selector).

    Args:
        name: The NetworkPolicy name.
        namespace: The NetworkPolicy namespace.
        server_name: The MCPServer name (for pod selector).
        service_targets: List of service target dicts from _collect_service_targets.

    Returns:
        A NetworkPolicy body dict.
    """
    egress_rules: list[dict[str, Any]] = []

    # Redis (same namespace)
    egress_rules.append(
        {
            "to": [
                {
                    "podSelector": {
                        "matchLabels": {
                            "app.kubernetes.io/name": "mcp-redis",
                            "app.kubernetes.io/component": "cache",
                        }
                    }
                }
            ],
            "ports": [{"port": 6379, "protocol": "TCP"}],
        }
    )

    # DNS resolution
    egress_rules.append(
        {
            "to": [
                {
                    "namespaceSelector": {},
                    "podSelector": {"matchLabels": {"k8s-app": "kube-dns"}},
                }
            ],
            "ports": [
                {"port": 53, "protocol": "UDP"},
                {"port": 53, "protocol": "TCP"},
            ],
        }
    )

    # Service-backed egress targets from MCPTools and MCPResources.
    for target in service_targets:
        ports = [{"port": port, "protocol": "TCP"} for port in target["ports"]]
        if target["mode"] == "selector":
            to = [
                {
                    "namespaceSelector": {
                        "matchLabels": {
                            "kubernetes.io/metadata.name": target["namespace"],
                        }
                    },
                    "podSelector": {"matchLabels": target["selector"]},
                }
            ]
        elif target["mode"] == "namespace":
            to = [
                {
                    "namespaceSelector": {
                        "matchLabels": {
                            "kubernetes.io/metadata.name": target["namespace"],
                        }
                    }
                }
            ]
        else:
            to = [{"ipBlock": {"cidr": cidr}} for cidr in target["cidrs"]]

        rule: dict[str, Any] = {"to": to, "ports": ports}
        egress_rules.append(rule)

    return {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": {"name": name, "namespace": namespace},
        "spec": {
            "podSelector": {
                "matchLabels": {
                    "app.kubernetes.io/name": "mcp-server",
                    "app.kubernetes.io/instance": server_name,
                }
            },
            "policyTypes": ["Egress"],
            "egress": egress_rules,
        },
    }


def _resolve_operator_api_server_cidr(k8s: Any, logger: kopf.Logger) -> str:
    """Resolve operator API server egress CIDR from env override or auto-detect."""
    configured = os.getenv(OPERATOR_API_SERVER_CIDR_ENV)
    if configured:
        try:
            normalized = str(ip_network(configured.strip(), strict=False))
            logger.info(f"Using API server CIDR from {OPERATOR_API_SERVER_CIDR_ENV}: {normalized}")
            return normalized
        except ValueError:
            logger.warning(
                f"Ignoring invalid {OPERATOR_API_SERVER_CIDR_ENV} value: {configured!r}; "
                "falling back to auto-detect"
            )

    detected = k8s.get_api_server_cidr()
    if isinstance(detected, str) and detected.strip():
        try:
            normalized = str(ip_network(detected.strip(), strict=False))
            logger.info(f"Detected API server CIDR from kubernetes endpoints: {normalized}")
            return normalized
        except ValueError:
            logger.warning(f"Ignoring invalid detected API server CIDR: {detected!r}")

    logger.warning(
        "Falling back to broad API server CIDR allowlist "
        f"{DEFAULT_OPERATOR_API_SERVER_CIDR}; set {OPERATOR_API_SERVER_CIDR_ENV} to harden"
    )
    return DEFAULT_OPERATOR_API_SERVER_CIDR


def _build_operator_networkpolicy(namespace: str, api_server_cidr: str) -> dict[str, Any]:
    """Build operator NetworkPolicy with API-server egress pinned to resolved CIDR."""
    return {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": {"name": "mcp-operator-policy", "namespace": namespace},
        "spec": {
            "podSelector": {
                "matchLabels": {
                    "app.kubernetes.io/name": "mcp-operator",
                    "app.kubernetes.io/component": "operator",
                }
            },
            "policyTypes": ["Ingress", "Egress"],
            "ingress": [
                {
                    "ports": [
                        {"port": 8080, "protocol": "TCP"},
                        {"port": 9090, "protocol": "TCP"},
                    ]
                }
            ],
            "egress": [
                {
                    "to": [
                        {
                            "podSelector": {
                                "matchLabels": {
                                    "app.kubernetes.io/name": "mcp-redis",
                                    "app.kubernetes.io/component": "cache",
                                }
                            }
                        }
                    ],
                    "ports": [{"port": 6379, "protocol": "TCP"}],
                },
                {
                    "to": [{"ipBlock": {"cidr": api_server_cidr}}],
                    "ports": [
                        {"port": 443, "protocol": "TCP"},
                        {"port": 6443, "protocol": "TCP"},
                    ],
                },
                {
                    "to": [
                        {
                            "namespaceSelector": {},
                            "podSelector": {"matchLabels": {"k8s-app": "kube-dns"}},
                        }
                    ],
                    "ports": [
                        {"port": 53, "protocol": "UDP"},
                        {"port": 53, "protocol": "TCP"},
                    ],
                },
            ],
        },
    }


def _reconcile_operator_networkpolicy(k8s: Any, logger: kopf.Logger) -> None:
    """Reconcile shared operator NetworkPolicy with resolved API server CIDR."""
    operator_namespace = os.getenv("NAMESPACE", DEFAULT_OPERATOR_NAMESPACE)
    api_server_cidr = _resolve_operator_api_server_cidr(k8s, logger)
    operator_netpol = _build_operator_networkpolicy(operator_namespace, api_server_cidr)
    k8s.create_or_update_networkpolicy(
        name="mcp-operator-policy",
        namespace=operator_namespace,
        body=operator_netpol,
    )
    logger.info(
        f"Updated NetworkPolicy mcp-operator-policy in {operator_namespace} "
        f"with API egress CIDR {api_server_cidr}"
    )


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
    _reconcile_operator_networkpolicy(k8s, logger)

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
                tool_name = tool_entry.get("name")
                if not tool_name:
                    logger.warning(
                        "Skipping MCPTool entry with missing name in CR "
                        f"{tool_cr.get('metadata', {}).get('name', '<unknown>')}"
                    )
                    continue
                entry = _resolve_tool_entry(
                    tool_name=tool_name,
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

    # Generate egress NetworkPolicy from discovered tool/resource services
    service_targets = _collect_service_targets(tools, resources, namespace, k8s)
    netpol_name = f"mcp-server-{name}-egress"
    netpol_body = _build_server_networkpolicy(
        name=netpol_name,
        namespace=namespace,
        server_name=name,
        service_targets=service_targets,
    )
    k8s.create_or_update_networkpolicy(
        name=netpol_name,
        namespace=namespace,
        body=netpol_body,
        owner_reference=owner_ref,
    )
    logger.info(
        f"Updated NetworkPolicy {netpol_name} with {len(service_targets)} service target(s)"
    )

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
