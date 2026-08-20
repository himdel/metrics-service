"""Tests for the analytics API views (discovery, rows, on-demand collect)."""

from datetime import UTC, datetime, timedelta

import pytest
from django.utils import timezone

from apps.analytics.models import AnalyticsPayload
from apps.tasks.models import Task

pytestmark = [pytest.mark.unit, pytest.mark.django_db]

ROOT = "/api/v1/analytics/"
UNIFIED = "controller.unified_jobs_dashboard"  # hourly (windowed)
CONFIG = "controller.config"  # snapshot


def _done_row(collector, since, until, **kw):
    return AnalyticsPayload.objects.create(
        collector=collector,
        since=since,
        until=until,
        state=AnalyticsPayload.STATE_DONE,
        started_at=since or timezone.now(),
        finished_at=until or timezone.now(),
        **kw,
    )


# --- discovery ------------------------------------------------------------


def test_root_lists_enabled_collectors(authenticated_client):
    resp = authenticated_client.get(ROOT)
    assert resp.status_code == 200
    names = {c["name"] for c in resp.json()["collectors"]}
    assert UNIFIED in names
    assert CONFIG in names
    assert "service.task_executions_service" not in names


def test_root_requires_auth(api_client):
    assert api_client.get(ROOT).status_code in (401, 403)


# --- rows -----------------------------------------------------------------


def test_rows_unknown_collector_404(authenticated_client):
    assert authenticated_client.get(f"{ROOT}nope.nope/").status_code == 404


def test_rows_only_returns_done(authenticated_client):
    _done_row(UNIFIED, datetime(2026, 8, 17, 10, tzinfo=UTC), datetime(2026, 8, 17, 11, tzinfo=UTC))
    AnalyticsPayload.objects.create(
        collector=UNIFIED,
        since=datetime(2026, 8, 17, 11, tzinfo=UTC),
        until=datetime(2026, 8, 17, 12, tzinfo=UTC),
        state=AnalyticsPayload.STATE_PENDING,
        claimed_at=timezone.now(),
    )
    resp = authenticated_client.get(f"{ROOT}{UNIFIED}/")
    assert resp.status_code == 200
    assert resp.json()["count"] == 1


def test_rows_window_overlap_until_exclusive(authenticated_client):
    _done_row(UNIFIED, datetime(2026, 8, 17, 10, tzinfo=UTC), datetime(2026, 8, 17, 11, tzinfo=UTC))
    _done_row(UNIFIED, datetime(2026, 8, 17, 11, tzinfo=UTC), datetime(2026, 8, 17, 12, tzinfo=UTC))
    # Query [11:00, 12:00): the 10-11 row's until (11:00) is NOT > 11:00, so it's excluded.
    resp = authenticated_client.get(f"{ROOT}{UNIFIED}/?since=2026-08-17T11:00:00Z&until=2026-08-17T12:00:00Z")
    assert resp.status_code == 200
    windows = {(r["since"], r["until"]) for r in resp.json()["results"]}
    assert len(windows) == 1


def test_rows_snapshot_null_window_always_matches(authenticated_client):
    _done_row(CONFIG, None, None, payload={"v": 1})
    resp = authenticated_client.get(f"{ROOT}{CONFIG}/?since=2026-08-17T11:00:00Z&until=2026-08-17T12:00:00Z")
    assert resp.status_code == 200
    assert resp.json()["count"] == 1


def test_rows_invalid_since_400(authenticated_client):
    assert authenticated_client.get(f"{ROOT}{UNIFIED}/?since=notadate").status_code == 400


# --- on-demand collect ----------------------------------------------------


def test_collect_snapshot_rejects_window(authenticated_client):
    resp = authenticated_client.post(
        f"{ROOT}{CONFIG}/collect/", {"since": "2026-08-17T10:00:00Z", "until": "2026-08-17T11:00:00Z"}, format="json"
    )
    assert resp.status_code == 400


