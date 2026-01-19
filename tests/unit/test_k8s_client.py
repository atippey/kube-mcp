"""Unit tests for K8s client utilities."""

from unittest.mock import MagicMock, patch

from src.utils.k8s_client import K8sClient, get_k8s_client


class TestK8sClientInit:
    """Tests for K8sClient initialization."""

    def test_init_loads_incluster_config(self) -> None:
        """Test that in-cluster config is tried first."""
        with (
            patch("src.utils.k8s_client.config.load_incluster_config") as mock_incluster,
            patch("src.utils.k8s_client.client.CoreV1Api"),
            patch("src.utils.k8s_client.client.AppsV1Api"),
            patch("src.utils.k8s_client.client.NetworkingV1Api"),
            patch("src.utils.k8s_client.client.CustomObjectsApi"),
        ):
            K8sClient()
            mock_incluster.assert_called_once()

    def test_init_falls_back_to_kubeconfig(self) -> None:
        """Test that kubeconfig is loaded when in-cluster fails."""
        from kubernetes.config import ConfigException

        with (
            patch(
                "src.utils.k8s_client.config.load_incluster_config",
                side_effect=ConfigException("Not in cluster"),
            ),
            patch("src.utils.k8s_client.config.load_kube_config") as mock_kubeconfig,
            patch("src.utils.k8s_client.client.CoreV1Api"),
            patch("src.utils.k8s_client.client.AppsV1Api"),
            patch("src.utils.k8s_client.client.NetworkingV1Api"),
            patch("src.utils.k8s_client.client.CustomObjectsApi"),
        ):
            K8sClient()
            mock_kubeconfig.assert_called_once()


class TestK8sClientGetService:
    """Tests for K8sClient.get_service."""

    def test_get_service_found(self) -> None:
        """Test getting a service that exists."""
        from kubernetes.config import ConfigException

        mock_service = MagicMock()
        mock_service.to_dict.return_value = {"metadata": {"name": "test-svc"}}

        with (
            patch(
                "src.utils.k8s_client.config.load_incluster_config",
                side_effect=ConfigException("Not in cluster"),
            ),
            patch("src.utils.k8s_client.config.load_kube_config"),
            patch("src.utils.k8s_client.client.CoreV1Api") as mock_core_v1,
            patch("src.utils.k8s_client.client.AppsV1Api"),
            patch("src.utils.k8s_client.client.NetworkingV1Api"),
            patch("src.utils.k8s_client.client.CustomObjectsApi"),
        ):
            mock_core_v1.return_value.read_namespaced_service.return_value = mock_service
            k8s = K8sClient()
            result = k8s.get_service("test-svc", "default")

            assert result == {"metadata": {"name": "test-svc"}}

    def test_get_service_not_found(self) -> None:
        """Test getting a service that doesn't exist."""
        from kubernetes.client.exceptions import ApiException
        from kubernetes.config import ConfigException

        with (
            patch(
                "src.utils.k8s_client.config.load_incluster_config",
                side_effect=ConfigException("Not in cluster"),
            ),
            patch("src.utils.k8s_client.config.load_kube_config"),
            patch("src.utils.k8s_client.client.CoreV1Api") as mock_core_v1,
            patch("src.utils.k8s_client.client.AppsV1Api"),
            patch("src.utils.k8s_client.client.NetworkingV1Api"),
            patch("src.utils.k8s_client.client.CustomObjectsApi"),
        ):
            mock_core_v1.return_value.read_namespaced_service.side_effect = ApiException(
                status=404, reason="Not Found"
            )
            k8s = K8sClient()
            result = k8s.get_service("missing-svc", "default")

            assert result is None


