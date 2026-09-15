# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_admin_observability_sql.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for admin observability SQL functions.

Tests SQL-based and Python-based computation paths for:
- Latency percentiles
- Time-series metrics
- Latency heatmap
"""

# Standard
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

# Third-Party
import pytest

# Local
from tests.utils.rbac_mocks import create_mock_user_context

# First-Party
from mcpgateway.admin import (
    _get_latency_heatmap_postgresql,
    _get_latency_heatmap_python,
    _get_latency_percentiles_postgresql,
    _get_latency_percentiles_python,
    _get_timeseries_metrics_postgresql,
    _get_timeseries_metrics_python,
)


class TestLatencyPercentilesPostgresql:
    """Tests for PostgreSQL latency percentiles computation."""

    def test_percentiles_no_results(self):
        """Test PostgreSQL percentiles returns empty when no data."""
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_db.execute.return_value = mock_result

        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=1)
        result = _get_latency_percentiles_postgresql(mock_db, cutoff_time, 5)

        assert result == {"timestamps": [], "p50": [], "p90": [], "p95": [], "p99": []}

    def test_percentiles_with_data(self):
        """Test PostgreSQL percentiles with mocked SQL results."""
        mock_db = MagicMock()

        # Mock the SQL result
        mock_row = MagicMock()
        mock_row.bucket = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
        mock_row.p50 = 50.0
        mock_row.p90 = 90.0
        mock_row.p95 = 95.0
        mock_row.p99 = 99.0

        mock_result = MagicMock()
        mock_result.fetchall.return_value = [mock_row]
        mock_db.execute.return_value = mock_result

        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=1)
        result = _get_latency_percentiles_postgresql(mock_db, cutoff_time, 5)

        assert len(result["timestamps"]) == 1
        assert result["p50"][0] == 50.0
        assert result["p90"][0] == 90.0
        assert result["p95"][0] == 95.0
        assert result["p99"][0] == 99.0


class TestLatencyPercentilesPython:
    """Tests for Python latency percentiles computation (SQLite fallback)."""

    def test_percentiles_no_results(self):
        """Test Python percentiles returns empty when no data."""
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []

        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=1)
        result = _get_latency_percentiles_python(mock_db, cutoff_time, 5)

        assert result == {"timestamps": [], "p50": [], "p90": [], "p95": [], "p99": []}

    def test_percentiles_with_data(self):
        """Test Python percentiles with mocked trace data."""
        mock_db = MagicMock()

        # Create mock traces
        mock_traces = []
        base_time = datetime.now(timezone.utc) - timedelta(minutes=30)
        for i in range(100):
            trace = MagicMock()
            trace.start_time = base_time
            trace.duration_ms = float(i + 1)  # 1 to 100
            mock_traces.append(trace)

        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = mock_traces

        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=1)
        result = _get_latency_percentiles_python(mock_db, cutoff_time, 60)

        assert len(result["timestamps"]) >= 1
        assert len(result["p50"]) >= 1
        assert len(result["p95"]) >= 1


class TestTimeseriesMetricsPostgresql:
    """Tests for PostgreSQL time-series metrics computation."""

    def test_timeseries_no_results(self):
        """Test PostgreSQL timeseries returns empty when no data."""
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_db.execute.return_value = mock_result

        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=1)
        result = _get_timeseries_metrics_postgresql(mock_db, cutoff_time, 5)

        assert result == {"timestamps": [], "request_count": [], "success_count": [], "error_count": [], "error_rate": []}

    def test_timeseries_with_data(self):
        """Test PostgreSQL timeseries with mocked SQL results."""
        mock_db = MagicMock()

        # Mock the SQL result
        mock_row = MagicMock()
        mock_row.bucket = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
        mock_row.total = 100
        mock_row.success = 90
        mock_row.error = 10

        mock_result = MagicMock()
        mock_result.fetchall.return_value = [mock_row]
        mock_db.execute.return_value = mock_result

        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=1)
        result = _get_timeseries_metrics_postgresql(mock_db, cutoff_time, 5)

        assert len(result["timestamps"]) == 1
        assert result["request_count"][0] == 100
        assert result["success_count"][0] == 90
        assert result["error_count"][0] == 10
        assert result["error_rate"][0] == 10.0


class TestTimeseriesMetricsPython:
    """Tests for Python time-series metrics computation (SQLite fallback)."""

    def test_timeseries_no_results(self):
        """Test Python timeseries returns empty when no data."""
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []

        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=1)
        result = _get_timeseries_metrics_python(mock_db, cutoff_time, 5)

        assert result == {"timestamps": [], "request_count": [], "success_count": [], "error_count": [], "error_rate": []}

    def test_timeseries_with_data(self):
        """Test Python timeseries with mocked trace data."""
        mock_db = MagicMock()

        # Create mock traces
        mock_traces = []
        base_time = datetime.now(timezone.utc) - timedelta(minutes=30)
        for i in range(50):
            trace = MagicMock()
            trace.start_time = base_time
            trace.status = "ok" if i % 5 != 0 else "error"
            mock_traces.append(trace)

        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = mock_traces

        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=1)
        result = _get_timeseries_metrics_python(mock_db, cutoff_time, 60)

        assert len(result["timestamps"]) >= 1
        assert len(result["request_count"]) >= 1


class TestLatencyHeatmapPostgresql:
    """Tests for PostgreSQL latency heatmap computation."""

    def test_heatmap_no_results(self):
        """Test PostgreSQL heatmap returns empty when no data."""
        mock_db = MagicMock()

        # First call returns stats, second returns heatmap data
        mock_stats_row = MagicMock()
        mock_stats_row.min_d = None
        mock_stats_row.max_d = None

        mock_result = MagicMock()
        mock_result.fetchone.return_value = mock_stats_row
        mock_db.execute.return_value = mock_result

        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=1)
        result = _get_latency_heatmap_postgresql(mock_db, cutoff_time, hours=1, time_buckets=10, latency_buckets=5)

        assert result == {"time_labels": [], "latency_labels": [], "data": []}

    def test_heatmap_with_data(self):
        """Test PostgreSQL heatmap with mocked SQL results."""
        mock_db = MagicMock()

        # Mock stats query result
        mock_stats_row = MagicMock()
        mock_stats_row.min_d = 10.0
        mock_stats_row.max_d = 100.0

        # Mock heatmap query result
        mock_heatmap_row = MagicMock()
        mock_heatmap_row.time_idx = 0
        mock_heatmap_row.latency_idx = 2
        mock_heatmap_row.cnt = 5

        stats_result = MagicMock()
        stats_result.fetchone.return_value = mock_stats_row

        heatmap_result = MagicMock()
        heatmap_result.fetchall.return_value = [mock_heatmap_row]

        mock_db.execute.side_effect = [stats_result, heatmap_result]

        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=1)
        result = _get_latency_heatmap_postgresql(mock_db, cutoff_time, hours=1, time_buckets=10, latency_buckets=5)

        assert len(result["time_labels"]) == 10
        assert len(result["latency_labels"]) == 5
        assert len(result["data"]) == 5
        assert len(result["data"][0]) == 10
        # Check the populated cell
        assert result["data"][2][0] == 5


class TestLatencyHeatmapPython:
    """Tests for Python latency heatmap computation (SQLite fallback)."""

    def test_heatmap_no_results(self):
        """Test Python heatmap returns empty when no data."""
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []

        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=1)
        result = _get_latency_heatmap_python(mock_db, cutoff_time, hours=1, time_buckets=10, latency_buckets=5)

        assert result == {"time_labels": [], "latency_labels": [], "data": []}

    def test_heatmap_with_data(self):
        """Test Python heatmap with mocked trace data."""
        mock_db = MagicMock()

        # Create mock traces
        mock_traces = []
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=1)
        for i in range(20):
            trace = MagicMock()
            trace.start_time = cutoff_time + timedelta(minutes=i * 3)
            trace.duration_ms = 10.0 + i * 5  # 10 to 105
            mock_traces.append(trace)

        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = mock_traces

        result = _get_latency_heatmap_python(mock_db, cutoff_time, hours=1, time_buckets=10, latency_buckets=5)

        assert len(result["time_labels"]) == 10
        assert len(result["latency_labels"]) == 5
        assert len(result["data"]) == 5
        assert len(result["data"][0]) == 10
        # Check that some cells are populated
        total_count = sum(sum(row) for row in result["data"])
        assert total_count == 20

    def test_heatmap_single_duration(self):
        """Test Python heatmap handles single duration value (all same)."""
        mock_db = MagicMock()

        # Create mock traces with same duration
        mock_traces = []
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=1)
        for i in range(10):
            trace = MagicMock()
            trace.start_time = cutoff_time + timedelta(minutes=i * 6)
            trace.duration_ms = 50.0  # All same duration
            mock_traces.append(trace)

        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = mock_traces

        result = _get_latency_heatmap_python(mock_db, cutoff_time, hours=1, time_buckets=10, latency_buckets=5)

        assert len(result["time_labels"]) == 10
        assert len(result["latency_labels"]) == 5
        # All should fall in one latency bucket
        total_count = sum(sum(row) for row in result["data"])
        assert total_count == 10


class TestToolUsageStatistics:
    """Tests for tool usage statistics with different databases."""

    @pytest.mark.parametrize("dialect", ["postgresql", "sqlite"])
    def test_tool_usage_with_dialect(self, dialect):
        """Test tool usage works with PostgreSQL and SQLite."""
        mock_db = MagicMock()
        mock_bind = MagicMock()
        mock_bind.dialect.name = dialect
        mock_db.get_bind.return_value = mock_bind

        # Mock query chain
        mock_row = MagicMock()
        mock_row.tool_name = "test_tool"
        mock_row.count = 10

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.group_by.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = [mock_row]

        mock_db.query.return_value = mock_query

        # Import and call the function
        from mcpgateway.admin import get_tool_usage
        from fastapi import Request

        # Mock request and dependencies
        mock_request = MagicMock(spec=Request)
        mock_user = create_mock_user_context()
        mock_user["db"] = mock_db  # Use the same mock_db so dialect is consistent

        # This should not raise GroupingError
        with patch("mcpgateway.admin.get_db", return_value=iter([mock_db])):
            with patch("mcpgateway.admin.get_current_user_with_permissions", return_value=mock_user):
                import asyncio

                result = asyncio.run(get_tool_usage(mock_request, hours=24, limit=20, _user=mock_user))

        assert "tools" in result
        assert result["tools"][0]["tool_name"] == "test_tool"


class TestToolErrorStatistics:
    """Tests for tool error statistics with different databases."""

    @pytest.mark.parametrize("dialect", ["postgresql", "sqlite"])
    def test_tool_errors_with_dialect(self, dialect):
        """Test tool errors works with PostgreSQL and SQLite."""
        mock_db = MagicMock()
        mock_bind = MagicMock()
        mock_bind.dialect.name = dialect
        mock_db.get_bind.return_value = mock_bind

        # Mock query chain
        mock_row = MagicMock()
        mock_row.tool_name = "test_tool"
        mock_row.total_count = 100
        mock_row.error_count = 5

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.group_by.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = [mock_row]

        mock_db.query.return_value = mock_query

        from mcpgateway.admin import get_tool_errors
        from fastapi import Request

        mock_request = MagicMock(spec=Request)
        mock_user = create_mock_user_context()
        mock_user["db"] = mock_db  # Use the same mock_db so dialect is consistent

        with patch("mcpgateway.admin.get_db", return_value=iter([mock_db])):
            with patch("mcpgateway.admin.get_current_user_with_permissions", return_value=mock_user):
                import asyncio

                result = asyncio.run(get_tool_errors(mock_request, hours=24, limit=20, _user=mock_user))

        assert "tools" in result
        assert result["tools"][0]["tool_name"] == "test_tool"
        assert result["tools"][0]["error_rate"] == 5.0


class TestToolChains:
    """Tests for tool chain statistics."""

    @pytest.mark.parametrize("dialect", ["postgresql", "sqlite"])
    def test_tool_chains_with_dialect(self, dialect):
        """Test tool chains works with PostgreSQL and SQLite."""
        mock_db = MagicMock()
        mock_bind = MagicMock()
        mock_bind.dialect.name = dialect
        mock_db.get_bind.return_value = mock_bind

        # Mock query chain
        mock_span1 = MagicMock()
        mock_span1.trace_id = "trace1"
        mock_span1.tool_name = "tool_a"
        mock_span1.start_time = datetime.now(timezone.utc)

        mock_span2 = MagicMock()
        mock_span2.trace_id = "trace1"
        mock_span2.tool_name = "tool_b"
        mock_span2.start_time = datetime.now(timezone.utc) + timedelta(seconds=1)

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.all.return_value = [mock_span1, mock_span2]

        mock_db.query.return_value = mock_query

        from mcpgateway.admin import get_tool_chains
        from fastapi import Request

        mock_request = MagicMock(spec=Request)
        mock_user = create_mock_user_context()
        mock_user["db"] = mock_db  # Use the same mock_db so dialect is consistent

        with patch("mcpgateway.admin.get_db", return_value=iter([mock_db])):
            with patch("mcpgateway.admin.get_current_user_with_permissions", return_value=mock_user):
                import asyncio

                result = asyncio.run(get_tool_chains(mock_request, hours=24, limit=20, _user=mock_user))

        assert "chains" in result
        assert len(result["chains"]) > 0


class TestPromptStatistics:
    """Tests for prompt statistics with different databases."""

    @pytest.mark.parametrize("dialect", ["postgresql", "sqlite"])
    def test_prompt_usage_with_dialect(self, dialect):
        """Test prompt usage works with PostgreSQL and SQLite."""
        mock_db = MagicMock()
        mock_bind = MagicMock()
        mock_bind.dialect.name = dialect
        mock_db.get_bind.return_value = mock_bind

        # Mock query chain
        mock_row = MagicMock()
        mock_row.prompt_id = "test_prompt"
        mock_row.count = 15

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.group_by.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = [mock_row]

        mock_db.query.return_value = mock_query

        from mcpgateway.admin import get_prompt_usage
        from fastapi import Request

        mock_request = MagicMock(spec=Request)
        mock_user = create_mock_user_context()
        mock_user["db"] = mock_db  # Use the same mock_db so dialect is consistent

        with patch("mcpgateway.admin.get_db", return_value=iter([mock_db])):
            with patch("mcpgateway.admin.get_current_user_with_permissions", return_value=mock_user):
                import asyncio

                result = asyncio.run(get_prompt_usage(mock_request, hours=24, limit=20, _user=mock_user))

        assert "prompts" in result
        assert result["prompts"][0]["prompt_id"] == "test_prompt"

    @pytest.mark.parametrize("dialect", ["postgresql", "sqlite"])
    def test_prompt_errors_with_dialect(self, dialect):
        """Test prompt errors works with PostgreSQL and SQLite."""
        mock_db = MagicMock()
        mock_bind = MagicMock()
        mock_bind.dialect.name = dialect
        mock_db.get_bind.return_value = mock_bind

        # Mock query chain
        mock_row = MagicMock()
        mock_row.prompt_id = "test_prompt"
        mock_row.total_count = 50
        mock_row.error_count = 3

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.group_by.return_value = mock_query
        mock_query.all.return_value = [mock_row]

        mock_db.query.return_value = mock_query

        from mcpgateway.admin import get_prompts_errors
        from fastapi import Request

        mock_request = MagicMock(spec=Request)
        mock_user = create_mock_user_context()
        mock_user["db"] = mock_db  # Use the same mock_db so dialect is consistent

        with patch("mcpgateway.admin.get_db", return_value=iter([mock_db])):
            with patch("mcpgateway.admin.get_current_user_with_permissions", return_value=mock_user):
                import asyncio

                result = asyncio.run(get_prompts_errors(hours=24, limit=20, _user=mock_user))

        assert "prompts" in result


class TestResourceStatistics:
    """Tests for resource statistics with different databases."""

    @pytest.mark.parametrize("dialect", ["postgresql", "sqlite"])
    def test_resource_usage_with_dialect(self, dialect):
        """Test resource usage works with PostgreSQL and SQLite."""
        mock_db = MagicMock()
        mock_bind = MagicMock()
        mock_bind.dialect.name = dialect
        mock_db.get_bind.return_value = mock_bind

        # Mock query chain
        mock_row = MagicMock()
        mock_row.resource_uri = "file:///test.txt"
        mock_row.count = 20

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.group_by.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = [mock_row]

        mock_db.query.return_value = mock_query

        from mcpgateway.admin import get_resource_usage
        from fastapi import Request

        mock_request = MagicMock(spec=Request)
        mock_user = create_mock_user_context()
        mock_user["db"] = mock_db  # Use the same mock_db so dialect is consistent

        with patch("mcpgateway.admin.get_db", return_value=iter([mock_db])):
            with patch("mcpgateway.admin.get_current_user_with_permissions", return_value=mock_user):
                import asyncio

                result = asyncio.run(get_resource_usage(mock_request, hours=24, limit=20, _user=mock_user))

        assert "resources" in result
        assert result["resources"][0]["resource_uri"] == "file:///test.txt"

    @pytest.mark.parametrize("dialect", ["postgresql", "sqlite"])
    def test_resource_errors_with_dialect(self, dialect):
        """Test resource errors works with PostgreSQL and SQLite."""
        mock_db = MagicMock()
        mock_bind = MagicMock()
        mock_bind.dialect.name = dialect
        mock_db.get_bind.return_value = mock_bind

        # Mock query chain
        mock_row = MagicMock()
        mock_row.resource_uri = "file:///test.txt"
        mock_row.total_count = 30
        mock_row.error_count = 2

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.group_by.return_value = mock_query
        mock_query.all.return_value = [mock_row]

        mock_db.query.return_value = mock_query

        from mcpgateway.admin import get_resources_errors
        from fastapi import Request

        mock_request = MagicMock(spec=Request)
        mock_user = create_mock_user_context()
        mock_user["db"] = mock_db  # Use the same mock_db so dialect is consistent

        with patch("mcpgateway.admin.get_db", return_value=iter([mock_db])):
            with patch("mcpgateway.admin.get_current_user_with_permissions", return_value=mock_user):
                import asyncio

                result = asyncio.run(get_resources_errors(hours=24, limit=20, _user=mock_user))

        assert "resources" in result


@pytest.mark.asyncio
async def test_tool_usage_groups_shared_observation_records_by_catalog_name(test_engine, monkeypatch):
    """Real persisted catalog and direct-proxy spans feed the existing admin SQL aggregation."""
    # Standard
    import uuid

    # Third-Party
    from sqlalchemy import delete
    from sqlalchemy.orm import sessionmaker

    # First-Party
    from mcpgateway import admin
    from mcpgateway.db import ObservabilitySpan, ObservabilityTrace
    from mcpgateway.services import observability_service, tool_service

    session_factory = sessionmaker(bind=test_engine)
    monkeypatch.setattr(observability_service, "_get_or_create_observability_session", lambda: (session_factory(), True))
    monkeypatch.setattr(tool_service, "metrics_buffer", MagicMock())
    monkeypatch.setattr(tool_service.settings, "observability_enabled", True)
    service = observability_service.ObservabilityService()
    trace_id = service.start_trace("catalog aggregation fixture")
    trace_token = tool_service.current_trace_id.set(trace_id)
    parent_token = tool_service.current_span_id.set(None)
    canonical_name = "gateway-echo-" + uuid.uuid4().hex
    try:
        for mode in ("catalog", "direct_proxy"):
            state = tool_service.ToolService._start_tool_observation(None, None, {"tool.name": canonical_name, "tool.original_name": "echo", "tool.execution_mode": mode})
            tool_service.ToolService._finish_tool_observation(state, True, None)
        # This shares the name attribute but is not a tool invocation and must be excluded.
        service.start_span(trace_id, "mcp.client.request", attributes={"tool.name": canonical_name})
        query_db = session_factory()
        monkeypatch.setattr(admin, "get_db", lambda: iter([query_db]))
        result = await admin.get_tool_usage.__wrapped__(MagicMock(), hours=24, limit=1000, db=query_db)
        record = next(row for row in result["tools"] if row["tool_name"] == canonical_name)
        assert record["count"] == 2
        assert not any(row["tool_name"] == "echo" for row in result["tools"])
    finally:
        tool_service.current_span_id.reset(parent_token)
        tool_service.current_trace_id.reset(trace_token)
        with session_factory.begin() as db:
            db.execute(delete(ObservabilitySpan).where(ObservabilitySpan.trace_id == trace_id))
            db.execute(delete(ObservabilityTrace).where(ObservabilityTrace.trace_id == trace_id))


@pytest.mark.parametrize("span_status,outcome", [("ok", "Succeeded"), ("error", "Failed"), ("unset", "In progress")])
def test_trace_summary_separates_tool_outcome_from_http(span_status, outcome):
    """A successful HTTP request can contain a failed or unfinished tool invocation."""
    # Standard
    from types import SimpleNamespace

    # First-Party
    from mcpgateway.admin import _summarize_observability_traces

    trace = SimpleNamespace(trace_id="trace", attributes={"http.route": "/servers/server/mcp"}, http_url=None, http_status_code=200)
    span = SimpleNamespace(trace_id="trace", attributes={"tool.name": "catalog-echo", "tool.original_name": "echo", "tool.execution_mode": "direct_proxy"},
                           resource_name="catalog-echo", status=span_status, duration_ms=0, status_message="Bearer fixture-secret")
    db = MagicMock()
    span_query, server_query = MagicMock(), MagicMock()
    span_query.filter.return_value.order_by.return_value.all.return_value = [span]
    server_query.filter.return_value.all.return_value = [("server", "Discovery Studio")]
    db.query.side_effect = [span_query, server_query]
    summaries = _summarize_observability_traces(db, [trace])
    result = summaries["trace"]
    assert result["outcome"] == outcome
    assert result["servers"] == [{"id": "server", "name": "Discovery Studio"}]
    assert result["tools"][0]["original_name"] == "echo"
    assert "fixture-secret" not in result["tools"][0]["status_message"]
    assert result["tools"][0]["duration_ms"] == 0
    assert db.query.call_count == 2


def test_trace_summary_batches_page_and_handles_missing_context():
    """A full trace page uses one span query and no server query when no IDs were recorded."""
    # Standard
    from types import SimpleNamespace

    # First-Party
    from mcpgateway.admin import _summarize_observability_traces

    traces = [SimpleNamespace(trace_id=str(i), attributes={}, http_url="/mcp") for i in range(50)]
    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
    result = _summarize_observability_traces(db, traces)
    assert len(result) == 50
    assert all(row["outcome"] == "No recorded call" and not row["servers"] for row in result.values())
    db.query.assert_called_once()
    db.reset_mock()
    assert _summarize_observability_traces(db, []) == {}
    db.query.assert_not_called()


def test_trace_templates_escape_names_and_render_missing_timing():
    """Untrusted tool names stay text, missing identity stays unknown, and zero durations render."""
    # Standard
    import json
    from types import SimpleNamespace

    # Third-Party
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    env = Environment(loader=FileSystemLoader("mcpgateway/templates"), autoescape=select_autoescape())
    env.globals["csp_nonce"] = lambda _request: "fixture"
    attack = '</script><script>alert("name")</script>'
    now = datetime.now(timezone.utc)
    span = SimpleNamespace(span_id="span", name="tool.invoke", resource_name=attack, attributes={"tool.original_name": attack}, kind="client", status="unset",
                           start_time=now, end_time=None, duration_ms=None, parent_span_id=None, events=[])
    trace = SimpleNamespace(trace_id="trace", name="POST /mcp", http_method="POST", start_time=now, end_time=None, duration_ms=None, status="unset",
                            http_status_code=200, user_email=None, spans=[span], attributes={})
    summary = {"tools": [{"name": attack, "original_name": attack, "mode": "direct_proxy", "status": "unset", "duration_ms": None,
                           "failure_reason": None, "status_message": None}], "servers": [], "outcome": "In progress", "status": "unset"}
    for name in ("observability_traces_list.html", "observability_trace_detail.html"):
        html = env.get_template(name).render(request=None, trace=trace, traces=[trace], summary=summary, summaries={"trace": summary}, root_path="/gateway")
        assert attack not in html
        assert "Not recorded" in html
        assert "In progress" in html
        assert "anonymous" not in html or "does not imply anonymous access" in html
    trace.duration_ms = 0
    html = env.get_template("observability_traces_list.html").render(traces=[trace], summaries={"trace": summary}, root_path="/gateway")
    assert "0.00 ms" in html
    assert 'hx-get="/gateway/admin/observability/trace/trace"' in html

    # Completed child spans exercise the JavaScript chart payload, not only the cards.
    for parent_id in (None, "parent-span", attack):
        span.parent_span_id = parent_id
        html = env.get_template("observability_trace_detail.html").render(request=None, trace=trace, summary=summary)
        assert attack not in html
        script = html.split("<script", 1)[1].split(">", 1)[1].split("</script>", 1)[0]
        serialized_parent = script.split("parent_span_id: ", 1)[1].split(",", 1)[0]
        assert json.loads(serialized_parent) == parent_id


@pytest.mark.asyncio
async def test_trace_filter_uses_original_tool_name_and_utc_window(test_engine, monkeypatch):
    """Recent UTC traces stay visible on a non-UTC host when searching an upstream name."""
    # Standard
    import uuid

    # Third-Party
    from sqlalchemy import delete
    from sqlalchemy.orm import sessionmaker

    # First-Party
    from mcpgateway import admin
    from mcpgateway.db import ObservabilitySpan, ObservabilityTrace

    now = datetime.now(timezone.utc)

    class LocalClock(datetime):
        """Simulate a host ten hours ahead of the database's UTC timestamps."""

        @classmethod
        def now(cls, tz=None):
            """Return UTC only when the caller explicitly requests an aware timestamp."""
            return now.astimezone(tz) if tz else (now + timedelta(hours=10)).replace(tzinfo=None)

    session_factory = sessionmaker(bind=test_engine)
    trace_id = str(uuid.uuid4())
    with session_factory.begin() as db:
        db.add(ObservabilityTrace(trace_id=trace_id, name="POST /rpc", start_time=now - timedelta(minutes=5), status="ok", attributes={}))
        db.flush()
        db.add(ObservabilitySpan(trace_id=trace_id, name="tool.invoke", start_time=now, status="ok", attributes={"tool.name": "opaque-catalog-label", "tool.original_name": "my_tool"}))
    try:
        monkeypatch.setattr(admin, "datetime", LocalClock)
        monkeypatch.setattr(admin, "get_db", lambda: iter([session_factory()]))
        request = MagicMock()
        request.scope = {"root_path": ""}
        await admin.get_observability_traces.__wrapped__(request, time_range="1h", status_filter="all", limit=50, min_duration=None, max_duration=None,
            http_method=None, user_email=None, name_search=None, attribute_search=None, tool_name="my_tool", _user={})
        context = request.app.state.templates.TemplateResponse.call_args.args[2]
        assert trace_id in context["summaries"]
        assert context["summaries"][trace_id]["tools"][0]["name"] == "opaque-catalog-label"
    finally:
        with session_factory.begin() as db:
            db.execute(delete(ObservabilitySpan).where(ObservabilitySpan.trace_id == trace_id))
            db.execute(delete(ObservabilityTrace).where(ObservabilityTrace.trace_id == trace_id))