def test_collect_windowed_uses_default_window(authenticated_client):
    resp = authenticated_client.post(f"{ROOT}{UNIFIED}/collect/", {}, format="json")
    assert resp.status_code == 202
    body = resp.json()
    assert body["state"] == AnalyticsPayload.STATE_PENDING
    assert body["since"] is not None and body["until"] is not None
    assert body["suggested_interval_seconds"] == 3600
    # A claim row and a Task were created.
    assert AnalyticsPayload.objects.filter(collector=UNIFIED, state=AnalyticsPayload.STATE_PENDING).exists()
    assert Task.objects.filter(function_name="collect_analytics_on_demand").count() == 1


def test_collect_requires_both_or_neither(authenticated_client):
    resp = authenticated_client.post(f"{ROOT}{UNIFIED}/collect/", {"since": "2026-08-17T10:00:00Z"}, format="json")
    assert resp.status_code == 400


def test_collect_fresh_done_is_not_requeued(authenticated_client):
    since = datetime(2026, 8, 17, 10, tzinfo=UTC)
    until = datetime(2026, 8, 17, 11, tzinfo=UTC)
    row = _done_row(UNIFIED, since, until, payload={"v": 1})
    row.finished_at = timezone.now()  # just finished
    row.save(update_fields=["finished_at"])

    resp = authenticated_client.post(
        f"{ROOT}{UNIFIED}/collect/",
        {"since": since.isoformat(), "until": until.isoformat()},
        format="json",
    )
    assert resp.status_code == 202
    assert resp.json()["state"] == AnalyticsPayload.STATE_DONE
    assert not Task.objects.filter(function_name="collect_analytics_on_demand").exists()


def test_collect_stale_done_is_requeued(authenticated_client):
    since = datetime(2026, 8, 17, 10, tzinfo=UTC)
    until = datetime(2026, 8, 17, 11, tzinfo=UTC)
    row = _done_row(UNIFIED, since, until, payload={"v": 1})
    row.finished_at = timezone.now() - timedelta(hours=2)  # old
    row.save(update_fields=["finished_at"])

    resp = authenticated_client.post(
        f"{ROOT}{UNIFIED}/collect/",
        {"since": since.isoformat(), "until": until.isoformat()},
        format="json",
    )
    assert resp.status_code == 202
    assert resp.json()["state"] == AnalyticsPayload.STATE_PENDING
    assert Task.objects.filter(function_name="collect_analytics_on_demand").count() == 1


def test_collect_running_claim_not_requeued(authenticated_client):
    since = datetime(2026, 8, 17, 10, tzinfo=UTC)
    until = datetime(2026, 8, 17, 11, tzinfo=UTC)
    AnalyticsPayload.objects.create(
        collector=UNIFIED,
        since=since,
        until=until,
        state=AnalyticsPayload.STATE_PENDING,
        claimed_at=timezone.now(),
    )
    resp = authenticated_client.post(
        f"{ROOT}{UNIFIED}/collect/",
        {"since": since.isoformat(), "until": until.isoformat()},
        format="json",
    )
    assert resp.status_code == 202
    assert resp.json()["state"] == AnalyticsPayload.STATE_PENDING
    assert not Task.objects.filter(function_name="collect_analytics_on_demand").exists()


def test_collect_failed_claim_is_requeued(authenticated_client):
    since = datetime(2026, 8, 17, 10, tzinfo=UTC)
    until = datetime(2026, 8, 17, 11, tzinfo=UTC)
    AnalyticsPayload.objects.create(
        collector=UNIFIED,
        since=since,
        until=until,
        state=AnalyticsPayload.STATE_FAILED,
        error_message="boom",
    )
    resp = authenticated_client.post(
        f"{ROOT}{UNIFIED}/collect/",
        {"since": since.isoformat(), "until": until.isoformat()},
        format="json",
    )
    assert resp.status_code == 202
    assert resp.json()["state"] == AnalyticsPayload.STATE_PENDING
    assert Task.objects.filter(function_name="collect_analytics_on_demand").count() == 1


def test_collect_unknown_collector_404(authenticated_client):
    assert authenticated_client.post(f"{ROOT}nope.nope/collect/", {}, format="json").status_code == 404
