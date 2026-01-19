"""Unit tests for MCPResource controller."""

from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.controllers.mcpresource_controller import reconcile_mcpresource
from src.models.crds import MCPResourceSpec


class TestMCPResourceSpec:
    """Tests for MCPResourceSpec validation."""

    def test_valid_operations_spec(
        self, sample_mcpresource_spec_operations: dict[str, Any]
    ) -> None:
        """Test that a valid operations spec is accepted."""
        spec = MCPResourceSpec(**sample_mcpresource_spec_operations)
        assert spec.name == "github-docs"
        assert spec.operations is not None
        assert len(spec.operations) == 1
        assert spec.operations[0].method == "GET"

    def test_valid_inline_spec(self, sample_mcpresource_spec_inline: dict[str, Any]) -> None:
        """Test that a valid inline content spec is accepted."""
        spec = MCPResourceSpec(**sample_mcpresource_spec_inline)
        assert spec.name == "config-template"
        assert spec.content is not None
        assert spec.content.mimeType == "text/yaml"
        assert "key: value" in (spec.content.text or "")

    def test_operation_parameters(self, sample_mcpresource_spec_operations: dict[str, Any]) -> None:
        """Test that operation parameters are parsed correctly."""
        spec = MCPResourceSpec(**sample_mcpresource_spec_operations)
        assert spec.operations is not None
        params = spec.operations[0].parameters
        assert len(params) == 2
        section_param = next(p for p in params if p.name == "section")
        assert section_param.in_ == "path"
        assert section_param.required is True

    def test_empty_spec_requires_either_operations_or_content(self) -> None:
        """Test that resource must have either operations or content."""
        # This should be valid - neither operations nor content is required by pydantic
        # But we'll validate this in reconciliation
        spec = MCPResourceSpec(
            name="empty-resource",
            description="Resource with no operations or content",
        )
        assert spec.operations is None
        assert spec.content is None


