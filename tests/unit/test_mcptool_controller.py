"""Unit tests for MCPTool controller."""

from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.controllers.mcptool_controller import reconcile_mcptool
from src.models.crds import MCPToolSpec


class TestMCPToolSpec:
    """Tests for MCPToolSpec validation."""

    def test_valid_spec(self, sample_mcptool_spec: dict[str, Any]) -> None:
        """Test that a valid spec is accepted."""
        spec = MCPToolSpec(**sample_mcptool_spec)
        assert spec.name == "github-search"
        assert spec.service.name == "github-tool-svc"
        assert spec.service.port == 8080
        assert spec.method == "POST"

    def test_default_method(self) -> None:
        """Test that method defaults to POST."""
        spec = MCPToolSpec(
            name="test-tool",
            service={"name": "svc", "port": 8080},
        )
        assert spec.method == "POST"

    def test_default_path(self) -> None:
        """Test that service path defaults to /."""
        spec = MCPToolSpec(
            name="test-tool",
            service={"name": "svc", "port": 8080},
        )
        assert spec.service.path == "/"

    def test_invalid_method(self) -> None:
        """Test that invalid HTTP method is rejected."""
        with pytest.raises(ValueError):
            MCPToolSpec(
                name="test-tool",
                service={"name": "svc", "port": 8080},
                method="INVALID",
            )

    def test_service_namespace_defaults_to_none(self) -> None:
        """Test that service namespace defaults to None (same as MCPTool)."""
        spec = MCPToolSpec(
            name="test-tool",
            service={"name": "svc", "port": 8080},
        )
        assert spec.service.namespace is None

    def test_service_with_explicit_namespace(self) -> None:
        """Test that service can have explicit namespace."""
        spec = MCPToolSpec(
            name="test-tool",
            service={"name": "svc", "namespace": "other-ns", "port": 8080},
        )
        assert spec.service.namespace == "other-ns"


