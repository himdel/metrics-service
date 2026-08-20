"""Analytics collector registry — the whitelist of metrics-utility collectors.

Single source of truth for which collectors the analytics API exposes and which we may
safely call from the metrics service. Drives:

* **persistence** — only ``enabled`` collectors get their raw ``gather()`` output written
  to :class:`~apps.analytics.models.AnalyticsPayload` (see ``apps.analytics.persist``);
* **the read API** — ``/api/v1/analytics/<name>/`` only serves ``enabled`` collectors;
* **on-demand collection** — resolves the underlying collector + its default window.

Naming
------
The **public name** (API path + stored ``collector`` value) is ``group.function`` —  the
metrics-utility service group plus the real m-u collector function name, e.g.
``controller.unified_jobs_dashboard``. This is self-documenting and groups by service (room for
EDA/Hub later). Internally each entry also carries:

* ``collector_type`` — the metrics-service key that ``generic_collect_metrics`` and the
  ``_get_{hourly,snapshot,daily}_collectors()`` registries use (e.g. ``unified_jobs``);
* ``group`` / ``mu_function`` — the pieces the public name is built from.

Tiers
-----
* **ENABLED** — registered in the service, standalone-safe (read-only AWX DB, SQL only),
  customer-facing. Persisted + exposed.
* **DISABLED** — registered in the service but intentionally off for the API. Kept here so they
  can be enabled later without rework. Not persisted, not exposed.
* **EXCLUDED** — exist in metrics-utility but NOT registered in the service and unsafe to call
  standalone. Documentation only; never scheduled or exposed.

FOLLOWUPS (noted back in the anstrat-1587 plan):
* CI drift test comparing this registry vs the collectors discovered in the service — foundation 03.
* Registry-driven per-collector viewset/serializer/OpenAPI generation — API 05/07.
* SDP fields ``requires_functions`` / ``service_group`` / ``is_rollup`` — add when needed.
"""

from __future__ import annotations

from dataclasses import dataclass

# Maps a collector's scheduling "mode" to the metrics-service *scheduled* task function.
# (On-demand collection uses the dedicated ON_DEMAND_FUNCTION below, not these.)
MODE_FUNCTION: dict[str, str] = {
    "hourly": "collect_hourly_metrics",
    "snapshot": "collect_snapshot_metrics",
    "daily": "collect_daily_metrics",
}

# The single task function that runs any enabled collector on demand for an arbitrary window.
ON_DEMAND_FUNCTION = "collect_analytics_on_demand"

# Modes that accept a since/until collection window (snapshots are current-state only).
_WINDOWED_MODES = ("hourly", "daily")


@dataclass(frozen=True)
class CollectorEntry:
    """One collector in the analytics whitelist.

    Attributes:
        collector_type: metrics-service key (used by generic_collect_metrics and the
            ``_get_*_collectors()`` registries).
        group: metrics-utility service group (``controller`` / ``service`` / ``others`` / ...).
        mu_function: metrics-utility collector function name.
        mode: ``"hourly"`` / ``"snapshot"`` / ``"daily"`` (scheduling + window model); ``""`` for
            EXCLUDED collectors (never scheduled).
        enabled: whether the collector is persisted and exposed by the API.
        database: which Django DB connection the collector reads (defaults to ``awx``).
        default_window: on-demand default-window policy. ``None`` -> derive from ``mode``
            (finished hour / yesterday / now). Registry override point; unused for now.
        note: why a collector is disabled/excluded, or any relevant caveat.
    """

    collector_type: str
    group: str
    mu_function: str
    mode: str
    enabled: bool
    database: str = "awx"
    default_window: str | None = None
    note: str = ""

    @property
    def name(self) -> str:
        """Public API name / stored ``collector`` value (``group.function``)."""
        return f"{self.group}.{self.mu_function}"

    @property
    def accepts_window(self) -> bool:
        """Whether this collector accepts a since/until window (False for snapshots)."""
        return self.mode in _WINDOWED_MODES


