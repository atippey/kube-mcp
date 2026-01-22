"""Unit tests for MCPServer controller."""

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.controllers.mcpserver_controller import reconcile_mcpserver
from src.models.crds import MCPServerSpec


class TestMCPServerSpec:
    """Tests for MCPServerSpec validation."""

    def test_valid_spec(self, sample_mcpserver_spec: dict[str, Any]) -> None:
        """Test that a valid spec is accepted."""
        spec = MCPServerSpec(**sample_mcpserver_spec)
        assert spec.replicas == 2
        assert spec.redis.serviceName == "mcp-redis"
        assert spec.toolSelector.matchLabels == {"mcp-server": "main"}

    def test_default_replicas(self) -> None:
        """Test that replicas defaults to 1."""
        spec = MCPServerSpec(
            redis={"serviceName": "redis"},
            toolSelector={"matchLabels": {"app": "test"}},
        )
        assert spec.replicas == 1

    def test_replicas_range(self) -> None:
        """Test that replicas must be between 1 and 10."""
        with pytest.raises(ValueError):
            MCPServerSpec(
                replicas=0,
                redis={"serviceName": "redis"},
                toolSelector={"matchLabels": {"app": "test"}},
            )

        with pytest.raises(ValueError):
            MCPServerSpec(
                replicas=11,
                redis={"serviceName": "redis"},
                toolSelector={"matchLabels": {"app": "test"}},
            )

    def test_ingress_optional(self) -> None:
        """Test that ingress is optional."""
        spec = MCPServerSpec(
            redis={"serviceName": "redis"},
            toolSelector={"matchLabels": {"app": "test"}},
        )
        assert spec.ingress is None

    def test_config_defaults(self) -> None:
        """Test that config has sensible defaults."""
        spec = MCPServerSpec(
            redis={"serviceName": "redis"},
            toolSelector={"matchLabels": {"app": "test"}},
        )
        assert spec.config is None  # Config is optional, gets defaults when processed