class TestK8sClientGetServiceEndpoint:
    """Tests for K8sClient.get_service_endpoint."""

    def test_get_service_endpoint_found(self) -> None:
        """Test getting endpoint for existing service."""
        from kubernetes.config import ConfigException

        mock_service = MagicMock()
        mock_service.to_dict.return_value = {"metadata": {"name": "test-svc"}}

        with (
            patch(
                "src.utils.k8s_client.config.load_incluster_config",
                side_effect=ConfigException("Not in cluster"),
            ),
            patch("src.utils.k8s_client.config.load_kube_config"),
            patch("src.utils.k8s_client.client.CoreV1Api") as mock_core_v1,
            patch("src.utils.k8s_client.client.AppsV1Api"),
            patch("src.utils.k8s_client.client.NetworkingV1Api"),
            patch("src.utils.k8s_client.client.CustomObjectsApi"),
        ):
            mock_core_v1.return_value.read_namespaced_service.return_value = mock_service
            k8s = K8sClient()
            result = k8s.get_service_endpoint("test-svc", "default", 8080)

            assert result == "http://test-svc.default.svc.cluster.local:8080"

    def test_get_service_endpoint_not_found(self) -> None:
        """Test getting endpoint for missing service returns None."""
        from kubernetes.client.exceptions import ApiException
        from kubernetes.config import ConfigException

        with (
            patch(
                "src.utils.k8s_client.config.load_incluster_config",
                side_effect=ConfigException("Not in cluster"),
            ),
            patch("src.utils.k8s_client.config.load_kube_config"),
            patch("src.utils.k8s_client.client.CoreV1Api") as mock_core_v1,
            patch("src.utils.k8s_client.client.AppsV1Api"),
            patch("src.utils.k8s_client.client.NetworkingV1Api"),
            patch("src.utils.k8s_client.client.CustomObjectsApi"),
        ):
            mock_core_v1.return_value.read_namespaced_service.side_effect = ApiException(
                status=404, reason="Not Found"
            )
            k8s = K8sClient()
            result = k8s.get_service_endpoint("missing-svc", "default", 8080)

            assert result is None


class TestK8sClientGetDeployment:
    """Tests for K8sClient.get_deployment."""

    def test_get_deployment_found(self) -> None:
        """Test getting a deployment that exists."""
        from kubernetes.config import ConfigException

        mock_deployment = MagicMock()
        mock_deployment.to_dict.return_value = {"metadata": {"name": "test-deploy"}}

        with (
            patch(
                "src.utils.k8s_client.config.load_incluster_config",
                side_effect=ConfigException("Not in cluster"),
            ),
            patch("src.utils.k8s_client.config.load_kube_config"),
            patch("src.utils.k8s_client.client.CoreV1Api"),
            patch("src.utils.k8s_client.client.AppsV1Api") as mock_apps_v1,
            patch("src.utils.k8s_client.client.NetworkingV1Api"),
            patch("src.utils.k8s_client.client.CustomObjectsApi"),
        ):
            mock_apps_v1.return_value.read_namespaced_deployment.return_value = mock_deployment
            k8s = K8sClient()
            result = k8s.get_deployment("test-deploy", "default")

            assert result == {"metadata": {"name": "test-deploy"}}

    def test_get_deployment_not_found(self) -> None:
        """Test getting a deployment that doesn't exist."""
        from kubernetes.client.exceptions import ApiException
        from kubernetes.config import ConfigException

        with (
            patch(
                "src.utils.k8s_client.config.load_incluster_config",
                side_effect=ConfigException("Not in cluster"),
            ),
            patch("src.utils.k8s_client.config.load_kube_config"),
            patch("src.utils.k8s_client.client.CoreV1Api"),
            patch("src.utils.k8s_client.client.AppsV1Api") as mock_apps_v1,
            patch("src.utils.k8s_client.client.NetworkingV1Api"),
            patch("src.utils.k8s_client.client.CustomObjectsApi"),
        ):
            mock_apps_v1.return_value.read_namespaced_deployment.side_effect = ApiException(
                status=404, reason="Not Found"
            )
            k8s = K8sClient()
            result = k8s.get_deployment("missing-deploy", "default")

            assert result is None