# ---------------------------------------------------------------------------
# ENABLED — persisted + exposed. Registered in the service and standalone-safe.
# ---------------------------------------------------------------------------
_ENABLED: list[CollectorEntry] = [
    # Hourly (collect_hourly_metrics registry)
    CollectorEntry("unified_jobs", "controller", "unified_jobs_dashboard", "hourly", True),
    CollectorEntry("job_host_summary_service", "controller", "job_host_summary_service", "hourly", True),
    CollectorEntry("credentials_service", "controller", "credentials_service", "hourly", True),
    CollectorEntry("main_jobevent_service", "controller", "main_jobevent_service", "hourly", True),
    # Snapshot (collect_snapshot_metrics registry; current-state, no since/until window)
    CollectorEntry("execution_environments", "controller", "execution_environments", "snapshot", True),
    CollectorEntry("config", "controller", "config", "snapshot", True, note="already keeps raw (no rollup)"),
    CollectorEntry("controller_version_service", "controller", "controller_version_service", "snapshot", True),
    CollectorEntry("table_metadata", "controller", "table_metadata", "snapshot", True),
    CollectorEntry("feature_flags_service", "controller", "feature_flags_service", "snapshot", True),
]

# ---------------------------------------------------------------------------
# DISABLED — registered in the service, but intentionally off for the API.
# Kept here so they can be enabled later without rework.
# ---------------------------------------------------------------------------
_DISABLED: list[CollectorEntry] = [
    CollectorEntry(
        "task_executions_service",
        "service",
        "task_executions_service",
        "daily",
        False,
        database="default",
        note="reads the metrics-service own DB (tasks_taskexecution) — pipeline/observability, "
        "not customer data. Needs a product decision to expose ops data.",
    ),
    CollectorEntry(
        "indirect_managed_nodes",
        "controller",
        "main_indirectmanagednodeaudit",
        "daily",
        False,
        note="off by default (INDIRECT_NODE_COLLECTION feature). Opt-in indirect node audit; "
        "needs the ANSTRAT-2160 path to GA before exposing.",
    ),
]

# ---------------------------------------------------------------------------
# EXCLUDED — exist in metrics-utility but NOT registered in the service and unsafe to call
# standalone. Documentation only; never scheduled or exposed. (The record of *why* they're absent.)
# ---------------------------------------------------------------------------
_EXCLUDED: list[CollectorEntry] = [
    CollectorEntry(
        "job_host_summary",
        "controller",
        "job_host_summary",
        "",
        False,
        note="calls ensure_functions() (needs a writable DB); superseded by job_host_summary_service.",
    ),
    CollectorEntry(
        "main_host",
        "controller",
        "main_host",
        "",
        False,
        note="calls ensure_functions() / needs hostnames; not registered in the service.",
    ),
    CollectorEntry(
        "main_host_daily",
        "controller",
        "main_host_daily",
        "",
        False,
        note="hostname-keyed daily host metrics; needs ensure_functions()/hostnames; not registered.",
    ),
    CollectorEntry(
        "config_django",
        "controller",
        "config_django",
        "",
        False,
        note="imports awx.conf.license / awx.main.utils at runtime; superseded by config (SQL variant).",
    ),
    CollectorEntry(
        "total_workers_vcpu",
        "others",
        "total_workers_vcpu",
        "",
        False,
        note="Prometheus/CLI billing path only; not registered in the service.",
    ),
]

_ALL: tuple[CollectorEntry, ...] = (*_ENABLED, *_DISABLED, *_EXCLUDED)

# Public lookup by public name (group.function).
COLLECTORS: dict[str, CollectorEntry] = {e.name: e for e in _ALL}

# Reverse lookup by metrics-service collector_type — used by the persist hook, which only knows
# the internal key. Only enabled+disabled entries have meaningful collector_types here; excluded
# ones are never persisted so collisions among them don't matter.
_BY_TYPE: dict[str, CollectorEntry] = {e.collector_type: e for e in _ALL}


def enabled_collectors() -> dict[str, CollectorEntry]:
    """Return the collectors that are persisted and exposed by the API, keyed by public name."""
    return {name: e for name, e in COLLECTORS.items() if e.enabled}


def get_entry(name: str) -> CollectorEntry | None:
    """Return the registry entry for a public collector name, or None if unknown."""
    return COLLECTORS.get(name)


def get_entry_by_type(collector_type: str) -> CollectorEntry | None:
    """Return the registry entry for a metrics-service collector_type, or None if unknown."""
    return _BY_TYPE.get(collector_type)


def is_enabled(name: str) -> bool:
    """Whether a public collector name is enabled (persisted + exposed)."""
    entry = COLLECTORS.get(name)
    return bool(entry and entry.enabled)
