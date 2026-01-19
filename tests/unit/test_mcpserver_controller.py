"""Unit tests for MCPServer controller."""

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

    @pytest.mark.asyncio
    async def test_reconcile_finds_tools_by_selector(
        self,
        sample_mcpserver_spec: dict[str, Any],
        mock_logger: MagicMock,
        mock_tools: list[dict[str, Any]],
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
            )

        assert mock_patch_obj.status["toolCount"] == 2
        assert mock_patch_obj.status["promptCount"] == 1
        assert mock_patch_obj.status["resourceCount"] == 1

    @pytest.mark.asyncio
    async def test_reconcile_sets_ready_replicas(
        self,
        sample_mcpserver_spec: dict[str, Any],
        mock_logger: MagicMock,
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
            )

        assert mock_patch_obj.status["readyReplicas"] == 2

    @pytest.mark.asyncio
    async def test_reconcile_deployment_not_found_sets_zero_replicas(
        self,
        sample_mcpserver_spec: dict[str, Any],
        mock_logger: MagicMock,
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
            )

        assert mock_patch_obj.status["readyReplicas"] == 0

    @pytest.mark.asyncio
    async def test_reconcile_sets_conditions(
        self,
        sample_mcpserver_spec: dict[str, Any],
        mock_logger: MagicMock,
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
            )

        mock_logger.info.assert_called()

    @pytest.mark.asyncio
    async def test_reconcile_uses_tool_selector_for_all_resources(
        self,
        sample_mcpserver_spec: dict[str, Any],
        mock_logger: MagicMock,
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
            )

        assert mock_patch_obj.status["toolCount"] == 0
        assert mock_patch_obj.status["promptCount"] == 0
        assert mock_patch_obj.status["resourceCount"] == 0
