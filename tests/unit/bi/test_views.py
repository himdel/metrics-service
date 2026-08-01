from datetime import date, timedelta

import pytest
from django.utils import timezone

from apps.tasks.models import HourlyMetricsCollection


@pytest.mark.django_db
class TestCollectionListView:
    url = "/api/v1/bi/collections/"

    def test_unauthenticated(self, api_client):
        resp = api_client.get(self.url)
        assert resp.status_code in (401, 403)

    def test_list_returns_metadata_only(self, authenticated_client, collection_factory):
        collection_factory()
        resp = authenticated_client.get(self.url)
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert len(results) == 1
        assert "collector_type" in results[0]
        assert "raw_data" not in results[0]

    def test_filter_by_data_type(self, authenticated_client, collection_factory):
        collection_factory(collector_type="unified_jobs")
        collection_factory(
            collector_type="credentials_service",
            collection_timestamp=timezone.now().replace(minute=15, second=0, microsecond=0),
        )
        resp = authenticated_client.get(self.url, {"data_type": "unified_jobs"})
        results = resp.json()["results"]
        assert len(results) == 1
        assert results[0]["collector_type"] == "unified_jobs"

    def test_filter_by_status(self, authenticated_client, collection_factory):
        collection_factory(status="collected")
        collection_factory(
            status="failed",
            collector_type="credentials_service",
            collection_timestamp=timezone.now().replace(minute=15, second=0, microsecond=0),
        )
        resp = authenticated_client.get(self.url, {"status": "collected"})
        results = resp.json()["results"]
        assert len(results) == 1

    def test_filter_by_date_range(self, authenticated_client, collection_factory):
        today = date.today()
        collection_factory(collection_timestamp=timezone.now())
        collection_factory(
            collector_type="credentials_service",
            collection_timestamp=timezone.now() - timedelta(days=5),
        )
        resp = authenticated_client.get(self.url, {"date_from": str(today - timedelta(days=1))})
        results = resp.json()["results"]
        assert len(results) == 1


@pytest.mark.django_db
class TestCollectionDetailView:
    def test_unauthenticated(self, api_client):
        resp = api_client.get("/api/v1/bi/collections/unified_jobs/2026-01-01/")
        assert resp.status_code in (401, 403)

    def test_by_date(self, authenticated_client, collection_factory):
        ts = timezone.now().replace(hour=1, minute=30, second=0, microsecond=0)
        collection_factory(
            collector_type="execution_environments",
            collection_timestamp=ts,
            raw_data={"ee_count": 5},
        )
        resp = authenticated_client.get(f"/api/v1/bi/collections/execution_environments/{ts.date()}/")
        assert resp.status_code == 200
        assert resp.json() == {"ee_count": 5}

    def test_by_date_and_hour(self, authenticated_client, collection_factory):
        ts = timezone.now().replace(hour=15, minute=5, second=0, microsecond=0)
        collection_factory(collection_timestamp=ts, raw_data={"jobs": 10})
        resp = authenticated_client.get(f"/api/v1/bi/collections/unified_jobs/{ts.date()}T15/")
        assert resp.status_code == 200
        assert resp.json() == {"jobs": 10}

    def test_not_found(self, authenticated_client):
        resp = authenticated_client.get("/api/v1/bi/collections/unified_jobs/2020-01-01/")
        assert resp.status_code == 404

    def test_invalid_collector_type(self, authenticated_client):
        resp = authenticated_client.get("/api/v1/bi/collections/nonexistent/2026-01-01/")
        assert resp.status_code == 404
        assert "Unknown collector_type" in resp.json()["detail"]

    def test_invalid_date(self, authenticated_client):
        resp = authenticated_client.get("/api/v1/bi/collections/unified_jobs/not-a-date/")
        assert resp.status_code == 400

    def test_csv_format(self, authenticated_client, collection_factory):
        ts = timezone.now().replace(hour=10, minute=5, second=0, microsecond=0)
        collection_factory(collection_timestamp=ts, raw_data={"jobs": 10, "hosts": 5})
        resp = authenticated_client.get(f"/api/v1/bi/collections/unified_jobs/{ts.date()}T10/", {"format": "csv"})
        assert resp.status_code == 200
        assert resp["Content-Type"] == "text/csv; charset=UTF-8"
        assert "attachment" in resp["Content-Disposition"]
        content = resp.content.decode()
        assert "jobs" in content
        assert "10" in content

    def test_returns_latest_when_multiple(self, authenticated_client, collection_factory):
        ts1 = timezone.now().replace(hour=10, minute=5, second=0, microsecond=0)
        ts2 = timezone.now().replace(hour=10, minute=20, second=0, microsecond=0)
        collection_factory(collection_timestamp=ts1, raw_data={"version": "old"})
        # Need a different unique key — same collector_type + different timestamp in same hour
        HourlyMetricsCollection.objects.create(
            collector_type="unified_jobs",
            collection_timestamp=ts2,
            raw_data={"version": "new"},
            status="collected",
        )
        resp = authenticated_client.get(f"/api/v1/bi/collections/unified_jobs/{ts1.date()}T10/")
        assert resp.json()["version"] == "new"


