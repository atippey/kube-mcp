"""Unit tests for MCPServer controller."""

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.controllers.mcpserver_controller import reconcile_mcpserver
from src.models.crds import EnvVar, MCPServerSpec


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

    def test_command_args_env_optional(self) -> None:
        """Test that command, args, and env default to None."""
        spec = MCPServerSpec(
            redis={"serviceName": "redis"},
            toolSelector={"matchLabels": {"app": "test"}},
        )
        assert spec.command is None
        assert spec.args is None
        assert spec.env is None

    def test_command_args_env_accepted(self) -> None:
        """Test that command, args, and env are parsed correctly."""
        spec = MCPServerSpec(
            redis={"serviceName": "redis"},
            toolSelector={"matchLabels": {"app": "test"}},
            command=["/bin/sh", "-c"],
            args=["--transport", "sse", "--port", "8080"],
            env=[{"name": "LOG_LEVEL", "value": "DEBUG"}],
        )
        assert spec.command == ["/bin/sh", "-c"]
        assert spec.args == ["--transport", "sse", "--port", "8080"]
        assert len(spec.env) == 1
        assert spec.env[0].name == "LOG_LEVEL"
        assert spec.env[0].value == "DEBUG"

    def test_env_var_name_required(self) -> None:
        """Test that env var name is required."""
        with pytest.raises(ValueError):
            EnvVar(name="", value="val")

    def test_env_var_requires_value_or_value_from(self) -> None:
        """Test that env vars require a value source."""
        with pytest.raises(ValueError):
            EnvVar(name="FOO")

    def test_env_var_rejects_both_value_and_value_from(self) -> None:
        """Test that env vars cannot set both value and valueFrom."""
        with pytest.raises(ValueError):
            EnvVar(
                name="FOO",
                value="bar",
                valueFrom={"secretKeyRef": {"name": "my-secret", "key": "foo"}},
            )

    def test_env_var_accepts_value_from(self) -> None:
        """Test that env vars support Kubernetes valueFrom sources."""
        var = EnvVar(
            name="TOKEN",
            valueFrom={"secretKeyRef": {"name": "my-secret", "key": "token"}},
        )
        assert var.value is None
        assert var.valueFrom == {"secretKeyRef": {"name": "my-secret", "key": "token"}}

    def test_env_serialization_via_model_dump(self) -> None:
        """Test that env vars serialize consistently via Pydantic model_dump."""
        spec = MCPServerSpec(
            redis={"serviceName": "redis"},
            toolSelector={"matchLabels": {"app": "test"}},
            env=[
                {"name": "A", "value": "1"},
                {"name": "B", "valueFrom": {"configMapKeyRef": {"name": "cm", "key": "b"}}},
            ],
        )
        dumped = [e.model_dump(exclude_none=True) for e in spec.env]
        assert dumped == [
            {"name": "A", "value": "1"},
            {"name": "B", "valueFrom": {"configMapKeyRef": {"name": "cm", "key": "b"}}},
        ]


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
        """Test that reconciliation sets all three condition types."""
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

        conditions = mock_patch_obj.status["conditions"]
        assert len(conditions) == 3
        condition_types = {c["type"] for c in conditions}
        assert condition_types == {"ToolsDiscovered", "ConfigReady", "Ready"}

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
    async def test_reconcile_tools_discovered_true_with_tools(
        self,
        sample_mcpserver_spec: dict[str, Any],
        mock_logger: MagicMock,
        sample_body: dict[str, Any],
    ) -> None:
        """Test ToolsDiscovered is True when tools are found."""
        mock_k8s = MagicMock()
        tool_cr = {
            "spec": {
                "name": "my-tool",
                "service": {"name": "svc", "port": 8080, "path": "/"},
                "inputSchema": {"type": "object"},
            }
        }
        mock_k8s.list_by_label_selector.side_effect = [[tool_cr], [], []]
        mock_k8s.get_service.return_value = {
            "spec": {"selector": {"app": "backend"}, "ports": [{"port": 8080}]}
        }
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

        condition = next(
            c for c in mock_patch_obj.status["conditions"] if c["type"] == "ToolsDiscovered"
        )
        assert condition["status"] == "True"
        assert condition["reason"] == "ResourcesFound"
        assert "1 tool(s)" in condition["message"]

    @pytest.mark.asyncio
    async def test_reconcile_tools_discovered_false_with_no_resources(
        self,
        sample_mcpserver_spec: dict[str, Any],
        mock_logger: MagicMock,
        sample_body: dict[str, Any],
    ) -> None:
        """Test ToolsDiscovered is False when no tools/prompts/resources found."""
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

        condition = next(
            c for c in mock_patch_obj.status["conditions"] if c["type"] == "ToolsDiscovered"
        )
        assert condition["status"] == "False"
        assert condition["reason"] == "NoResourcesFound"
        assert "No tools, prompts, or resources found" in condition["message"]

    @pytest.mark.asyncio
    async def test_reconcile_config_ready_condition(
        self,
        sample_mcpserver_spec: dict[str, Any],
        mock_logger: MagicMock,
        sample_body: dict[str, Any],
    ) -> None:
        """Test ConfigReady condition is set after ConfigMap creation."""
        mock_k8s = MagicMock()
        tool_cr = {
            "spec": {
                "name": "my-tool",
                "service": {"name": "svc", "port": 8080, "path": "/"},
                "inputSchema": {"type": "object"},
            }
        }
        prompt_cr = {"spec": {"name": "my-prompt", "template": "Hello {{name}}", "variables": []}}
        mock_k8s.list_by_label_selector.side_effect = [[tool_cr], [prompt_cr], []]
        mock_k8s.get_service.return_value = {
            "spec": {"selector": {"app": "backend"}, "ports": [{"port": 8080}]}
        }
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

        condition = next(
            c for c in mock_patch_obj.status["conditions"] if c["type"] == "ConfigReady"
        )
        assert condition["status"] == "True"
        assert condition["reason"] == "ConfigMapCreated"
        assert "1 tool(s)" in condition["message"]
        assert "1 prompt(s)" in condition["message"]

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
    async def test_reconcile_creates_deployment_with_args(
        self,
        sample_mcpserver_spec: dict[str, Any],
        mock_logger: MagicMock,
        mock_adopt: MagicMock,
        sample_body: dict[str, Any],
    ) -> None:
        """Test that args are passed through to the deployment container."""
        mock_k8s = MagicMock()
        mock_k8s.list_by_label_selector.side_effect = [[], [], []]
        mock_k8s.get_deployment.return_value = {"status": {"readyReplicas": 1}}
        mock_patch_obj = MagicMock()
        mock_patch_obj.status = {}

        sample_mcpserver_spec["args"] = ["--transport", "sse", "--port", "8080"]

        with patch("src.controllers.mcpserver_controller.get_k8s_client", return_value=mock_k8s):
            await reconcile_mcpserver(
                spec=sample_mcpserver_spec,
                name="test-server",
                namespace="default",
                logger=mock_logger,
                patch=mock_patch_obj,
                body=sample_body,
            )

        deployment_body = mock_k8s.create_or_update_deployment.call_args[0][2]
        container = deployment_body["spec"]["template"]["spec"]["containers"][0]
        assert container["args"] == ["--transport", "sse", "--port", "8080"]
        assert "command" not in container

    @pytest.mark.asyncio
    async def test_reconcile_creates_deployment_with_command(
        self,
        sample_mcpserver_spec: dict[str, Any],
        mock_logger: MagicMock,
        mock_adopt: MagicMock,
        sample_body: dict[str, Any],
    ) -> None:
        """Test that command is passed through to the deployment container."""
        mock_k8s = MagicMock()
        mock_k8s.list_by_label_selector.side_effect = [[], [], []]
        mock_k8s.get_deployment.return_value = {"status": {"readyReplicas": 1}}
        mock_patch_obj = MagicMock()
        mock_patch_obj.status = {}

        sample_mcpserver_spec["command"] = ["/bin/sh", "-c"]
        sample_mcpserver_spec["args"] = ["echo hello"]

        with patch("src.controllers.mcpserver_controller.get_k8s_client", return_value=mock_k8s):
            await reconcile_mcpserver(
                spec=sample_mcpserver_spec,
                name="test-server",
                namespace="default",
                logger=mock_logger,
                patch=mock_patch_obj,
                body=sample_body,
            )

        deployment_body = mock_k8s.create_or_update_deployment.call_args[0][2]
        container = deployment_body["spec"]["template"]["spec"]["containers"][0]
        assert container["command"] == ["/bin/sh", "-c"]
        assert container["args"] == ["echo hello"]

    @pytest.mark.asyncio
    async def test_reconcile_creates_deployment_with_env(
        self,
        sample_mcpserver_spec: dict[str, Any],
        mock_logger: MagicMock,
        mock_adopt: MagicMock,
        sample_body: dict[str, Any],
    ) -> None:
        """Test that user env vars are appended after operator defaults."""
        mock_k8s = MagicMock()
        mock_k8s.list_by_label_selector.side_effect = [[], [], []]
        mock_k8s.get_deployment.return_value = {"status": {"readyReplicas": 1}}
        mock_patch_obj = MagicMock()
        mock_patch_obj.status = {}

        sample_mcpserver_spec["env"] = [
            {"name": "FASTMCP_LOG_LEVEL", "value": "ERROR"},
            {"name": "CUSTOM_VAR", "value": "custom"},
        ]

        with patch("src.controllers.mcpserver_controller.get_k8s_client", return_value=mock_k8s):
            await reconcile_mcpserver(
                spec=sample_mcpserver_spec,
                name="test-server",
                namespace="default",
                logger=mock_logger,
                patch=mock_patch_obj,
                body=sample_body,
            )

        deployment_body = mock_k8s.create_or_update_deployment.call_args[0][2]
        container = deployment_body["spec"]["template"]["spec"]["containers"][0]
        env = container["env"]
        # Operator defaults first, then user env
        assert env[0] == {"name": "REDIS_HOST", "value": "mcp-redis"}
        assert env[1] == {"name": "MCP_CONFIG_DIR", "value": "/etc/mcp/config"}
        assert env[2] == {"name": "FASTMCP_LOG_LEVEL", "value": "ERROR"}
        assert env[3] == {"name": "CUSTOM_VAR", "value": "custom"}

    @pytest.mark.asyncio
    async def test_reconcile_creates_deployment_with_env_value_from(
        self,
        sample_mcpserver_spec: dict[str, Any],
        mock_logger: MagicMock,
        mock_adopt: MagicMock,
        sample_body: dict[str, Any],
    ) -> None:
        """Test that valueFrom env vars are preserved in deployment spec."""
        mock_k8s = MagicMock()
        mock_k8s.list_by_label_selector.side_effect = [[], [], []]
        mock_k8s.get_deployment.return_value = {"status": {"readyReplicas": 1}}
        mock_patch_obj = MagicMock()
        mock_patch_obj.status = {}

        sample_mcpserver_spec["env"] = [
            {
                "name": "API_TOKEN",
                "valueFrom": {"secretKeyRef": {"name": "aws-diagram-secret", "key": "api-token"}},
            }
        ]

        with patch("src.controllers.mcpserver_controller.get_k8s_client", return_value=mock_k8s):
            await reconcile_mcpserver(
                spec=sample_mcpserver_spec,
                name="test-server",
                namespace="default",
                logger=mock_logger,
                patch=mock_patch_obj,
                body=sample_body,
            )

        deployment_body = mock_k8s.create_or_update_deployment.call_args[0][2]
        env = deployment_body["spec"]["template"]["spec"]["containers"][0]["env"]
        assert env[2] == {
            "name": "API_TOKEN",
            "valueFrom": {"secretKeyRef": {"name": "aws-diagram-secret", "key": "api-token"}},
        }

    @pytest.mark.asyncio
    async def test_reconcile_creates_deployment_without_optional_fields(
        self,
        sample_mcpserver_spec: dict[str, Any],
        mock_logger: MagicMock,
        mock_adopt: MagicMock,
        sample_body: dict[str, Any],
    ) -> None:
        """Test that command/args are omitted from deployment when not specified."""
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

        deployment_body = mock_k8s.create_or_update_deployment.call_args[0][2]
        container = deployment_body["spec"]["template"]["spec"]["containers"][0]
        assert "command" not in container
        assert "args" not in container
        # Only operator default env vars
        assert len(container["env"]) == 2

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
        mock_k8s.get_service_endpoint.side_effect = lambda name, ns, port: (
            f"http://{name}.{ns}.svc.cluster.local:{port}"
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


class TestMCPServerMultiToolExpansion:
    """Tests for multi-tool MCPTool expansion in MCPServer reconciliation."""

    @pytest.fixture
    def mock_logger(self) -> MagicMock:
        """Create a mock logger."""
        return MagicMock()

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
                "uid": "test-uid-456",
            }
        }

    @pytest.mark.asyncio
    async def test_reconcile_expands_multi_tool_mcptool(
        self,
        sample_mcpserver_spec: dict[str, Any],
        mock_logger: MagicMock,
        sample_body: dict[str, Any],
    ) -> None:
        """Test that a multi-tool MCPTool CR is expanded to multiple tools.json entries."""
        multi_tool_cr = {
            "metadata": {"name": "crane-tools", "namespace": "default"},
            "spec": {
                "service": {"name": "crane-svc", "port": 8080},
                "tools": [
                    {"name": "crane-images", "path": "/images", "inputSchema": {"type": "object"}},
                    {"name": "crane-inspect", "path": "/inspect"},
                ],
            },
        }

        mock_k8s = MagicMock()
        mock_k8s.list_by_label_selector.side_effect = [
            [multi_tool_cr],
            [],
            [],
        ]
        mock_k8s.get_service_endpoint.side_effect = lambda name, ns, port: (
            f"http://{name}.{ns}.svc.cluster.local:{port}"
        )
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

        # Verify ConfigMap has 2 tool entries from 1 MCPTool CR
        call_args = mock_k8s.create_or_update_configmap.call_args[1]
        tools_json = json.loads(call_args["data"]["tools.json"])
        assert len(tools_json) == 2
        assert tools_json[0]["name"] == "crane-images"
        assert "/images" in tools_json[0]["endpoint"]
        assert tools_json[1]["name"] == "crane-inspect"
        assert "/inspect" in tools_json[1]["endpoint"]
        assert mock_patch_obj.status["toolCount"] == 2

    @pytest.mark.asyncio
    async def test_reconcile_mixes_single_and_multi_tool(
        self,
        sample_mcpserver_spec: dict[str, Any],
        mock_logger: MagicMock,
        sample_body: dict[str, Any],
    ) -> None:
        """Test that single-tool and multi-tool MCPTool CRs are merged correctly."""
        single_tool_cr = {
            "metadata": {"name": "hash-tool", "namespace": "default"},
            "spec": {
                "name": "hash-tool",
                "service": {"name": "hash-svc", "port": 8080, "path": "/hash"},
            },
        }
        multi_tool_cr = {
            "metadata": {"name": "crane-tools", "namespace": "default"},
            "spec": {
                "service": {"name": "crane-svc", "port": 8080},
                "tools": [
                    {"name": "crane-images", "path": "/images"},
                    {"name": "crane-inspect", "path": "/inspect"},
                ],
            },
        }

        mock_k8s = MagicMock()
        mock_k8s.list_by_label_selector.side_effect = [
            [single_tool_cr, multi_tool_cr],
            [],
            [],
        ]
        mock_k8s.get_service_endpoint.side_effect = lambda name, ns, port: (
            f"http://{name}.{ns}.svc.cluster.local:{port}"
        )
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

        call_args = mock_k8s.create_or_update_configmap.call_args[1]
        tools_json = json.loads(call_args["data"]["tools.json"])
        assert len(tools_json) == 3
        tool_names = [t["name"] for t in tools_json]
        assert "hash-tool" in tool_names
        assert "crane-images" in tool_names
        assert "crane-inspect" in tool_names
        assert mock_patch_obj.status["toolCount"] == 3

    @pytest.mark.asyncio
    async def test_reconcile_tool_count_reflects_expanded_tools(
        self,
        sample_mcpserver_spec: dict[str, Any],
        mock_logger: MagicMock,
        sample_body: dict[str, Any],
    ) -> None:
        """Test that toolCount reflects expanded tool entries, not MCPTool CR count."""
        multi_tool_cr = {
            "metadata": {"name": "multi", "namespace": "default"},
            "spec": {
                "service": {"name": "svc", "port": 8080},
                "tools": [
                    {"name": "tool-a", "path": "/a"},
                    {"name": "tool-b", "path": "/b"},
                    {"name": "tool-c", "path": "/c"},
                ],
            },
        }

        mock_k8s = MagicMock()
        mock_k8s.list_by_label_selector.side_effect = [[multi_tool_cr], [], []]
        mock_k8s.get_service_endpoint.return_value = "http://svc.default.svc.cluster.local:8080"
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

        # 1 MCPTool CR with 3 tools = toolCount should be 3
        assert mock_patch_obj.status["toolCount"] == 3


