"""Tests for the on-demand analytics collection task."""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from apps.analytics.models import AnalyticsPayload
from apps.analytics.tasks import collect_analytics_on_demand

pytestmark = [pytest.mark.unit, pytest.mark.django_db]

UNIFIED = "controller.unified_jobs_dashboard"


def _fake_collector(df):
    """Return a collector_func stand-in whose instance .gather() yields df."""
    instance = MagicMock()
    instance.gather.return_value = df
    return MagicMock(return_value=instance)


def test_on_demand_unknown_collector_errors():
    result = collect_analytics_on_demand(collector="nope.nope")
    assert result["status"] == "error"
    assert not AnalyticsPayload.objects.exists()


def test_on_demand_missing_collector_errors():
    result = collect_analytics_on_demand()
    assert result["status"] == "error"


@patch("apps.analytics.tasks.get_db_connection")
def test_on_demand_happy_path_persists(mock_db):
    df = pd.DataFrame([{"id": 1}])
    func = _fake_collector(df)
    with patch("apps.analytics.tasks._collector_func", return_value=func):
        result = collect_analytics_on_demand(
            collector=UNIFIED, since="2026-08-17T10:00:00Z", until="2026-08-17T11:00:00Z"
        )
    assert result["status"] == "success"
    row = AnalyticsPayload.objects.get(collector=UNIFIED)
    assert row.state == AnalyticsPayload.STATE_DONE
    assert row.payload == [{"id": 1}]
    # since/until are threaded through to the collector.
    _, kwargs = func.call_args
    assert kwargs["since"] is not None and kwargs["until"] is not None


@patch("apps.analytics.tasks.get_db_connection")
def test_on_demand_failure_marks_claim_failed(mock_db):
    since, until = "2026-08-17T10:00:00Z", "2026-08-17T11:00:00Z"
    # Pre-existing pending claim (as the endpoint would have created).
    from apps.analytics.v1.views import _parse_dt

    AnalyticsPayload.objects.create(
        collector=UNIFIED,
        since=_parse_dt(since),
        until=_parse_dt(until),
        state=AnalyticsPayload.STATE_PENDING,
    )
    boom = MagicMock()
    boom.return_value.gather.side_effect = RuntimeError("kaboom")
    with patch("apps.analytics.tasks._collector_func", return_value=boom):
        result = collect_analytics_on_demand(collector=UNIFIED, since=since, until=until)
    assert result["status"] == "error"
    row = AnalyticsPayload.objects.get(collector=UNIFIED)
    assert row.state == AnalyticsPayload.STATE_FAILED
    assert "kaboom" in row.error_message


@patch("apps.analytics.tasks.get_db_connection")
def test_on_demand_snapshot_no_window(mock_db):
    func = _fake_collector({"version": "9"})
    with patch("apps.analytics.tasks._collector_func", return_value=func):
        result = collect_analytics_on_demand(collector="controller.config")
    assert result["status"] == "success"
    # Snapshot collectors are called without since/until.
    _, kwargs = func.call_args
    assert "since" not in kwargs and "until" not in kwargs
    assert AnalyticsPayload.objects.get(collector="controller.config").payload == {"version": "9"}
