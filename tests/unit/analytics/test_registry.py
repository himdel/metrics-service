"""Tests for the analytics collector registry (the whitelist)."""

import pytest

from apps.analytics import registry


@pytest.mark.unit
def test_public_name_is_group_dot_function():
    entry = registry.get_entry("controller.unified_jobs_dashboard")
    assert entry is not None
    assert entry.name == "controller.unified_jobs_dashboard"
    assert entry.group == "controller"
    assert entry.mu_function == "unified_jobs_dashboard"
    # Internal metrics-service key differs from the public function name here.
    assert entry.collector_type == "unified_jobs"


@pytest.mark.unit
def test_enabled_collectors_are_all_enabled():
    enabled = registry.enabled_collectors()
    assert enabled, "expected at least one enabled collector"
    assert all(e.enabled for e in enabled.values())
    # Disabled/excluded collectors must not leak into the enabled set.
    assert "service.task_executions_service" not in enabled
    assert "controller.job_host_summary" not in enabled


@pytest.mark.unit
def test_accepts_window_by_mode():
    assert registry.get_entry("controller.unified_jobs_dashboard").accepts_window is True  # hourly
    assert registry.get_entry("controller.config").accepts_window is False  # snapshot


@pytest.mark.unit
def test_get_entry_by_type_maps_internal_key():
    entry = registry.get_entry_by_type("unified_jobs")
    assert entry is not None
    assert entry.name == "controller.unified_jobs_dashboard"
    assert registry.get_entry_by_type("does_not_exist") is None


@pytest.mark.unit
def test_is_enabled():
    assert registry.is_enabled("controller.config") is True
    assert registry.is_enabled("service.task_executions_service") is False
    assert registry.is_enabled("nope.nope") is False