@pytest.mark.django_db
class TestRollupListView:
    url = "/api/v1/bi/rollups/"

    def test_unauthenticated(self, api_client):
        resp = api_client.get(self.url)
        assert resp.status_code in (401, 403)

    def test_list_returns_metadata_only(self, authenticated_client, rollup_factory):
        rollup_factory()
        resp = authenticated_client.get(self.url)
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert len(results) == 1
        assert "summary_date" in results[0]
        assert "aggregated_metrics" not in results[0]
        assert "config_data" not in results[0]

    def test_filter_by_date_range(self, authenticated_client, rollup_factory):
        rollup_factory(summary_date=date.today() - timedelta(days=1))
        rollup_factory(summary_date=date.today() - timedelta(days=10))
        resp = authenticated_client.get(self.url, {"date_from": str(date.today() - timedelta(days=3))})
        assert len(resp.json()["results"]) == 1


@pytest.mark.django_db
class TestRollupDetailView:
    def test_unauthenticated(self, api_client):
        resp = api_client.get("/api/v1/bi/rollups/2026-01-01/")
        assert resp.status_code in (401, 403)

    def test_returns_full_data(self, authenticated_client, rollup_factory):
        d = date.today() - timedelta(days=1)
        rollup_factory(summary_date=d)
        resp = authenticated_client.get(f"/api/v1/bi/rollups/{d}/")
        assert resp.status_code == 200
        data = resp.json()
        assert "unified_jobs" in data
        assert "credentials_service" in data

    def test_data_type_filter(self, authenticated_client, rollup_factory):
        d = date.today() - timedelta(days=1)
        rollup_factory(summary_date=d)
        resp = authenticated_client.get(f"/api/v1/bi/rollups/{d}/", {"data_type": "unified_jobs"})
        assert resp.status_code == 200
        assert resp.json() == {"total": 100, "failed": 5}

    def test_data_type_not_found(self, authenticated_client, rollup_factory):
        d = date.today() - timedelta(days=1)
        rollup_factory(summary_date=d)
        resp = authenticated_client.get(f"/api/v1/bi/rollups/{d}/", {"data_type": "nonexistent"})
        assert resp.status_code == 404
        assert "Available" in resp.json()["detail"]

    def test_not_found(self, authenticated_client):
        resp = authenticated_client.get("/api/v1/bi/rollups/2020-01-01/")
        assert resp.status_code == 404

    def test_csv_format(self, authenticated_client, rollup_factory):
        d = date.today() - timedelta(days=1)
        rollup_factory(summary_date=d)
        resp = authenticated_client.get(f"/api/v1/bi/rollups/{d}/", {"format": "csv", "data_type": "unified_jobs"})
        assert resp.status_code == 200
        assert resp["Content-Type"] == "text/csv; charset=UTF-8"


@pytest.mark.django_db
class TestPayloadListView:
    url = "/api/v1/bi/payloads/"

    def test_unauthenticated(self, api_client):
        resp = api_client.get(self.url)
        assert resp.status_code in (401, 403)

    def test_list_returns_metadata_only(self, authenticated_client, payload_factory):
        payload_factory()
        resp = authenticated_client.get(self.url)
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert len(results) == 1
        assert "summary_date" in results[0]
        assert "anonymized_data" not in results[0]


@pytest.mark.django_db
class TestPayloadDetailView:
    def test_returns_full_data(self, authenticated_client, payload_factory):
        d = date.today() - timedelta(days=1)
        payload_factory(summary_date=d)
        resp = authenticated_client.get(f"/api/v1/bi/payloads/{d}/")
        assert resp.status_code == 200
        data = resp.json()
        assert "statistics" in data
        assert "summary_metadata" in data

    def test_data_type_filter(self, authenticated_client, payload_factory):
        d = date.today() - timedelta(days=1)
        payload_factory(summary_date=d)
        resp = authenticated_client.get(f"/api/v1/bi/payloads/{d}/", {"data_type": "statistics"})
        assert resp.status_code == 200
        assert resp.json() == {"host_count": 10}

    def test_not_found(self, authenticated_client):
        resp = authenticated_client.get("/api/v1/bi/payloads/2020-01-01/")
        assert resp.status_code == 404