class TestMCPResourceReconciliation:
    """Tests for MCPResource reconciliation logic."""

    @pytest.fixture
    def mock_logger(self) -> MagicMock:
        """Create a mock logger."""
        return MagicMock()

    @pytest.mark.asyncio
    async def test_reconcile_operations_service_exists_sets_ready_true(
        self,
        sample_mcpresource_spec_operations: dict[str, Any],
        mock_logger: MagicMock,
    ) -> None:
        """Test that reconciliation sets ready=True when service exists for operations."""
        mock_k8s = MagicMock()
        mock_k8s.get_service.return_value = {"metadata": {"name": "github-docs-svc"}}
        mock_k8s.get_service_endpoint.return_value = (
            "http://github-docs-svc.default.svc.cluster.local:8080"
        )

        with patch("src.controllers.mcpresource_controller.get_k8s_client", return_value=mock_k8s):
            result = await reconcile_mcpresource(
                spec=sample_mcpresource_spec_operations,
                name="github-docs",
                namespace="default",
                logger=mock_logger,
            )

        assert result["ready"] is True
        assert result["operationCount"] == 1
        mock_k8s.get_service.assert_called_once()

    @pytest.mark.asyncio
    async def test_reconcile_operations_service_not_found_sets_ready_false(
        self,
        sample_mcpresource_spec_operations: dict[str, Any],
        mock_logger: MagicMock,
    ) -> None:
        """Test that reconciliation sets ready=False when service doesn't exist."""
        mock_k8s = MagicMock()
        mock_k8s.get_service.return_value = None

        with patch("src.controllers.mcpresource_controller.get_k8s_client", return_value=mock_k8s):
            result = await reconcile_mcpresource(
                spec=sample_mcpresource_spec_operations,
                name="github-docs",
                namespace="default",
                logger=mock_logger,
            )

        assert result["ready"] is False
        assert len(result["conditions"]) > 0
        assert result["conditions"][0]["type"] == "Ready"
        assert result["conditions"][0]["status"] == "False"
        assert "not found" in result["conditions"][0]["message"].lower()

    @pytest.mark.asyncio
    async def test_reconcile_inline_content_sets_ready_true(
        self,
        sample_mcpresource_spec_inline: dict[str, Any],
        mock_logger: MagicMock,
    ) -> None:
        """Test that reconciliation sets ready=True for valid inline content."""
        result = await reconcile_mcpresource(
            spec=sample_mcpresource_spec_inline,
            name="config-template",
            namespace="default",
            logger=mock_logger,
        )

        assert result["ready"] is True
        assert result["operationCount"] == 0

    @pytest.mark.asyncio
    async def test_reconcile_empty_content_sets_ready_false(
        self,
        mock_logger: MagicMock,
    ) -> None:
        """Test that reconciliation fails for empty inline content."""
        spec = {
            "name": "empty-content",
            "content": {
                "uri": "config://empty",
                "mimeType": "text/plain",
                "text": "",
            },
        }

        result = await reconcile_mcpresource(
            spec=spec,
            name="empty-content",
            namespace="default",
            logger=mock_logger,
        )

        assert result["ready"] is False
        assert len(result["conditions"]) > 0
        assert "empty" in result["conditions"][0]["message"].lower()

    @pytest.mark.asyncio
    async def test_reconcile_neither_operations_nor_content_sets_ready_false(
        self,
        mock_logger: MagicMock,
    ) -> None:
        """Test that reconciliation fails when neither operations nor content provided."""
        spec = {
            "name": "invalid-resource",
            "description": "Has neither operations nor content",
        }

        result = await reconcile_mcpresource(
            spec=spec,
            name="invalid-resource",
            namespace="default",
            logger=mock_logger,
        )

        assert result["ready"] is False
        assert len(result["conditions"]) > 0
        assert result["conditions"][0]["status"] == "False"

    @pytest.mark.asyncio
    async def test_reconcile_sets_last_sync_time(
        self,
        sample_mcpresource_spec_inline: dict[str, Any],
        mock_logger: MagicMock,
    ) -> None:
        """Test that reconciliation sets lastSyncTime."""
        result = await reconcile_mcpresource(
            spec=sample_mcpresource_spec_inline,
            name="config-template",
            namespace="default",
            logger=mock_logger,
        )

        assert result["lastSyncTime"] is not None
        # Should be a valid ISO format timestamp
        datetime.fromisoformat(result["lastSyncTime"].replace("Z", "+00:00"))

    @pytest.mark.asyncio
    async def test_reconcile_ready_condition_when_ready(
        self,
        sample_mcpresource_spec_inline: dict[str, Any],
        mock_logger: MagicMock,
    ) -> None:
        """Test that Ready condition is True when resource is valid."""
        result = await reconcile_mcpresource(
            spec=sample_mcpresource_spec_inline,
            name="config-template",
            namespace="default",
            logger=mock_logger,
        )

        ready_condition = next((c for c in result["conditions"] if c["type"] == "Ready"), None)
        assert ready_condition is not None
        assert ready_condition["status"] == "True"
        assert ready_condition["reason"] == "ContentValid"

    @pytest.mark.asyncio
    async def test_reconcile_logs_info(
        self,
        sample_mcpresource_spec_inline: dict[str, Any],
        mock_logger: MagicMock,
    ) -> None:
        """Test that reconciliation logs appropriate info."""
        await reconcile_mcpresource(
            spec=sample_mcpresource_spec_inline,
            name="config-template",
            namespace="default",
            logger=mock_logger,
        )

        mock_logger.info.assert_called()

    @pytest.mark.asyncio
    async def test_reconcile_multiple_operations_counts_correctly(
        self,
        mock_logger: MagicMock,
    ) -> None:
        """Test that operation count is correct for multiple operations."""
        spec = {
            "name": "multi-op",
            "operations": [
                {
                    "method": "GET",
                    "ingressPath": "/items",
                    "service": {"name": "svc", "port": 8080, "path": "/api/items"},
                },
                {
                    "method": "POST",
                    "ingressPath": "/items",
                    "service": {"name": "svc", "port": 8080, "path": "/api/items"},
                },
                {
                    "method": "DELETE",
                    "ingressPath": "/items/{id}",
                    "service": {"name": "svc", "port": 8080, "path": "/api/items/{id}"},
                    "parameters": [{"name": "id", "in": "path", "required": True}],
                },
            ],
        }

        mock_k8s = MagicMock()
        mock_k8s.get_service.return_value = {"metadata": {"name": "svc"}}
        mock_k8s.get_service_endpoint.return_value = "http://svc.default.svc.cluster.local:8080"

        with patch("src.controllers.mcpresource_controller.get_k8s_client", return_value=mock_k8s):
            result = await reconcile_mcpresource(
                spec=spec,
                name="multi-op",
                namespace="default",
                logger=mock_logger,
            )

        assert result["operationCount"] == 3

    @pytest.mark.asyncio
    async def test_reconcile_resolves_endpoint_same_namespace(
        self,
        sample_mcpresource_spec_operations: dict[str, Any],
        mock_logger: MagicMock,
    ) -> None:
        """Test endpoint resolution uses MCPResource namespace when service ns not specified."""
        mock_k8s = MagicMock()
        mock_k8s.get_service.return_value = {"metadata": {"name": "github-docs-svc"}}
        mock_k8s.get_service_endpoint.return_value = (
            "http://github-docs-svc.mcp-system.svc.cluster.local:8080"
        )

        with patch("src.controllers.mcpresource_controller.get_k8s_client", return_value=mock_k8s):
            await reconcile_mcpresource(
                spec=sample_mcpresource_spec_operations,
                name="github-docs",
                namespace="mcp-system",
                logger=mock_logger,
            )

        # Service lookup should use MCPResource's namespace
        mock_k8s.get_service.assert_called_with("github-docs-svc", "mcp-system")

    @pytest.mark.asyncio
    async def test_reconcile_operations_cross_namespace(
        self,
        mock_logger: MagicMock,
    ) -> None:
        """Test endpoint resolution uses explicit service namespace."""
        spec = {
            "name": "cross-ns-resource",
            "operations": [
                {
                    "method": "GET",
                    "ingressPath": "/data",
                    "service": {
                        "name": "data-svc",
                        "namespace": "data-ns",
                        "port": 9000,
                        "path": "/api/data",
                    },
                },
            ],
        }

        mock_k8s = MagicMock()
        mock_k8s.get_service.return_value = {"metadata": {"name": "data-svc"}}
        mock_k8s.get_service_endpoint.return_value = (
            "http://data-svc.data-ns.svc.cluster.local:9000"
        )

        with patch("src.controllers.mcpresource_controller.get_k8s_client", return_value=mock_k8s):
            result = await reconcile_mcpresource(
                spec=spec,
                name="cross-ns-resource",
                namespace="default",
                logger=mock_logger,
            )

        # Service lookup should use explicit namespace
        mock_k8s.get_service.assert_called_with("data-svc", "data-ns")
        assert result["ready"] is True