class TestMCPToolReconciliation:
    """Tests for MCPTool reconciliation logic."""

    @pytest.fixture
    def mock_logger(self) -> MagicMock:
        """Create a mock logger."""
        return MagicMock()

    @pytest.mark.asyncio
    async def test_reconcile_service_exists_sets_ready_true(
        self,
        sample_mcptool_spec: dict[str, Any],
        mock_logger: MagicMock,
    ) -> None:
        """Test that reconciliation sets ready=True when service exists."""
        mock_k8s = MagicMock()
        mock_k8s.get_service.return_value = {"metadata": {"name": "github-tool-svc"}}
        mock_k8s.get_service_endpoint.return_value = (
            "http://github-tool-svc.default.svc.cluster.local:8080"
        )

        with patch("src.controllers.mcptool_controller.get_k8s_client", return_value=mock_k8s):
            result = await reconcile_mcptool(
                spec=sample_mcptool_spec,
                name="github-search",
                namespace="default",
                logger=mock_logger,
            )

        assert result["ready"] is True
        assert "github-tool-svc" in result["resolvedEndpoint"]
        mock_k8s.get_service.assert_called_once()

    @pytest.mark.asyncio
    async def test_reconcile_service_not_found_sets_ready_false(
        self,
        sample_mcptool_spec: dict[str, Any],
        mock_logger: MagicMock,
    ) -> None:
        """Test that reconciliation sets ready=False when service doesn't exist."""
        mock_k8s = MagicMock()
        mock_k8s.get_service.return_value = None

        with patch("src.controllers.mcptool_controller.get_k8s_client", return_value=mock_k8s):
            result = await reconcile_mcptool(
                spec=sample_mcptool_spec,
                name="github-search",
                namespace="default",
                logger=mock_logger,
            )

        assert result["ready"] is False
        assert result["resolvedEndpoint"] is None
        # Should have a condition explaining the failure
        assert len(result["conditions"]) > 0
        assert result["conditions"][0]["type"] == "Ready"
        assert result["conditions"][0]["status"] == "False"
        assert "not found" in result["conditions"][0]["message"].lower()

    @pytest.mark.asyncio
    async def test_reconcile_resolves_endpoint_same_namespace(
        self,
        sample_mcptool_spec: dict[str, Any],
        mock_logger: MagicMock,
    ) -> None:
        """Test endpoint resolution uses MCPTool namespace when service ns not specified."""
        mock_k8s = MagicMock()
        mock_k8s.get_service.return_value = {"metadata": {"name": "github-tool-svc"}}
        mock_k8s.get_service_endpoint.return_value = (
            "http://github-tool-svc.mcp-system.svc.cluster.local:8080"
        )

        with patch("src.controllers.mcptool_controller.get_k8s_client", return_value=mock_k8s):
            result = await reconcile_mcptool(
                spec=sample_mcptool_spec,
                name="github-search",
                namespace="mcp-system",
                logger=mock_logger,
            )

        # Service lookup should use MCPTool's namespace
        mock_k8s.get_service.assert_called_with("github-tool-svc", "mcp-system")
        assert "mcp-system" in result["resolvedEndpoint"]

    @pytest.mark.asyncio
    async def test_reconcile_resolves_endpoint_cross_namespace(
        self,
        mock_logger: MagicMock,
    ) -> None:
        """Test endpoint resolution uses explicit service namespace."""
        spec = {
            "name": "cross-ns-tool",
            "service": {"name": "backend-svc", "namespace": "backend-ns", "port": 9000},
        }

        mock_k8s = MagicMock()
        mock_k8s.get_service.return_value = {"metadata": {"name": "backend-svc"}}
        mock_k8s.get_service_endpoint.return_value = (
            "http://backend-svc.backend-ns.svc.cluster.local:9000"
        )

        with patch("src.controllers.mcptool_controller.get_k8s_client", return_value=mock_k8s):
            result = await reconcile_mcptool(
                spec=spec,
                name="cross-ns-tool",
                namespace="default",
                logger=mock_logger,
            )

        # Service lookup should use explicit namespace
        mock_k8s.get_service.assert_called_with("backend-svc", "backend-ns")
        assert "backend-ns" in result["resolvedEndpoint"]

    @pytest.mark.asyncio
    async def test_reconcile_includes_path_in_endpoint(
        self,
        sample_mcptool_spec: dict[str, Any],
        mock_logger: MagicMock,
    ) -> None:
        """Test that resolved endpoint includes service path."""
        mock_k8s = MagicMock()
        mock_k8s.get_service.return_value = {"metadata": {"name": "github-tool-svc"}}
        mock_k8s.get_service_endpoint.return_value = (
            "http://github-tool-svc.default.svc.cluster.local:8080"
        )

        with patch("src.controllers.mcptool_controller.get_k8s_client", return_value=mock_k8s):
            result = await reconcile_mcptool(
                spec=sample_mcptool_spec,
                name="github-search",
                namespace="default",
                logger=mock_logger,
            )

        # Endpoint should include the path from spec
        assert result["resolvedEndpoint"].endswith("/search")

    @pytest.mark.asyncio
    async def test_reconcile_sets_last_sync_time(
        self,
        sample_mcptool_spec: dict[str, Any],
        mock_logger: MagicMock,
    ) -> None:
        """Test that reconciliation sets lastSyncTime."""
        mock_k8s = MagicMock()
        mock_k8s.get_service.return_value = {"metadata": {"name": "github-tool-svc"}}
        mock_k8s.get_service_endpoint.return_value = (
            "http://github-tool-svc.default.svc.cluster.local:8080"
        )

        with patch("src.controllers.mcptool_controller.get_k8s_client", return_value=mock_k8s):
            result = await reconcile_mcptool(
                spec=sample_mcptool_spec,
                name="github-search",
                namespace="default",
                logger=mock_logger,
            )

        assert result["lastSyncTime"] is not None
        # Should be a valid ISO format timestamp
        datetime.fromisoformat(result["lastSyncTime"].replace("Z", "+00:00"))

    @pytest.mark.asyncio
    async def test_reconcile_ready_condition_when_ready(
        self,
        sample_mcptool_spec: dict[str, Any],
        mock_logger: MagicMock,
    ) -> None:
        """Test that Ready condition is True when service exists."""
        mock_k8s = MagicMock()
        mock_k8s.get_service.return_value = {"metadata": {"name": "github-tool-svc"}}
        mock_k8s.get_service_endpoint.return_value = (
            "http://github-tool-svc.default.svc.cluster.local:8080"
        )

        with patch("src.controllers.mcptool_controller.get_k8s_client", return_value=mock_k8s):
            result = await reconcile_mcptool(
                spec=sample_mcptool_spec,
                name="github-search",
                namespace="default",
                logger=mock_logger,
            )

        ready_condition = next((c for c in result["conditions"] if c["type"] == "Ready"), None)
        assert ready_condition is not None
        assert ready_condition["status"] == "True"
        assert ready_condition["reason"] == "ServiceResolved"

    @pytest.mark.asyncio
    async def test_reconcile_logs_info(
        self,
        sample_mcptool_spec: dict[str, Any],
        mock_logger: MagicMock,
    ) -> None:
        """Test that reconciliation logs appropriate info."""
        mock_k8s = MagicMock()
        mock_k8s.get_service.return_value = {"metadata": {"name": "github-tool-svc"}}
        mock_k8s.get_service_endpoint.return_value = (
            "http://github-tool-svc.default.svc.cluster.local:8080"
        )

        with patch("src.controllers.mcptool_controller.get_k8s_client", return_value=mock_k8s):
            await reconcile_mcptool(
                spec=sample_mcptool_spec,
                name="github-search",
                namespace="default",
                logger=mock_logger,
            )

        mock_logger.info.assert_called()