class TestK8sClientCreateOrUpdateDeployment:
    """Tests for K8sClient.create_or_update_deployment."""

    def test_create_or_update_deployment_patches_when_exists(self) -> None:
        """Test that patch is called when deployment exists."""
        from kubernetes.config import ConfigException

        mock_deployment = {"metadata": {"name": "test-deploy"}}
        mock_result = MagicMock()
        mock_result.to_dict.return_value = mock_deployment

        with (
            patch(
                "src.utils.k8s_client.config.load_incluster_config",
                side_effect=ConfigException("Not in cluster"),
            ),
            patch("src.utils.k8s_client.config.load_kube_config"),
            patch("src.utils.k8s_client.client.CoreV1Api"),
            patch("src.utils.k8s_client.client.AppsV1Api") as mock_apps_v1,
            patch("src.utils.k8s_client.client.NetworkingV1Api"),
            patch("src.utils.k8s_client.client.CustomObjectsApi"),
        ):
            mock_apps_v1.return_value.patch_namespaced_deployment.return_value = mock_result

            k8s = K8sClient()
            result = k8s.create_or_update_deployment("test-deploy", "default", mock_deployment)

            assert result == mock_deployment
            mock_apps_v1.return_value.patch_namespaced_deployment.assert_called_once_with(
                "test-deploy", "default", mock_deployment
            )
            mock_apps_v1.return_value.create_namespaced_deployment.assert_not_called()

    def test_create_or_update_deployment_creates_when_missing(self) -> None:
        """Test that create is called when patch fails with 404."""
        from kubernetes.client.exceptions import ApiException
        from kubernetes.config import ConfigException

        mock_deployment = {"metadata": {"name": "test-deploy"}}
        mock_result = MagicMock()
        mock_result.to_dict.return_value = mock_deployment

        with (
            patch(
                "src.utils.k8s_client.config.load_incluster_config",
                side_effect=ConfigException("Not in cluster"),
            ),
            patch("src.utils.k8s_client.config.load_kube_config"),
            patch("src.utils.k8s_client.client.CoreV1Api"),
            patch("src.utils.k8s_client.client.AppsV1Api") as mock_apps_v1,
            patch("src.utils.k8s_client.client.NetworkingV1Api"),
            patch("src.utils.k8s_client.client.CustomObjectsApi"),
        ):
            mock_apps_v1.return_value.patch_namespaced_deployment.side_effect = ApiException(
                status=404, reason="Not Found"
            )
            mock_apps_v1.return_value.create_namespaced_deployment.return_value = mock_result

            k8s = K8sClient()
            result = k8s.create_or_update_deployment("test-deploy", "default", mock_deployment)

            assert result == mock_deployment
            mock_apps_v1.return_value.patch_namespaced_deployment.assert_called_once()
            mock_apps_v1.return_value.create_namespaced_deployment.assert_called_once_with(
                "default", mock_deployment
            )


class TestK8sClientListByLabelSelector:
    """Tests for K8sClient.list_by_label_selector."""

    def test_list_by_label_selector_with_match_labels(self) -> None:
        """Test listing resources with matchLabels selector."""
        from kubernetes.config import ConfigException

        mock_result = {"items": [{"metadata": {"name": "item1"}}]}

        with (
            patch(
                "src.utils.k8s_client.config.load_incluster_config",
                side_effect=ConfigException("Not in cluster"),
            ),
            patch("src.utils.k8s_client.config.load_kube_config"),
            patch("src.utils.k8s_client.client.CoreV1Api"),
            patch("src.utils.k8s_client.client.AppsV1Api"),
            patch("src.utils.k8s_client.client.NetworkingV1Api"),
            patch("src.utils.k8s_client.client.CustomObjectsApi") as mock_custom,
        ):
            mock_custom.return_value.list_namespaced_custom_object.return_value = mock_result
            k8s = K8sClient()
            result = k8s.list_by_label_selector(
                group="mcp.k8s.turd.ninja",
                version="v1alpha1",
                plural="mcptools",
                namespace="default",
                label_selector={"matchLabels": {"app": "test"}},
            )

            assert len(result) == 1
            assert result[0]["metadata"]["name"] == "item1"

    def test_list_by_label_selector_empty_result(self) -> None:
        """Test listing resources with no matches."""
        from kubernetes.config import ConfigException

        mock_result = {"items": []}

        with (
            patch(
                "src.utils.k8s_client.config.load_incluster_config",
                side_effect=ConfigException("Not in cluster"),
            ),
            patch("src.utils.k8s_client.config.load_kube_config"),
            patch("src.utils.k8s_client.client.CoreV1Api"),
            patch("src.utils.k8s_client.client.AppsV1Api"),
            patch("src.utils.k8s_client.client.NetworkingV1Api"),
            patch("src.utils.k8s_client.client.CustomObjectsApi") as mock_custom,
        ):
            mock_custom.return_value.list_namespaced_custom_object.return_value = mock_result
            k8s = K8sClient()
            result = k8s.list_by_label_selector(
                group="mcp.k8s.turd.ninja",
                version="v1alpha1",
                plural="mcptools",
                namespace="default",
                label_selector={"matchLabels": {"app": "nonexistent"}},
            )

            assert len(result) == 0