class TestMCPServerNetworkPolicyGeneration:
    """Tests for controller-managed egress NetworkPolicy generation."""

    @pytest.fixture
    def mock_logger(self) -> MagicMock:
        """Create a mock logger."""
        return MagicMock()

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
                "uid": "test-uid-789",
            }
        }

    def _make_tool_cr(
        self,
        name: str,
        svc_name: str,
        svc_port: int = 8080,
        svc_namespace: str | None = None,
        annotations: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Helper to create a tool CR dict."""
        service: dict[str, Any] = {"name": svc_name, "port": svc_port}
        if svc_namespace:
            service["namespace"] = svc_namespace
        return {
            "metadata": {"name": name, "namespace": "default", "annotations": annotations or {}},
            "spec": {"name": name, "service": service},
        }

    def _make_resource_cr(
        self,
        name: str,
        svc_name: str,
        svc_port: int = 8080,
        svc_namespace: str | None = None,
        annotations: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Helper to create a resource CR with one service-backed operation."""
        service: dict[str, Any] = {"name": svc_name, "port": svc_port, "path": "/resource"}
        if svc_namespace:
            service["namespace"] = svc_namespace
        return {
            "metadata": {"name": name, "namespace": "default", "annotations": annotations or {}},
            "spec": {
                "name": name,
                "operations": [{"method": "GET", "ingressPath": "/r/{id}", "service": service}],
            },
        }

    def _make_service_dict(
        self,
        selector: dict[str, str] | None,
        svc_type: str = "ClusterIP",
    ) -> dict[str, Any]:
        """Helper to create a service dict returned by get_service."""
        return {"spec": {"selector": selector, "type": svc_type}}

    @pytest.mark.asyncio
    async def test_reconcile_creates_networkpolicy_with_tool_services(
        self,
        sample_mcpserver_spec: dict[str, Any],
        mock_logger: MagicMock,
        sample_body: dict[str, Any],
    ) -> None:
        """Test that NetworkPolicy is created with egress rules for tool services."""
        tool1 = self._make_tool_cr("tool1", "svc1")
        tool2 = self._make_tool_cr("tool2", "svc2")

        mock_k8s = MagicMock()
        mock_k8s.list_by_label_selector.side_effect = [[tool1, tool2], [], []]
        mock_k8s.get_service_endpoint.side_effect = lambda name, ns, port: (
            f"http://{name}.{ns}.svc.cluster.local:{port}"
        )
        mock_k8s.get_service.side_effect = lambda name, ns: self._make_service_dict({"app": name})
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

        assert mock_k8s.create_or_update_networkpolicy.call_count == 2
        server_calls = [
            call
            for call in mock_k8s.create_or_update_networkpolicy.call_args_list
            if call.kwargs.get("name") == "mcp-server-test-server-egress"
        ]
        assert len(server_calls) == 1
        call_args = server_calls[0]

        netpol_body = call_args.kwargs["body"]
        egress = netpol_body["spec"]["egress"]
        # Redis + DNS + 2 tool services = 4 rules
        assert len(egress) == 4

    @pytest.mark.asyncio
    async def test_reconcile_networkpolicy_deduplicates_services(
        self,
        sample_mcpserver_spec: dict[str, Any],
        mock_logger: MagicMock,
        sample_body: dict[str, Any],
    ) -> None:
        """Test that duplicate service references produce only one egress rule."""
        # Two tools pointing at the same service
        tool1 = self._make_tool_cr("tool1", "shared-svc")
        tool2 = self._make_tool_cr("tool2", "shared-svc")

        mock_k8s = MagicMock()
        mock_k8s.list_by_label_selector.side_effect = [[tool1, tool2], [], []]
        mock_k8s.get_service_endpoint.side_effect = lambda name, ns, port: (
            f"http://{name}.{ns}.svc.cluster.local:{port}"
        )
        mock_k8s.get_service.side_effect = lambda name, ns: self._make_service_dict({"app": name})
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

        call_args = mock_k8s.create_or_update_networkpolicy.call_args
        netpol_body = call_args.kwargs["body"]
        egress = netpol_body["spec"]["egress"]
        # Redis + DNS + 1 deduplicated service = 3 rules
        assert len(egress) == 3

    @pytest.mark.asyncio
    async def test_reconcile_networkpolicy_uses_service_pod_selector(
        self,
        sample_mcpserver_spec: dict[str, Any],
        mock_logger: MagicMock,
        sample_body: dict[str, Any],
    ) -> None:
        """Test that egress rules use the Service's spec.selector as podSelector."""
        tool1 = self._make_tool_cr("tool1", "my-svc")

        mock_k8s = MagicMock()
        mock_k8s.list_by_label_selector.side_effect = [[tool1], [], []]
        mock_k8s.get_service_endpoint.side_effect = lambda name, ns, port: (
            f"http://{name}.{ns}.svc.cluster.local:{port}"
        )
        mock_k8s.get_service.return_value = self._make_service_dict(
            {"app.kubernetes.io/name": "my-tool", "version": "v1"}
        )
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

        call_args = mock_k8s.create_or_update_networkpolicy.call_args
        netpol_body = call_args.kwargs["body"]
        # The service rule is the 3rd egress rule (after Redis and DNS)
        svc_rule = netpol_body["spec"]["egress"][2]
        pod_selector = svc_rule["to"][0]["podSelector"]["matchLabels"]
        assert pod_selector == {"app.kubernetes.io/name": "my-tool", "version": "v1"}

    @pytest.mark.asyncio
    async def test_reconcile_networkpolicy_has_owner_reference(
        self,
        sample_mcpserver_spec: dict[str, Any],
        mock_logger: MagicMock,
        sample_body: dict[str, Any],
    ) -> None:
        """Test that the generated NetworkPolicy has an owner reference."""
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

        call_args = mock_k8s.create_or_update_networkpolicy.call_args
        owner_ref = call_args.kwargs["owner_reference"]
        assert owner_ref["name"] == "test-server"
        assert owner_ref["uid"] == "test-uid-789"
        assert owner_ref["controller"] is True

    @pytest.mark.asyncio
    async def test_reconcile_networkpolicy_with_cross_namespace_service(
        self,
        sample_mcpserver_spec: dict[str, Any],
        mock_logger: MagicMock,
        sample_body: dict[str, Any],
    ) -> None:
        """Test that cross-namespace service produces correct namespaceSelector."""
        tool1 = self._make_tool_cr("tool1", "remote-svc", svc_namespace="other-ns")

        mock_k8s = MagicMock()
        mock_k8s.list_by_label_selector.side_effect = [[tool1], [], []]
        mock_k8s.get_service_endpoint.side_effect = lambda name, ns, port: (
            f"http://{name}.{ns}.svc.cluster.local:{port}"
        )
        mock_k8s.get_service.return_value = self._make_service_dict({"app": "remote"})
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

        call_args = mock_k8s.create_or_update_networkpolicy.call_args
        netpol_body = call_args.kwargs["body"]
        svc_rule = netpol_body["spec"]["egress"][2]
        ns_selector = svc_rule["to"][0]["namespaceSelector"]["matchLabels"]
        assert ns_selector == {"kubernetes.io/metadata.name": "other-ns"}

    @pytest.mark.asyncio
    async def test_reconcile_networkpolicy_with_no_tools(
        self,
        sample_mcpserver_spec: dict[str, Any],
        mock_logger: MagicMock,
        sample_body: dict[str, Any],
    ) -> None:
        """Test that NetworkPolicy with no tools has only Redis + DNS rules."""
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

        call_args = mock_k8s.create_or_update_networkpolicy.call_args
        netpol_body = call_args.kwargs["body"]
        egress = netpol_body["spec"]["egress"]
        # Redis + DNS only = 2 rules
        assert len(egress) == 2
        # Verify pod selector targets the right server
        pod_selector = netpol_body["spec"]["podSelector"]["matchLabels"]
        assert pod_selector == {
            "app.kubernetes.io/name": "mcp-server",
            "app.kubernetes.io/instance": "test-server",
        }

    @pytest.mark.asyncio
    async def test_reconcile_networkpolicy_includes_resource_service_targets(
        self,
        sample_mcpserver_spec: dict[str, Any],
        mock_logger: MagicMock,
        sample_body: dict[str, Any],
    ) -> None:
        """Resource operations with service refs should generate egress allow rules."""
        tool1 = self._make_tool_cr("tool1", "tool-svc")
        resource1 = self._make_resource_cr("resource1", "resource-svc")

        mock_k8s = MagicMock()
        mock_k8s.list_by_label_selector.side_effect = [[tool1], [], [resource1]]
        mock_k8s.get_service_endpoint.side_effect = lambda name, ns, port: (
            f"http://{name}.{ns}.svc.cluster.local:{port}"
        )
        mock_k8s.get_service.side_effect = lambda name, ns: self._make_service_dict({"app": name})
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

        call_args = mock_k8s.create_or_update_networkpolicy.call_args
        egress = call_args.kwargs["body"]["spec"]["egress"]
        # Redis + DNS + tool + resource = 4 rules
        assert len(egress) == 4

    @pytest.mark.asyncio
    async def test_reconcile_networkpolicy_fails_selectorless_without_annotation(
        self,
        sample_mcpserver_spec: dict[str, Any],
        mock_logger: MagicMock,
        sample_body: dict[str, Any],
    ) -> None:
        """Selectorless services must declare namespace/cidr egress mode."""
        tool1 = self._make_tool_cr("tool1", "selectorless-svc")

        mock_k8s = MagicMock()
        mock_k8s.list_by_label_selector.side_effect = [[tool1], [], []]
        mock_k8s.get_service_endpoint.side_effect = lambda name, ns, port: (
            f"http://{name}.{ns}.svc.cluster.local:{port}"
        )
        mock_k8s.get_service.return_value = self._make_service_dict(None)
        mock_k8s.get_deployment.return_value = {"status": {"readyReplicas": 1}}
        mock_patch_obj = MagicMock()
        mock_patch_obj.status = {}

        with (
            patch("src.controllers.mcpserver_controller.get_k8s_client", return_value=mock_k8s),
            pytest.raises(ValueError, match="has no selector"),
        ):
            await reconcile_mcpserver(
                spec=sample_mcpserver_spec,
                name="test-server",
                namespace="default",
                logger=mock_logger,
                patch=mock_patch_obj,
                body=sample_body,
            )

    @pytest.mark.asyncio
    async def test_reconcile_networkpolicy_allows_selectorless_namespace_mode(
        self,
        sample_mcpserver_spec: dict[str, Any],
        mock_logger: MagicMock,
        sample_body: dict[str, Any],
    ) -> None:
        """Selectorless services can be allowed via namespace mode annotation."""
        tool1 = self._make_tool_cr(
            "tool1",
            "selectorless-svc",
            annotations={"kubemcp.io/egress-mode": "namespace"},
        )

        mock_k8s = MagicMock()
        mock_k8s.list_by_label_selector.side_effect = [[tool1], [], []]
        mock_k8s.get_service_endpoint.side_effect = lambda name, ns, port: (
            f"http://{name}.{ns}.svc.cluster.local:{port}"
        )
        mock_k8s.get_service.return_value = self._make_service_dict(None)
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

        call_args = mock_k8s.create_or_update_networkpolicy.call_args
        svc_rule = call_args.kwargs["body"]["spec"]["egress"][2]
        assert "podSelector" not in svc_rule["to"][0]
        assert svc_rule["to"][0]["namespaceSelector"]["matchLabels"] == {
            "kubernetes.io/metadata.name": "default"
        }

    @pytest.mark.asyncio
    async def test_reconcile_networkpolicy_externalname_requires_cidr_mode(
        self,
        sample_mcpserver_spec: dict[str, Any],
        mock_logger: MagicMock,
        sample_body: dict[str, Any],
    ) -> None:
        """ExternalName services require CIDR mode with explicit cidrs."""
        tool1 = self._make_tool_cr("tool1", "external-svc")

        mock_k8s = MagicMock()
        mock_k8s.list_by_label_selector.side_effect = [[tool1], [], []]
        mock_k8s.get_service_endpoint.side_effect = lambda name, ns, port: (
            f"http://{name}.{ns}.svc.cluster.local:{port}"
        )
        mock_k8s.get_service.return_value = self._make_service_dict(None, svc_type="ExternalName")
        mock_k8s.get_deployment.return_value = {"status": {"readyReplicas": 1}}
        mock_patch_obj = MagicMock()
        mock_patch_obj.status = {}

        with (
            patch("src.controllers.mcpserver_controller.get_k8s_client", return_value=mock_k8s),
            pytest.raises(ValueError, match="ExternalName"),
        ):
            await reconcile_mcpserver(
                spec=sample_mcpserver_spec,
                name="test-server",
                namespace="default",
                logger=mock_logger,
                patch=mock_patch_obj,
                body=sample_body,
            )

    @pytest.mark.asyncio
    async def test_reconcile_networkpolicy_externalname_cidr_mode_success(
        self,
        sample_mcpserver_spec: dict[str, Any],
        mock_logger: MagicMock,
        sample_body: dict[str, Any],
    ) -> None:
        """ExternalName service can be allowed via cidr mode annotations."""
        tool1 = self._make_tool_cr(
            "tool1",
            "external-svc",
            annotations={
                "kubemcp.io/egress-mode": "cidr",
                "kubemcp.io/egress-cidrs": "1.2.3.4/32",
            },
        )

        mock_k8s = MagicMock()
        mock_k8s.list_by_label_selector.side_effect = [[tool1], [], []]
        mock_k8s.get_service_endpoint.side_effect = lambda name, ns, port: (
            f"http://{name}.{ns}.svc.cluster.local:{port}"
        )
        mock_k8s.get_service.return_value = self._make_service_dict(None, svc_type="ExternalName")
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

        call_args = mock_k8s.create_or_update_networkpolicy.call_args
        svc_rule = call_args.kwargs["body"]["spec"]["egress"][2]
        assert svc_rule["to"] == [{"ipBlock": {"cidr": "1.2.3.4/32"}}]
        assert svc_rule["ports"] == [{"port": 8080, "protocol": "TCP"}]

    @pytest.mark.asyncio
    async def test_reconcile_networkpolicy_cidr_mode_multiple_cidrs_and_ports(
        self,
        sample_mcpserver_spec: dict[str, Any],
        mock_logger: MagicMock,
        sample_body: dict[str, Any],
    ) -> None:
        """CIDR mode should normalize and deduplicate CIDRs and ports."""
        tool1 = self._make_tool_cr(
            "tool1",
            "external-svc",
            svc_port=443,
            annotations={
                "kubemcp.io/egress-mode": "cidr",
                "kubemcp.io/egress-cidrs": "10.0.0.0/8, 10.0.0.0/8, 1.2.3.4/32",
                "kubemcp.io/egress-ports": "8443,443,443",
            },
        )

        mock_k8s = MagicMock()
        mock_k8s.list_by_label_selector.side_effect = [[tool1], [], []]
        mock_k8s.get_service_endpoint.side_effect = lambda name, ns, port: (
            f"http://{name}.{ns}.svc.cluster.local:{port}"
        )
        mock_k8s.get_service.return_value = self._make_service_dict(None, svc_type="ExternalName")
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

        call_args = mock_k8s.create_or_update_networkpolicy.call_args
        svc_rule = call_args.kwargs["body"]["spec"]["egress"][2]
        assert svc_rule["to"] == [
            {"ipBlock": {"cidr": "1.2.3.4/32"}},
            {"ipBlock": {"cidr": "10.0.0.0/8"}},
        ]
        assert svc_rule["ports"] == [
            {"port": 443, "protocol": "TCP"},
            {"port": 8443, "protocol": "TCP"},
        ]

    @pytest.mark.asyncio
    async def test_reconcile_operator_networkpolicy_uses_detected_api_cidr(
        self,
        sample_mcpserver_spec: dict[str, Any],
        mock_logger: MagicMock,
        sample_body: dict[str, Any],
    ) -> None:
        """Operator policy should use detected API server CIDR by default."""
        mock_k8s = MagicMock()
        mock_k8s.list_by_label_selector.side_effect = [[], [], []]
        mock_k8s.get_api_server_cidr.return_value = "10.43.0.1/32"
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

        operator_calls = [
            call
            for call in mock_k8s.create_or_update_networkpolicy.call_args_list
            if call.kwargs.get("name") == "mcp-operator-policy"
        ]
        assert len(operator_calls) == 1
        operator_egress = operator_calls[0].kwargs["body"]["spec"]["egress"]
        assert operator_egress[1]["to"] == [{"ipBlock": {"cidr": "10.43.0.1/32"}}]

    @pytest.mark.asyncio
    async def test_reconcile_operator_networkpolicy_uses_env_override(
        self,
        sample_mcpserver_spec: dict[str, Any],
        mock_logger: MagicMock,
        sample_body: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Env override should take precedence over auto-detection."""
        monkeypatch.setenv("MCP_OPERATOR_API_SERVER_CIDR", "192.168.0.10/32")
        mock_k8s = MagicMock()
        mock_k8s.list_by_label_selector.side_effect = [[], [], []]
        mock_k8s.get_api_server_cidr.return_value = "10.43.0.1/32"
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

        operator_calls = [
            call
            for call in mock_k8s.create_or_update_networkpolicy.call_args_list
            if call.kwargs.get("name") == "mcp-operator-policy"
        ]
        assert len(operator_calls) == 1
        operator_egress = operator_calls[0].kwargs["body"]["spec"]["egress"]
        assert operator_egress[1]["to"] == [{"ipBlock": {"cidr": "192.168.0.10/32"}}]

    @pytest.mark.asyncio
    async def test_reconcile_operator_networkpolicy_falls_back_to_broad_cidr(
        self,
        sample_mcpserver_spec: dict[str, Any],
        mock_logger: MagicMock,
        sample_body: dict[str, Any],
    ) -> None:
        """If detection fails, operator policy should fall back to 0.0.0.0/0."""
        mock_k8s = MagicMock()
        mock_k8s.list_by_label_selector.side_effect = [[], [], []]
        mock_k8s.get_api_server_cidr.return_value = None
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

        operator_calls = [
            call
            for call in mock_k8s.create_or_update_networkpolicy.call_args_list
            if call.kwargs.get("name") == "mcp-operator-policy"
        ]
        assert len(operator_calls) == 1
        operator_egress = operator_calls[0].kwargs["body"]["spec"]["egress"]
        assert operator_egress[1]["to"] == [{"ipBlock": {"cidr": "0.0.0.0/0"}}]
