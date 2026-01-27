"""Kubernetes client utilities.

Provides a wrapper around the kubernetes client for common operations
used by the MCP operator controllers.
"""

from typing import Any, cast

from kubernetes import client, config
from kubernetes.client.exceptions import ApiException


class K8sClient:
    """Kubernetes client wrapper for MCP operator operations."""

    def __init__(self) -> None:
        """Initialize the Kubernetes client.

        Attempts to load in-cluster config first, falls back to kubeconfig.
        """
        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()

        self.core_v1 = client.CoreV1Api()
        self.apps_v1 = client.AppsV1Api()
        self.networking_v1 = client.NetworkingV1Api()
        self.custom_objects = client.CustomObjectsApi()

    def get_service(self, name: str, namespace: str) -> dict[str, Any] | None:
        """Get a Service by name.

        Args:
            name: The service name.
            namespace: The service namespace.

        Returns:
            The service object as a dict, or None if not found.
        """
        try:
            svc = self.core_v1.read_namespaced_service(name, namespace)
            return cast(dict[str, Any], svc.to_dict())
        except ApiException as e:
            if e.status == 404:
                return None
            raise

    def get_service_endpoint(self, name: str, namespace: str, port: int) -> str | None:
        """Get the cluster-internal endpoint for a service.

        Args:
            name: The service name.
            namespace: The service namespace.
            port: The target port.

        Returns:
            The endpoint URL (e.g., "http://svc.ns.svc.cluster.local:8080"),
            or None if service not found.
        """
        svc = self.get_service(name, namespace)
        if svc is None:
            return None
        return f"http://{name}.{namespace}.svc.cluster.local:{port}"

    def get_deployment(self, name: str, namespace: str) -> dict[str, Any] | None:
        """Get a Deployment by name.

        Args:
            name: The deployment name.
            namespace: The deployment namespace.

        Returns:
            The deployment object as a dict, or None if not found.
        """
        try:
            deployment = self.apps_v1.read_namespaced_deployment(name, namespace)
            return cast(dict[str, Any], deployment.to_dict())
        except ApiException as e:
            if e.status == 404:
                return None
            raise

    def create_or_update_deployment(
        self,
        name: str,
        namespace: str,
        body: client.V1Deployment | dict[str, Any],
    ) -> dict[str, Any]:
        """Create or update a Deployment.

        Args:
            name: The deployment name.
            namespace: The deployment namespace.
            body: The deployment body.

        Returns:
            The created/updated deployment as a dict.
        """
        try:
            result = self.apps_v1.patch_namespaced_deployment(name, namespace, body)
        except ApiException as e:
            if e.status == 404:
                result = self.apps_v1.create_namespaced_deployment(namespace, body)
            else:
                raise

        return cast(dict[str, Any], result.to_dict())

    def list_by_label_selector(
        self,
        group: str,
        version: str,
        plural: str,
        namespace: str,
        label_selector: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """List custom resources by label selector.

        Args:
            group: The API group (e.g., "mcp.k8s.turd.ninja").
            version: The API version (e.g., "v1alpha1").
            plural: The resource plural name (e.g., "mcptools").
            namespace: The namespace to search in.
            label_selector: The label selector dict with matchLabels/matchExpressions.

        Returns:
            List of matching resources.
        """
        # Convert label selector to string format
        selector_str = self._build_label_selector_string(label_selector)

        try:
            result = self.custom_objects.list_namespaced_custom_object(
                group=group,
                version=version,
                namespace=namespace,
                plural=plural,
                label_selector=selector_str,
            )
            return cast(list[dict[str, Any]], result.get("items", []))
        except ApiException:
            return []

    def _build_label_selector_string(self, selector: dict[str, Any]) -> str:
        """Build a label selector string from a selector dict.

        Args:
            selector: Dict with matchLabels and/or matchExpressions.

        Returns:
            A comma-separated label selector string.
        """
        parts: list[str] = []

        # Handle matchLabels
        match_labels = selector.get("matchLabels", {})
        for key, value in match_labels.items():
            parts.append(f"{key}={value}")

        # Handle matchExpressions
        match_expressions = selector.get("matchExpressions", [])
        for expr in match_expressions:
            key = expr.get("key", "")
            operator = expr.get("operator", "")
            values = expr.get("values", [])

            if operator == "In":
                parts.append(f"{key} in ({','.join(values)})")
            elif operator == "NotIn":
                parts.append(f"{key} notin ({','.join(values)})")
            elif operator == "Exists":
                parts.append(key)
            elif operator == "DoesNotExist":
                parts.append(f"!{key}")

        return ",".join(parts)

    def create_or_update_configmap(
        self,
        name: str,
        namespace: str,
        data: dict[str, str],
        owner_reference: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create or update a ConfigMap.

        Args:
            name: The ConfigMap name.
            namespace: The ConfigMap namespace.
            data: The ConfigMap data.
            owner_reference: Optional owner reference for garbage collection.

        Returns:
            The created/updated ConfigMap.
        """
        metadata: dict[str, Any] = {"name": name, "namespace": namespace}
        if owner_reference:
            metadata["owner_references"] = [
                client.V1OwnerReference(
                    api_version=owner_reference.get("apiVersion"),
                    kind=owner_reference.get("kind"),
                    name=owner_reference.get("name"),
                    uid=owner_reference.get("uid"),
                    controller=owner_reference.get("controller", True),
                    block_owner_deletion=owner_reference.get("blockOwnerDeletion", True),
                )
            ]

        body = client.V1ConfigMap(
            api_version="v1",
            kind="ConfigMap",
            metadata=client.V1ObjectMeta(**metadata),
            data=data,
        )

        try:
            result = self.core_v1.replace_namespaced_config_map(name, namespace, body)
        except ApiException as e:
            if e.status == 404:
                result = self.core_v1.create_namespaced_config_map(namespace, body)
            else:
                raise

        return cast(dict[str, Any], result.to_dict())

    def create_or_update_service(
        self,
        name: str,
        namespace: str,
        ports: list[dict[str, Any]],
        selector: dict[str, str],
        owner_reference: dict[str, Any] | None = None,
        type: str = "ClusterIP",
    ) -> dict[str, Any]:
        """Create or update a Service.

        Args:
            name: The Service name.
            namespace: The Service namespace.
            ports: List of port configs (port, targetPort, protocol, name).
            selector: Label selector for pods.
            owner_reference: Optional owner reference for garbage collection.
            type: Service type (default: ClusterIP).

        Returns:
            The created/updated Service.
        """
        metadata: dict[str, Any] = {"name": name, "namespace": namespace}
        if owner_reference:
            metadata["owner_references"] = [
                client.V1OwnerReference(
                    api_version=owner_reference.get("apiVersion"),
                    kind=owner_reference.get("kind"),
                    name=owner_reference.get("name"),
                    uid=owner_reference.get("uid"),
                    controller=owner_reference.get("controller", True),
                    block_owner_deletion=owner_reference.get("blockOwnerDeletion", True),
                )
            ]

        # Ensure ports are valid V1ServicePort objects
        service_ports = []
        for port in ports:
            service_ports.append(
                client.V1ServicePort(
                    name=port.get("name"),
                    port=port["port"],
                    target_port=port.get("targetPort", port["port"]),
                    protocol=port.get("protocol", "TCP"),
                )
            )

        body = client.V1Service(
            api_version="v1",
            kind="Service",
            metadata=client.V1ObjectMeta(**metadata),
            spec=client.V1ServiceSpec(
                ports=service_ports,
                selector=selector,
                type=type,
            ),
        )

        try:
            # Try to get existing service first to preserve cluster IP
            existing = self.core_v1.read_namespaced_service(name, namespace)
            body.metadata.resource_version = existing.metadata.resource_version
            if type == "ClusterIP":
                body.spec.cluster_ip = existing.spec.cluster_ip

            result = self.core_v1.replace_namespaced_service(name, namespace, body)
        except ApiException as e:
            if e.status == 404:
                result = self.core_v1.create_namespaced_service(namespace, body)
            else:
                raise

        return cast(dict[str, Any], result.to_dict())

    def create_or_update_ingress(
        self,
        name: str,
        namespace: str,
        host: str | None,
        path: str,
        service_name: str,
        service_port: int,
        tls_secret_name: str | None = None,
        owner_reference: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create or update an Ingress.

        Args:
            name: The Ingress name.
            namespace: The Ingress namespace.
            host: The Ingress host (optional).
            path: The Ingress path.
            service_name: The backend service name.
            service_port: The backend service port.
            tls_secret_name: Optional TLS secret name.
            owner_reference: Optional owner reference.

        Returns:
            The created/updated Ingress.
        """
        metadata: dict[str, Any] = {"name": name, "namespace": namespace}
        if owner_reference:
            metadata["owner_references"] = [
                client.V1OwnerReference(
                    api_version=owner_reference.get("apiVersion"),
                    kind=owner_reference.get("kind"),
                    name=owner_reference.get("name"),
                    uid=owner_reference.get("uid"),
                    controller=owner_reference.get("controller", True),
                    block_owner_deletion=owner_reference.get("blockOwnerDeletion", True),
                )
            ]

        # Define Ingress Rule
        path_type = "Prefix"
        backend = client.V1IngressBackend(
            service=client.V1IngressServiceBackend(
                name=service_name,
                port=client.V1ServiceBackendPort(number=service_port),
            )
        )

        http_ingress_path = client.V1HTTPIngressPath(
            path=path,
            path_type=path_type,
            backend=backend,
        )

        rule = client.V1IngressRule(
            host=host,
            http=client.V1HTTPIngressRuleValue(paths=[http_ingress_path]),
        )

        # Define TLS
        tls = []
        if tls_secret_name:
            tls_entry = client.V1IngressTLS(
                hosts=[host] if host else [],
                secret_name=tls_secret_name,
            )
            tls.append(tls_entry)

        body = client.V1Ingress(
            api_version="networking.k8s.io/v1",
            kind="Ingress",
            metadata=client.V1ObjectMeta(**metadata),
            spec=client.V1IngressSpec(
                rules=[rule],
                tls=tls if tls else None,
            ),
        )

        try:
            existing = self.networking_v1.read_namespaced_ingress(name, namespace)
            body.metadata.resource_version = existing.metadata.resource_version
            result = self.networking_v1.replace_namespaced_ingress(name, namespace, body)
        except ApiException as e:
            if e.status == 404:
                result = self.networking_v1.create_namespaced_ingress(namespace, body)
            else:
                raise

        return cast(dict[str, Any], result.to_dict())


# Module-level client instance (lazy initialization)
_client: K8sClient | None = None


def get_k8s_client() -> K8sClient:
    """Get or create the singleton K8s client instance.

    Returns:
        The K8sClient instance.
    """
    global _client  # noqa: PLW0603
    if _client is None:
        _client = K8sClient()
    return _client