class TestMCPServerReconciliation:
    """Tests for MCPServer reconciliation logic."""

    @pytest.fixture
    def mock_logger(self) -> MagicMock:
        """Create a mock logger."""
        return MagicMock()

    @pytest.fixture
    def mock_tools(self) -> list[dict[str, Any]]:
        """Create sample tool objects."""
        return [
            {
                "metadata": {"name": "tool1", "namespace": "default"},
                "spec": {"name": "tool1", "service": {"name": "svc1", "port": 8080}},
                "status": {"ready": True, "resolvedEndpoint": "http://svc1:8080"},
            },
            {
                "metadata": {"name": "tool2", "namespace": "default"},
                "spec": {"name": "tool2", "service": {"name": "svc2", "port": 8080}},
                "status": {"ready": True, "resolvedEndpoint": "http://svc2:8080"},
            },
        ]

    @pytest.fixture
    def mock_prompts(self) -> list[dict[str, Any]]:
        """Create sample prompt objects."""
        return [
            {
                "metadata": {"name": "prompt1", "namespace": "default"},
                "spec": {"name": "prompt1", "template": "Hello {{name}}"},
                "status": {"validated": True},
            },
        ]

    @pytest.fixture
    def mock_resources(self) -> list[dict[str, Any]]:
        """Create sample resource objects."""
        return [
            {
                "metadata": {"name": "resource1", "namespace": "default"},
                "spec": {"name": "resource1", "content": {"uri": "file://test", "text": "data"}},
                "status": {"ready": True, "operationCount": 0},
            },
        ]

    @pytest.fixture(autouse=True)
    def mock_adopt(self) -> MagicMock:
        """Mock kopf.adopt for all tests in this class."""
        with patch("src.controllers.mcpserver_controller.kopf.adopt") as mock:
            yield mock

    @pytest.fixture
    def sample_body(self) -> dict[str, Any]:
        """Create a sample resource body."""
        return {
            "metadata": {
                "name": "test-server",
                "namespace": "default",
                "uid": "test-uid-123",
            }
        }

    @pytest.mark.asyncio
    async def test_reconcile_finds_tools_by_selector(
        self,
        sample_mcpserver_spec: dict[str, Any],
        mock_logger: MagicMock,
        mock_tools: list[dict[str, Any]],
        sample_body: dict[str, Any],
    ) -> None:
        """Test that reconciliation finds tools matching label selector."""
        mock_k8s = MagicMock()
        mock_k8s.list_by_label_selector.side_effect = [
            mock_tools,
            [],
            [],
        ]  # tools, prompts, resources
        mock_k8s.get_deployment.return_value = {"status": {"readyReplicas": 1}}
        mock_patch_obj = MagicMock()
        mock_patch_obj.status = {}

        with patch("src.controllers.mcpserver_controller.get_k8s_client", return_value=mock_k8s):
            await reconcile_mcpserver(
                spec=sample_mcpserver_spec,
                name="test-server",
                namespace="default",
                logger=mock_logger,
                patch=mock_patch_obj,
                body=sample_body,
            )

        assert mock_patch_obj.status["toolCount"] == 2
        mock_k8s.list_by_label_selector.assert_called()

    @pytest.mark.asyncio
    async def test_reconcile_counts_prompts_and_resources(
        self,
        sample_mcpserver_spec: dict[str, Any],
        mock_logger: MagicMock,
        mock_tools: list[dict[str, Any]],
        mock_prompts: list[dict[str, Any]],
        mock_resources: list[dict[str, Any]],
        sample_body: dict[str, Any],
    ) -> None:
        """Test that reconciliation counts prompts and resources."""
        mock_k8s = MagicMock()
        mock_k8s.list_by_label_selector.side_effect = [mock_tools, mock_prompts, mock_resources]
        mock_k8s.get_deployment.return_value = {"status": {"readyReplicas": 1}}
        mock_patch_obj = MagicMock()
        mock_patch_obj.status = {}

        with patch("src.controllers.mcpserver_controller.get_k8s_client", return_value=mock_k8s):
            await reconcile_mcpserver(
                spec=sample_mcpserver_spec,
                name="test-server",
                namespace="default",
                logger=mock_logger,
                patch=mock_patch_obj,
                body=sample_body,
            )

        assert mock_patch_obj.status["toolCount"] == 2
        assert mock_patch_obj.status["promptCount"] == 1
        assert mock_patch_obj.status["resourceCount"] == 1

    @pytest.mark.asyncio
    async def test_reconcile_sets_ready_replicas(
        self,
        sample_mcpserver_spec: dict[str, Any],
        mock_logger: MagicMock,
        sample_body: dict[str, Any],
    ) -> None:
        """Test that reconciliation sets readyReplicas based on deployment."""
        mock_k8s = MagicMock()
        mock_k8s.list_by_label_selector.side_effect = [[], [], []]  # No tools, prompts, resources
        mock_k8s.get_deployment.return_value = {
            "status": {"readyReplicas": 2},
        }
        mock_patch_obj = MagicMock()
        mock_patch_obj.status = {}

        with patch("src.controllers.mcpserver_controller.get_k8s_client", return_value=mock_k8s):
            await reconcile_mcpserver(
                spec=sample_mcpserver_spec,
                name="test-server",
                namespace="default",
                logger=mock_logger,
                patch=mock_patch_obj,
                body=sample_body,
            )

        assert mock_patch_obj.status["readyReplicas"] == 2

    @pytest.mark.asyncio
    async def test_reconcile_deployment_not_found_sets_zero_replicas(
        self,
        sample_mcpserver_spec: dict[str, Any],
        mock_logger: MagicMock,
        sample_body: dict[str, Any],
    ) -> None:
        """Test that reconciliation sets readyReplicas to 0 when deployment not found."""
        mock_k8s = MagicMock()
        mock_k8s.list_by_label_selector.side_effect = [[], [], []]
        mock_k8s.get_deployment.return_value = None
        mock_patch_obj = MagicMock()
        mock_patch_obj.status = {}

        with patch("src.controllers.mcpserver_controller.get_k8s_client", return_value=mock_k8s):
            await reconcile_mcpserver(
                spec=sample_mcpserver_spec,
                name="test-server",
                namespace="default",
                logger=mock_logger,
                patch=mock_patch_obj,
                body=sample_body,
            )

        assert mock_patch_obj.status["readyReplicas"] == 0

    @pytest.mark.asyncio
    async def test_reconcile_sets_conditions(
        self,
        sample_mcpserver_spec: dict[str, Any],
        mock_logger: MagicMock,
        sample_body: dict[str, Any],
    ) -> None:
        """Test that reconciliation sets conditions."""
        mock_k8s = MagicMock()
        mock_k8s.list_by_label_selector.side_effect = [[], [], []]
        mock_k8s.get_deployment.return_value = {"status": {"readyReplicas": 2}}
        mock_patch_obj = MagicMock()
        mock_patch_obj.status = {}

        with patch("src.controllers.mcpserver_controller.get_k8s_client", return_value=mock_k8s):
            await reconcile_mcpserver(
                spec=sample_mcpserver_spec,
                name="test-server",
                namespace="default",
                logger=mock_logger,
                patch=mock_patch_obj,
                body=sample_body,
            )

        assert len(mock_patch_obj.status["conditions"]) > 0
        ready_condition = next(
            (c for c in mock_patch_obj.status["conditions"] if c["type"] == "Ready"), None
        )
        assert ready_condition is not None

    @pytest.mark.asyncio
    async def test_reconcile_ready_when_deployment_ready(
        self,
        sample_mcpserver_spec: dict[str, Any],
        mock_logger: MagicMock,
        sample_body: dict[str, Any],
    ) -> None:
        """Test that Ready condition is True when deployment is ready."""
        mock_k8s = MagicMock()
        mock_k8s.list_by_label_selector.side_effect = [[], [], []]
        mock_k8s.get_deployment.return_value = {"status": {"readyReplicas": 2}}
        mock_patch_obj = MagicMock()
        mock_patch_obj.status = {}

        with patch("src.controllers.mcpserver_controller.get_k8s_client", return_value=mock_k8s):
            await reconcile_mcpserver(
                spec=sample_mcpserver_spec,
                name="test-server",
                namespace="default",
                logger=mock_logger,
                patch=mock_patch_obj,
                body=sample_body,
            )

        ready_condition = next(
            (c for c in mock_patch_obj.status["conditions"] if c["type"] == "Ready"), None
        )
        assert ready_condition["status"] == "True"
        assert ready_condition["reason"] == "DeploymentReady"

    @pytest.mark.asyncio
    async def test_reconcile_not_ready_when_deployment_not_ready(
        self,
        sample_mcpserver_spec: dict[str, Any],
        mock_logger: MagicMock,
        sample_body: dict[str, Any],
    ) -> None:
        """Test that Ready condition is False when deployment not ready."""
        mock_k8s = MagicMock()
        mock_k8s.list_by_label_selector.side_effect = [[], [], []]
        mock_k8s.get_deployment.return_value = {"status": {"readyReplicas": 0}}
        mock_patch_obj = MagicMock()
        mock_patch_obj.status = {}

        with patch("src.controllers.mcpserver_controller.get_k8s_client", return_value=mock_k8s):
            await reconcile_mcpserver(
                spec=sample_mcpserver_spec,
                name="test-server",
                namespace="default",
                logger=mock_logger,
                patch=mock_patch_obj,
                body=sample_body,
            )

        ready_condition = next(
            (c for c in mock_patch_obj.status["conditions"] if c["type"] == "Ready"), None
        )
        assert ready_condition["status"] == "False"
        assert ready_condition["reason"] == "DeploymentNotReady"

    @pytest.mark.asyncio
    async def test_reconcile_logs_info(
        self,
        sample_mcpserver_spec: dict[str, Any],
        mock_logger: MagicMock,
        sample_body: dict[str, Any],
    ) -> None:
        """Test that reconciliation logs appropriate info."""
        mock_k8s = MagicMock()
        mock_k8s.list_by_label_selector.side_effect = [[], [], []]
        mock_k8s.get_deployment.return_value = None
        mock_patch_obj = MagicMock()
        mock_patch_obj.status = {}

        with patch("src.controllers.mcpserver_controller.get_k8s_client", return_value=mock_k8s):
            await reconcile_mcpserver(
                spec=sample_mcpserver_spec,
                name="test-server",
                namespace="default",
                logger=mock_logger,
                patch=mock_patch_obj,
                body=sample_body,
            )

        mock_logger.info.assert_called()

    @pytest.mark.asyncio
    async def test_reconcile_uses_tool_selector_for_all_resources(
        self,
        sample_mcpserver_spec: dict[str, Any],
        mock_logger: MagicMock,
        sample_body: dict[str, Any],
    ) -> None:
        """Test that tool selector is used to find tools, prompts, and resources."""
        mock_k8s = MagicMock()
        mock_k8s.list_by_label_selector.side_effect = [[], [], []]
        mock_k8s.get_deployment.return_value = None
        mock_patch_obj = MagicMock()
        mock_patch_obj.status = {}

        with patch("src.controllers.mcpserver_controller.get_k8s_client", return_value=mock_k8s):
            await reconcile_mcpserver(
                spec=sample_mcpserver_spec,
                name="test-server",
                namespace="default",
                logger=mock_logger,
                patch=mock_patch_obj,
                body=sample_body,
            )

        # Should be called 3 times: once for tools, prompts, resources
        assert mock_k8s.list_by_label_selector.call_count == 3

        # Verify selector is passed correctly
        calls = mock_k8s.list_by_label_selector.call_args_list
        expected_selector = {"matchLabels": {"mcp-server": "main"}}

        for call in calls:
            assert (
                call.kwargs.get("label_selector") == expected_selector
                or call[1].get("label_selector") == expected_selector
            )

    @pytest.mark.asyncio
    async def test_reconcile_handles_empty_selector_result(
        self,
        sample_mcpserver_spec: dict[str, Any],
        mock_logger: MagicMock,
        sample_body: dict[str, Any],
    ) -> None:
        """Test that reconciliation handles empty tool/prompt/resource lists."""
        mock_k8s = MagicMock()
        mock_k8s.list_by_label_selector.side_effect = [[], [], []]
        mock_k8s.get_deployment.return_value = {"status": {"readyReplicas": 1}}
        mock_patch_obj = MagicMock()
        mock_patch_obj.status = {}

        with patch("src.controllers.mcpserver_controller.get_k8s_client", return_value=mock_k8s):
            await reconcile_mcpserver(
                spec=sample_mcpserver_spec,
                name="test-server",
                namespace="default",
                logger=mock_logger,
                patch=mock_patch_obj,
                body=sample_body,
            )

        assert mock_patch_obj.status["toolCount"] == 0
        assert mock_patch_obj.status["promptCount"] == 0
        assert mock_patch_obj.status["resourceCount"] == 0

    @pytest.mark.asyncio
    async def test_reconcile_creates_deployment(
        self,
        sample_mcpserver_spec: dict[str, Any],
        mock_logger: MagicMock,
        mock_adopt: MagicMock,
        sample_body: dict[str, Any],
    ) -> None:
        """Test that reconciliation creates a deployment."""
        mock_k8s = MagicMock()
        mock_k8s.list_by_label_selector.side_effect = [[], [], []]
        mock_k8s.get_deployment.return_value = {"status": {"readyReplicas": 1}}
        mock_patch_obj = MagicMock()
        mock_patch_obj.status = {}

        with patch("src.controllers.mcpserver_controller.get_k8s_client", return_value=mock_k8s):
            await reconcile_mcpserver(
                spec=sample_mcpserver_spec,
                name="test-server",
                namespace="default",
                logger=mock_logger,
                patch=mock_patch_obj,
                body=sample_body,
            )

        mock_k8s.create_or_update_deployment.assert_called_once()
        call_args = mock_k8s.create_or_update_deployment.call_args
        assert call_args[0][0] == "mcp-server-test-server"
        assert call_args[0][1] == "default"

        deployment_body = call_args[0][2]
        assert deployment_body["metadata"]["name"] == "mcp-server-test-server"
        assert deployment_body["spec"]["replicas"] == 2
        assert (
            deployment_body["spec"]["template"]["spec"]["containers"][0]["image"]
            == "ghcr.io/atippey/mcp-echo-server:latest"
        )
        assert (
            deployment_body["spec"]["template"]["spec"]["containers"][0]["env"][0]["value"]
            == "mcp-redis"
        )

        # Verify ConfigMap volume mount
        volumes = deployment_body["spec"]["template"]["spec"]["volumes"]
        assert len(volumes) == 1
        assert volumes[0]["name"] == "config"
        assert volumes[0]["configMap"]["name"] == "mcp-server-test-server-config"

        volume_mounts = deployment_body["spec"]["template"]["spec"]["containers"][0]["volumeMounts"]
        assert len(volume_mounts) == 1
        assert volume_mounts[0]["name"] == "config"
        assert volume_mounts[0]["mountPath"] == "/etc/mcp/config"

        mock_adopt.assert_called_once_with(deployment_body)

    @pytest.mark.asyncio
    async def test_reconcile_creates_deployment_with_custom_image(
        self,
        sample_mcpserver_spec: dict[str, Any],
        mock_logger: MagicMock,
        mock_adopt: MagicMock,
        sample_body: dict[str, Any],
    ) -> None:
        """Test that reconciliation creates a deployment with custom image."""
        mock_k8s = MagicMock()
        mock_k8s.list_by_label_selector.side_effect = [[], [], []]
        mock_k8s.get_deployment.return_value = {"status": {"readyReplicas": 1}}
        mock_patch_obj = MagicMock()
        mock_patch_obj.status = {}

        # Set custom image
        sample_mcpserver_spec["image"] = "custom/image:tag"

        with patch("src.controllers.mcpserver_controller.get_k8s_client", return_value=mock_k8s):
            await reconcile_mcpserver(
                spec=sample_mcpserver_spec,
                name="test-server",
                namespace="default",
                logger=mock_logger,
                patch=mock_patch_obj,
                body=sample_body,
            )

        mock_k8s.create_or_update_deployment.assert_called_once()
        call_args = mock_k8s.create_or_update_deployment.call_args
        deployment_body = call_args[0][2]

        assert (
            deployment_body["spec"]["template"]["spec"]["containers"][0]["image"]
            == "custom/image:tag"
        )

    @pytest.mark.asyncio
    async def test_reconcile_creates_service(
        self,
        sample_mcpserver_spec: dict[str, Any],
        mock_logger: MagicMock,
        sample_body: dict[str, Any],
    ) -> None:
        """Test that reconciliation creates a Service."""
        mock_k8s = MagicMock()
        mock_k8s.list_by_label_selector.side_effect = [[], [], []]
        mock_k8s.get_deployment.return_value = {"status": {"readyReplicas": 1}}
        mock_patch_obj = MagicMock()
        mock_patch_obj.status = {}

        with patch("src.controllers.mcpserver_controller.get_k8s_client", return_value=mock_k8s):
            await reconcile_mcpserver(
                spec=sample_mcpserver_spec,
                name="test-server",
                namespace="default",
                logger=mock_logger,
                patch=mock_patch_obj,
                body=sample_body,
            )

        mock_k8s.create_or_update_service.assert_called_once()
        call_kwargs = mock_k8s.create_or_update_service.call_args.kwargs
        assert call_kwargs["name"] == "mcp-server-test-server"
        assert call_kwargs["namespace"] == "default"
        assert call_kwargs["selector"] == {
            "app.kubernetes.io/name": "mcp-server",
            "app.kubernetes.io/instance": "test-server",
        }
        assert call_kwargs["ports"][0]["port"] == 8080
        assert call_kwargs["owner_reference"]["name"] == "test-server"
        assert call_kwargs["owner_reference"]["uid"] == "test-uid-123"

    @pytest.mark.asyncio
    async def test_reconcile_creates_configmap(
        self,
        sample_mcpserver_spec: dict[str, Any],
        mock_logger: MagicMock,
        mock_tools: list[dict[str, Any]],
        mock_prompts: list[dict[str, Any]],
        mock_resources: list[dict[str, Any]],
        sample_body: dict[str, Any],
    ) -> None:
        """Test that ConfigMap is created with correct data."""
        mock_k8s = MagicMock()
        mock_k8s.list_by_label_selector.side_effect = [mock_tools, mock_prompts, mock_resources]
        mock_k8s.get_deployment.return_value = {"status": {"readyReplicas": 1}}
        mock_k8s.get_service_endpoint.side_effect = (
            lambda name, ns, port: f"http://{name}.{ns}.svc.cluster.local:{port}"
        )

        mock_patch_obj = MagicMock()
        mock_patch_obj.status = {}

        with patch("src.controllers.mcpserver_controller.get_k8s_client", return_value=mock_k8s):
            await reconcile_mcpserver(
                spec=sample_mcpserver_spec,
                name="test-server",
                namespace="default",
                logger=mock_logger,
                patch=mock_patch_obj,
                body=sample_body,
            )

        # Verify ConfigMap creation
        mock_k8s.create_or_update_configmap.assert_called_once()
        call_args = mock_k8s.create_or_update_configmap.call_args[1]

        assert call_args["name"] == "mcp-server-test-server-config"
        assert call_args["namespace"] == "default"

        # Verify JSON content
        data = call_args["data"]
        tools_json = json.loads(data["tools.json"])
        prompts_json = json.loads(data["prompts.json"])
        resources_json = json.loads(data["resources.json"])

        assert len(tools_json) == 2
        assert tools_json[0]["name"] == "tool1"
        assert tools_json[0]["endpoint"] == "http://svc1.default.svc.cluster.local:8080/"

        assert len(prompts_json) == 1
        assert prompts_json[0]["name"] == "prompt1"
        assert prompts_json[0]["template"] == "Hello {{name}}"

        assert len(resources_json) == 1
        assert resources_json[0]["name"] == "resource1"
        assert resources_json[0]["content"]["text"] == "data"

        # Verify owner reference
        owner_ref = call_args["owner_reference"]
        assert owner_ref["name"] == "test-server"
        assert owner_ref["uid"] == "test-uid-123"

    @pytest.mark.asyncio
    async def test_reconcile_creates_ingress(
        self,
        sample_mcpserver_spec: dict[str, Any],
        mock_logger: MagicMock,
        sample_body: dict[str, Any],
    ) -> None:
        """Test that Ingress is created when configured."""
        mock_k8s = MagicMock()
        mock_k8s.list_by_label_selector.side_effect = [[], [], []]
        mock_k8s.get_deployment.return_value = {"status": {"readyReplicas": 1}}
        mock_patch_obj = MagicMock()
        mock_patch_obj.status = {}

        # Add ingress config
        sample_mcpserver_spec["ingress"] = {
            "host": "test.example.com",
            "pathPrefix": "/api",
            "tlsSecretName": "tls-secret",
        }

        with patch("src.controllers.mcpserver_controller.get_k8s_client", return_value=mock_k8s):
            await reconcile_mcpserver(
                spec=sample_mcpserver_spec,
                name="test-server",
                namespace="default",
                logger=mock_logger,
                patch=mock_patch_obj,
                body=sample_body,
            )

        mock_k8s.create_or_update_ingress.assert_called_once()
        call_args = mock_k8s.create_or_update_ingress.call_args.kwargs
        assert call_args["name"] == "mcp-server-test-server"
        assert call_args["host"] == "test.example.com"
        assert call_args["path"] == "/api"
        assert call_args["tls_secret_name"] == "tls-secret"
        assert call_args["service_name"] == "mcp-server-test-server"
        assert call_args["service_port"] == 8080
        assert call_args["owner_reference"]["uid"] == "test-uid-123"

    @pytest.mark.asyncio
    async def test_reconcile_skips_ingress(
        self,
        sample_mcpserver_spec: dict[str, Any],
        mock_logger: MagicMock,
        sample_body: dict[str, Any],
    ) -> None:
        """Test that Ingress is not created when not configured."""
        mock_k8s = MagicMock()
        mock_k8s.list_by_label_selector.side_effect = [[], [], []]
        mock_k8s.get_deployment.return_value = {"status": {"readyReplicas": 1}}
        mock_patch_obj = MagicMock()
        mock_patch_obj.status = {}

        # Ensure ingress is missing
        if "ingress" in sample_mcpserver_spec:
            del sample_mcpserver_spec["ingress"]

        with patch("src.controllers.mcpserver_controller.get_k8s_client", return_value=mock_k8s):
            await reconcile_mcpserver(
                spec=sample_mcpserver_spec,
                name="test-server",
                namespace="default",
                logger=mock_logger,
                patch=mock_patch_obj,
                body=sample_body,
            )

        mock_k8s.create_or_update_ingress.assert_not_called()