class TestK8sClientBuildLabelSelectorString:
    """Tests for K8sClient._build_label_selector_string."""

    def test_build_match_labels(self) -> None:
        """Test building selector string from matchLabels."""
        from kubernetes.config import ConfigException

        with (
            patch(
                "src.utils.k8s_client.config.load_incluster_config",
                side_effect=ConfigException("Not in cluster"),
            ),
            patch("src.utils.k8s_client.config.load_kube_config"),
            patch("src.utils.k8s_client.client.CoreV1Api"),
            patch("src.utils.k8s_client.client.AppsV1Api"),
            patch("src.utils.k8s_client.client.NetworkingV1Api"),
            patch("src.utils.k8s_client.client.CustomObjectsApi"),
        ):
            k8s = K8sClient()
            result = k8s._build_label_selector_string(
                {"matchLabels": {"app": "test", "env": "prod"}}
            )

            # Order might vary, so check both parts are present
            assert "app=test" in result
            assert "env=prod" in result

    def test_build_match_expressions_in(self) -> None:
        """Test building selector string from matchExpressions with In operator."""
        from kubernetes.config import ConfigException

        with (
            patch(
                "src.utils.k8s_client.config.load_incluster_config",
                side_effect=ConfigException("Not in cluster"),
            ),
            patch("src.utils.k8s_client.config.load_kube_config"),
            patch("src.utils.k8s_client.client.CoreV1Api"),
            patch("src.utils.k8s_client.client.AppsV1Api"),
            patch("src.utils.k8s_client.client.NetworkingV1Api"),
            patch("src.utils.k8s_client.client.CustomObjectsApi"),
        ):
            k8s = K8sClient()
            result = k8s._build_label_selector_string(
                {
                    "matchExpressions": [
                        {"key": "env", "operator": "In", "values": ["dev", "staging"]}
                    ]
                }
            )

            assert "env in (dev,staging)" in result

    def test_build_match_expressions_exists(self) -> None:
        """Test building selector string with Exists operator."""
        from kubernetes.config import ConfigException

        with (
            patch(
                "src.utils.k8s_client.config.load_incluster_config",
                side_effect=ConfigException("Not in cluster"),
            ),
            patch("src.utils.k8s_client.config.load_kube_config"),
            patch("src.utils.k8s_client.client.CoreV1Api"),
            patch("src.utils.k8s_client.client.AppsV1Api"),
            patch("src.utils.k8s_client.client.NetworkingV1Api"),
            patch("src.utils.k8s_client.client.CustomObjectsApi"),
        ):
            k8s = K8sClient()
            result = k8s._build_label_selector_string(
                {"matchExpressions": [{"key": "managed-by", "operator": "Exists"}]}
            )

            assert "managed-by" in result

    def test_build_match_expressions_does_not_exist(self) -> None:
        """Test building selector string with DoesNotExist operator."""
        from kubernetes.config import ConfigException

        with (
            patch(
                "src.utils.k8s_client.config.load_incluster_config",
                side_effect=ConfigException("Not in cluster"),
            ),
            patch("src.utils.k8s_client.config.load_kube_config"),
            patch("src.utils.k8s_client.client.CoreV1Api"),
            patch("src.utils.k8s_client.client.AppsV1Api"),
            patch("src.utils.k8s_client.client.NetworkingV1Api"),
            patch("src.utils.k8s_client.client.CustomObjectsApi"),
        ):
            k8s = K8sClient()
            result = k8s._build_label_selector_string(
                {"matchExpressions": [{"key": "legacy", "operator": "DoesNotExist"}]}
            )

            assert "!legacy" in result


class TestGetK8sClient:
    """Tests for get_k8s_client singleton."""

    def test_get_k8s_client_returns_instance(self) -> None:
        """Test that get_k8s_client returns a K8sClient instance."""
        from kubernetes.config import ConfigException

        with (
            patch(
                "src.utils.k8s_client.config.load_incluster_config",
                side_effect=ConfigException("Not in cluster"),
            ),
            patch("src.utils.k8s_client.config.load_kube_config"),
            patch("src.utils.k8s_client.client.CoreV1Api"),
            patch("src.utils.k8s_client.client.AppsV1Api"),
            patch("src.utils.k8s_client.client.NetworkingV1Api"),
            patch("src.utils.k8s_client.client.CustomObjectsApi"),
        ):
            # Reset the singleton
            import src.utils.k8s_client

            src.utils.k8s_client._client = None

            client = get_k8s_client()
            assert isinstance(client, K8sClient)

            # Calling again should return the same instance
            client2 = get_k8s_client()
            assert client is client2


