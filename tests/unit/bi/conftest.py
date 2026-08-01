from datetime import date, timedelta

import pytest
from django.utils import timezone

from apps.tasks.models import AnonymizedMetricsPayload, DailyMetricsSummary, HourlyMetricsCollection


@pytest.fixture
def collection_factory():
    def _create(**kwargs):
        defaults = {
            "collector_type": "unified_jobs",
            "collection_timestamp": timezone.now().replace(minute=5, second=0, microsecond=0),
            "raw_data": {"total_jobs": 42, "failed_jobs": 3},
            "status": "collected",
        }
        defaults.update(kwargs)
        return HourlyMetricsCollection.objects.create(**defaults)

    return _create


@pytest.fixture
def rollup_factory():
    def _create(**kwargs):
        defaults = {
            "summary_date": date.today() - timedelta(days=1),
            "status": "aggregated",
            "aggregated_metrics": {
                "unified_jobs": {"total": 100, "failed": 5},
                "credentials_service": {"total": 20},
            },
            "config_data": {"version": "4.5"},
            "hourly_collections_count": 24,
        }
        defaults.update(kwargs)
        return DailyMetricsSummary.objects.create(**defaults)

    return _create


@pytest.fixture
def payload_factory():
    def _create(**kwargs):
        defaults = {
            "summary_date": date.today() - timedelta(days=1),
            "status": "sent",
            "anonymized_data": {
                "statistics": {"host_count": 10},
                "summary_metadata": {"install_type": "containerized"},
            },
        }
        defaults.update(kwargs)
        return AnonymizedMetricsPayload.objects.create(**defaults)

    return _create
