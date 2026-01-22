"""Unit tests for MCPPrompt controller."""

from datetime import datetime
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.controllers.mcpprompt_controller import reconcile_mcpprompt
from src.models.crds import MCPPromptSpec


class TestMCPPromptSpec:
    """Tests for MCPPromptSpec validation."""

    def test_valid_spec(self, sample_mcpprompt_spec: dict[str, Any]) -> None:
        """Test that a valid spec is accepted."""
        spec = MCPPromptSpec(**sample_mcpprompt_spec)
        assert spec.name == "github-query-helper"
        assert "{{query}}" in spec.template
        assert len(spec.variables) == 2

    def test_variable_required(self, sample_mcpprompt_spec: dict[str, Any]) -> None:
        """Test that required flag is parsed correctly."""
        spec = MCPPromptSpec(**sample_mcpprompt_spec)
        query_var = next(v for v in spec.variables if v.name == "query")
        language_var = next(v for v in spec.variables if v.name == "language")
        assert query_var.required is True
        assert language_var.required is False

    def test_variable_default(self, sample_mcpprompt_spec: dict[str, Any]) -> None:
        """Test that default values are parsed correctly."""
        spec = MCPPromptSpec(**sample_mcpprompt_spec)
        language_var = next(v for v in spec.variables if v.name == "language")
        assert language_var.default == "any"

    def test_template_min_length(self) -> None:
        """Test that template must have at least 1 character."""
        with pytest.raises(ValueError):
            MCPPromptSpec(
                name="test-prompt",
                template="",
            )

    def test_variable_name_pattern(self) -> None:
        """Test that variable names must match pattern."""
        with pytest.raises(ValueError):
            MCPPromptSpec(
                name="test-prompt",
                template="Hello {{name}}",
                variables=[
                    {"name": "invalid-name", "description": "Has hyphen"}  # hyphens not allowed
                ],
            )

    def test_empty_variables_list(self) -> None:
        """Test that prompts without variables are valid."""
        spec = MCPPromptSpec(
            name="simple-prompt",
            template="A prompt with no variables.",
        )
        assert spec.variables == []


