"""Tests for persisting raw collector output into AnalyticsPayload."""

from datetime import UTC, datetime

import pandas as pd
import pytest

from apps.analytics.models import AnalyticsPayload
from apps.analytics.persist import persist_analytics_payload

pytestmark = [pytest.mark.unit, pytest.mark.django_db]


def _times():
    started = datetime(2026, 8, 17, 10, 0, tzinfo=UTC)
    finished = datetime(2026, 8, 17, 10, 1, tzinfo=UTC)
    return started, finished


def test_persist_dataframe_stores_records():
    started, finished = _times()
    df = pd.DataFrame([{"id": 1, "name": "a"}, {"id": 2, "name": "b"}])

    persist_analytics_payload("unified_jobs", df, since=None, until=None, started_at=started, finished_at=finished)

    row = AnalyticsPayload.objects.get(collector="controller.unified_jobs_dashboard")
    assert row.payload == [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]
    assert row.state == AnalyticsPayload.STATE_DONE


def test_persist_dict_payload():
    started, finished = _times()
    persist_analytics_payload(
        "config", {"version": "1.2.3"}, since=None, until=None, started_at=started, finished_at=finished
    )
    row = AnalyticsPayload.objects.get(collector="controller.config")
    assert row.payload == {"version": "1.2.3"}


def test_persist_none_becomes_empty_dict():
    started, finished = _times()
    persist_analytics_payload("config", None, since=None, until=None, started_at=started, finished_at=finished)
    assert AnalyticsPayload.objects.get(collector="controller.config").payload == {}


def test_persist_disabled_collector_is_noop():
    started, finished = _times()
    persist_analytics_payload(
        "task_executions_service", {"x": 1}, since=None, until=None, started_at=started, finished_at=finished
    )
    assert not AnalyticsPayload.objects.exists()


def test_persist_unknown_collector_is_noop():
    started, finished = _times()
    persist_analytics_payload(
        "does_not_exist", {"x": 1}, since=None, until=None, started_at=started, finished_at=finished
    )
    assert not AnalyticsPayload.objects.exists()


def test_persist_is_idempotent_upsert():
    started, finished = _times()
    since = datetime(2026, 8, 17, 9, 0, tzinfo=UTC)
    until = datetime(2026, 8, 17, 10, 0, tzinfo=UTC)
    for payload in ({"v": 1}, {"v": 2}):
        persist_analytics_payload("config", payload, since=since, until=until, started_at=started, finished_at=finished)
    rows = AnalyticsPayload.objects.filter(collector="controller.config", since=since, until=until)
    assert rows.count() == 1
    assert rows.first().payload == {"v": 2}


def test_persist_flips_pending_claim_to_done():
    started, finished = _times()
    since = datetime(2026, 8, 17, 9, 0, tzinfo=UTC)
    until = datetime(2026, 8, 17, 10, 0, tzinfo=UTC)
    AnalyticsPayload.objects.create(
        collector="controller.config",
        since=since,
        until=until,
        state=AnalyticsPayload.STATE_PENDING,
        claimed_at=started,
    )
    persist_analytics_payload("config", {"v": 9}, since=since, until=until, started_at=started, finished_at=finished)
    row = AnalyticsPayload.objects.get(collector="controller.config", since=since, until=until)
    assert row.state == AnalyticsPayload.STATE_DONE
    assert row.claimed_at is None
    assert row.payload == {"v": 9}