class TestK8sClientCreateOrUpdateIngress:
    """Tests for K8sClient.create_or_update_ingress."""

    def test_create_ingress_if_not_exists(self) -> None:
        """Test creating ingress if it doesn't exist."""
        from kubernetes.client.exceptions import ApiException
        from kubernetes.config import ConfigException

        mock_ingress = MagicMock()
        mock_ingress.to_dict.return_value = {"metadata": {"name": "test-ingress"}}

        with (
            patch(
                "src.utils.k8s_client.config.load_incluster_config",
                side_effect=ConfigException("Not in cluster"),
            ),
            patch("src.utils.k8s_client.config.load_kube_config"),
            patch("src.utils.k8s_client.client.CoreV1Api"),
            patch("src.utils.k8s_client.client.AppsV1Api"),
            patch("src.utils.k8s_client.client.NetworkingV1Api") as mock_networking_v1,
            patch("src.utils.k8s_client.client.CustomObjectsApi"),
        ):
            # Mock read to raise 404
            mock_networking_v1.return_value.read_namespaced_ingress.side_effect = ApiException(
                status=404
            )
            # Mock create to return the ingress
            mock_networking_v1.return_value.create_namespaced_ingress.return_value = mock_ingress

            k8s = K8sClient()
            result = k8s.create_or_update_ingress(
                name="test-ingress",
                namespace="default",
                host="example.com",
                path="/",
                service_name="test-svc",
                service_port=80,
            )

            assert result == {"metadata": {"name": "test-ingress"}}
            mock_networking_v1.return_value.read_namespaced_ingress.assert_called_once()
            mock_networking_v1.return_value.create_namespaced_ingress.assert_called_once()
            mock_networking_v1.return_value.replace_namespaced_ingress.assert_not_called()

    def test_update_ingress_if_exists(self) -> None:
        """Test updating ingress if it exists."""
        from kubernetes.config import ConfigException

        mock_existing = MagicMock()
        mock_existing.metadata.resource_version = "123"

        mock_ingress = MagicMock()
        mock_ingress.to_dict.return_value = {"metadata": {"name": "test-ingress"}}

        with (
            patch(
                "src.utils.k8s_client.config.load_incluster_config",
                side_effect=ConfigException("Not in cluster"),
            ),
            patch("src.utils.k8s_client.config.load_kube_config"),
            patch("src.utils.k8s_client.client.CoreV1Api"),
            patch("src.utils.k8s_client.client.AppsV1Api"),
            patch("src.utils.k8s_client.client.NetworkingV1Api") as mock_networking_v1,
            patch("src.utils.k8s_client.client.CustomObjectsApi"),
        ):
            # Mock read to return existing
            mock_networking_v1.return_value.read_namespaced_ingress.return_value = mock_existing
            # Mock replace to succeed
            mock_networking_v1.return_value.replace_namespaced_ingress.return_value = mock_ingress

            k8s = K8sClient()
            result = k8s.create_or_update_ingress(
                name="test-ingress",
                namespace="default",
                host="example.com",
                path="/",
                service_name="test-svc",
                service_port=80,
            )

            assert result == {"metadata": {"name": "test-ingress"}}
            mock_networking_v1.return_value.read_namespaced_ingress.assert_called_once()
            mock_networking_v1.return_value.replace_namespaced_ingress.assert_called_once()
            mock_networking_v1.return_value.create_namespaced_ingress.assert_not_called()

            # Verify resource_version was set
            call_args = mock_networking_v1.return_value.replace_namespaced_ingress.call_args
            body = call_args[0][2]
            assert body.metadata.resource_version == "123"

    def test_create_ingress_with_tls(self) -> None:
        """Test creating ingress with TLS."""
        from kubernetes.client.exceptions import ApiException
        from kubernetes.config import ConfigException

        mock_ingress = MagicMock()
        mock_ingress.to_dict.return_value = {"metadata": {"name": "test-ingress"}}

        with (
            patch(
                "src.utils.k8s_client.config.load_incluster_config",
                side_effect=ConfigException("Not in cluster"),
            ),
            patch("src.utils.k8s_client.config.load_kube_config"),
            patch("src.utils.k8s_client.client.CoreV1Api"),
            patch("src.utils.k8s_client.client.AppsV1Api"),
            patch("src.utils.k8s_client.client.NetworkingV1Api") as mock_networking_v1,
            patch("src.utils.k8s_client.client.CustomObjectsApi"),
        ):
            mock_networking_v1.return_value.read_namespaced_ingress.side_effect = ApiException(
                status=404
            )
            mock_networking_v1.return_value.create_namespaced_ingress.return_value = mock_ingress

            k8s = K8sClient()
            k8s.create_or_update_ingress(
                name="test-ingress",
                namespace="default",
                host="example.com",
                path="/",
                service_name="test-svc",
                service_port=80,
                tls_secret_name="tls-secret",
            )

            # Verify call arguments
            call_args = mock_networking_v1.return_value.create_namespaced_ingress.call_args
            body = call_args[0][1]  # Second positional argument is body
            assert body.spec.tls is not None
            assert len(body.spec.tls) == 1
            assert body.spec.tls[0].secret_name == "tls-secret"