class TestMCPPromptReconciliation:
    """Tests for MCPPrompt reconciliation logic."""

    @pytest.fixture
    def mock_logger(self) -> MagicMock:
        """Create a mock logger."""
        return MagicMock()

    @pytest.mark.asyncio
    async def test_reconcile_valid_template_sets_validated_true(
        self,
        sample_mcpprompt_spec: dict[str, Any],
        mock_logger: MagicMock,
    ) -> None:
        """Test that reconciliation sets validated=True when template is valid."""
        mock_patch_obj = MagicMock()
        mock_patch_obj.status = {}
        await reconcile_mcpprompt(
            spec=sample_mcpprompt_spec,
            name="github-query-helper",
            namespace="default",
            logger=mock_logger,
            patch=mock_patch_obj,
        )

        assert mock_patch_obj.status["validated"] is True
        assert len(mock_patch_obj.status["conditions"]) > 0

    @pytest.mark.asyncio
    async def test_reconcile_undeclared_variable_sets_validated_false(
        self,
        mock_logger: MagicMock,
    ) -> None:
        """Test that reconciliation fails when template has undeclared variables."""
        spec = {
            "name": "bad-template",
            "template": "Hello {{name}}! Your order {{order_id}} is ready.",
            "variables": [
                {"name": "name", "description": "User name"},
                # order_id is NOT declared
            ],
        }
        mock_patch_obj = MagicMock()
        mock_patch_obj.status = {}

        await reconcile_mcpprompt(
            spec=spec,
            name="bad-template",
            namespace="default",
            logger=mock_logger,
            patch=mock_patch_obj,
        )

        assert mock_patch_obj.status["validated"] is False
        # Should have a condition explaining the failure
        assert len(mock_patch_obj.status["conditions"]) > 0
        assert mock_patch_obj.status["conditions"][0]["type"] == "Validated"
        assert mock_patch_obj.status["conditions"][0]["status"] == "False"
        assert "order_id" in mock_patch_obj.status["conditions"][0]["message"]

    @pytest.mark.asyncio
    async def test_reconcile_unused_variable_sets_validated_false(
        self,
        mock_logger: MagicMock,
    ) -> None:
        """Test that reconciliation fails when variable is declared but unused."""
        spec = {
            "name": "unused-var",
            "template": "Hello {{name}}!",
            "variables": [
                {"name": "name", "description": "User name"},
                {"name": "unused_var", "description": "This is never used"},
            ],
        }
        mock_patch_obj = MagicMock()
        mock_patch_obj.status = {}

        await reconcile_mcpprompt(
            spec=spec,
            name="unused-var",
            namespace="default",
            logger=mock_logger,
            patch=mock_patch_obj,
        )

        assert mock_patch_obj.status["validated"] is False
        assert mock_patch_obj.status["conditions"][0]["type"] == "Validated"
        assert mock_patch_obj.status["conditions"][0]["status"] == "False"
        assert "unused_var" in mock_patch_obj.status["conditions"][0]["message"]

    @pytest.mark.asyncio
    async def test_reconcile_valid_condition_when_valid(
        self,
        sample_mcpprompt_spec: dict[str, Any],
        mock_logger: MagicMock,
    ) -> None:
        """Test that Validated condition is True when template is valid."""
        mock_patch_obj = MagicMock()
        mock_patch_obj.status = {}
        await reconcile_mcpprompt(
            spec=sample_mcpprompt_spec,
            name="github-query-helper",
            namespace="default",
            logger=mock_logger,
            patch=mock_patch_obj,
        )

        validated_condition = next(
            (c for c in mock_patch_obj.status["conditions"] if c["type"] == "Validated"), None
        )
        assert validated_condition is not None
        assert validated_condition["status"] == "True"
        assert validated_condition["reason"] == "TemplateValid"

    @pytest.mark.asyncio
    async def test_reconcile_sets_last_validation_time(
        self,
        sample_mcpprompt_spec: dict[str, Any],
        mock_logger: MagicMock,
    ) -> None:
        """Test that reconciliation sets lastValidationTime."""
        mock_patch_obj = MagicMock()
        mock_patch_obj.status = {}
        await reconcile_mcpprompt(
            spec=sample_mcpprompt_spec,
            name="github-query-helper",
            namespace="default",
            logger=mock_logger,
            patch=mock_patch_obj,
        )

        assert mock_patch_obj.status["lastValidationTime"] is not None
        # Should be a valid ISO format timestamp
        datetime.fromisoformat(mock_patch_obj.status["lastValidationTime"].replace("Z", "+00:00"))

    @pytest.mark.asyncio
    async def test_reconcile_logs_info(
        self,
        sample_mcpprompt_spec: dict[str, Any],
        mock_logger: MagicMock,
    ) -> None:
        """Test that reconciliation logs appropriate info."""
        mock_patch_obj = MagicMock()
        mock_patch_obj.status = {}
        await reconcile_mcpprompt(
            spec=sample_mcpprompt_spec,
            name="github-query-helper",
            namespace="default",
            logger=mock_logger,
            patch=mock_patch_obj,
        )

        mock_logger.info.assert_called()

    @pytest.mark.asyncio
    async def test_reconcile_extracts_template_variables(
        self,
        mock_logger: MagicMock,
    ) -> None:
        """Test that reconciliation correctly extracts variables from template."""
        spec = {
            "name": "multi-var",
            "template": "{{greeting}} {{name}}! How is {{city}} today?",
            "variables": [
                {"name": "greeting", "description": "Greeting"},
                {"name": "name", "description": "Name"},
                {"name": "city", "description": "City"},
            ],
        }
        mock_patch_obj = MagicMock()
        mock_patch_obj.status = {}

        await reconcile_mcpprompt(
            spec=spec,
            name="multi-var",
            namespace="default",
            logger=mock_logger,
            patch=mock_patch_obj,
        )

        assert mock_patch_obj.status["validated"] is True

    @pytest.mark.asyncio
    async def test_reconcile_no_variables_in_template(
        self,
        mock_logger: MagicMock,
    ) -> None:
        """Test that prompts without variables validate successfully."""
        spec = {
            "name": "no-vars",
            "template": "A simple prompt with no variables.",
            "variables": [],
        }
        mock_patch_obj = MagicMock()
        mock_patch_obj.status = {}

        await reconcile_mcpprompt(
            spec=spec,
            name="no-vars",
            namespace="default",
            logger=mock_logger,
            patch=mock_patch_obj,
        )

        assert mock_patch_obj.status["validated"] is True

    @pytest.mark.asyncio
    async def test_reconcile_multiple_occurrences_same_variable(
        self,
        mock_logger: MagicMock,
    ) -> None:
        """Test that the same variable can appear multiple times in template."""
        spec = {
            "name": "repeat-var",
            "template": "Hello {{name}}! {{name}}, are you there?",
            "variables": [
                {"name": "name", "description": "User name"},
            ],
        }
        mock_patch_obj = MagicMock()
        mock_patch_obj.status = {}

        await reconcile_mcpprompt(
            spec=spec,
            name="repeat-var",
            namespace="default",
            logger=mock_logger,
            patch=mock_patch_obj,
        )

        assert mock_patch_obj.status["validated"] is True
