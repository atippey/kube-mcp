"""Unit tests for the metrics module."""

from unittest.mock import patch

from prometheus_client import REGISTRY

from src.utils.metrics import (
    MANAGED_RESOURCES,
    RECONCILIATION_DURATION,
    RECONCILIATION_TOTAL,
    start_metrics_server,
)


class TestMetricsDefinitions:
    """Tests that metric objects are properly defined."""

    def test_reconciliation_total_is_counter(self) -> None:
        assert RECONCILIATION_TOTAL._type == "counter"

    def test_reconciliation_total_labels(self) -> None:
        assert RECONCILIATION_TOTAL._labelnames == ("controller", "result")

    def test_reconciliation_duration_is_histogram(self) -> None:
        assert RECONCILIATION_DURATION._type == "histogram"

    def test_reconciliation_duration_labels(self) -> None:
        assert RECONCILIATION_DURATION._labelnames == ("controller",)

    def test_reconciliation_duration_buckets(self) -> None:
        expected = [0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, float("inf")]
        assert list(RECONCILIATION_DURATION._upper_bounds) == expected

    def test_managed_resources_is_gauge(self) -> None:
        assert MANAGED_RESOURCES._type == "gauge"

    def test_managed_resources_labels(self) -> None:
        assert MANAGED_RESOURCES._labelnames == ("kind",)


class TestMetricsIncrement:
    """Tests that metrics can be incremented without error."""

    def test_increment_reconciliation_total(self) -> None:
        RECONCILIATION_TOTAL.labels(controller="test", result="success").inc()
        value = REGISTRY.get_sample_value(
            "mcp_reconciliation_total",
            {"controller": "test", "result": "success"},
        )
        assert value is not None
        assert value >= 1

    def test_observe_reconciliation_duration(self) -> None:
        RECONCILIATION_DURATION.labels(controller="test").observe(0.5)
        value = REGISTRY.get_sample_value(
            "mcp_reconciliation_duration_seconds_count",
            {"controller": "test"},
        )
        assert value is not None
        assert value >= 1

    def test_set_managed_resources(self) -> None:
        MANAGED_RESOURCES.labels(kind="MCPServer").set(3)
        value = REGISTRY.get_sample_value(
            "mcp_managed_resources",
            {"kind": "MCPServer"},
        )
        assert value == 3


class TestStartMetricsServer:
    """Tests for the metrics server startup."""

    @patch("src.utils.metrics.start_http_server")
    def test_start_metrics_server_default_port(self, mock_start: object) -> None:
        start_metrics_server()
        from unittest.mock import MagicMock

        assert isinstance(mock_start, MagicMock)
        mock_start.assert_called_once_with(9090)

    @patch("src.utils.metrics.start_http_server")
    def test_start_metrics_server_custom_port(self, mock_start: object) -> None:
        start_metrics_server(port=8888)
        from unittest.mock import MagicMock

        assert isinstance(mock_start, MagicMock)
        mock_start.assert_called_once_with(8888)
