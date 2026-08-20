"""Analytics storage models (ANSTRAT-1587 / AAP-87799).

One shared table storing the raw, pre-``prepare()`` output of each collector's ``gather()``
call, so the analytics API can serve it to customer BI tools. Today ``generic_collect_metrics``
discards the raw ``gather()`` output and only persists the rollup in ``HourlyMetricsCollection``;
this table adds a separate, non-invasive raw copy (the rollup path is untouched).

Minimal first-session field set (see FOLLOWUPS below for what was deliberately deferred).
"""

import json
import logging

from django.db import models

# Reuse the same DAB base classes / fallbacks as the tasks app.
try:
    from ansible_base.activitystream.models import AuditableModel
    from ansible_base.lib.abstract_models import CommonModel
except ImportError:  # pragma: no cover - simple fallback for setups without DAB

    class CommonModel(models.Model):
        created = models.DateTimeField(auto_now_add=True)
        modified = models.DateTimeField(auto_now=True)

        class Meta:
            abstract = True

    class AuditableModel(models.Model):
        class Meta:
            abstract = True


logger = logging.getLogger(__name__)

# Default origin for a local install. Distinguishes multi-cluster origin later without a
# migration; a real value (install UUID / cluster id) is a FOLLOWUP once ingest is built.
LOCAL_SOURCE = "local"


class AnalyticsPayload(CommonModel, AuditableModel):
    """Raw pre-``prepare()`` collector payload for the analytics API.

    One row per (collector, source, collection window). The ``payload`` holds the
    JSON-serialisable form of the collector's ``gather()`` output — a list of record dicts for
    the DataFrame collectors, or a dict for the ``config`` snapshot collector.

    The row doubles as the **on-demand collection claim**: the on-demand endpoint atomically
    ``get_or_create``s a ``pending`` row on ``(collector, source, since, until)`` (the existing
    unique constraint) so concurrent requests can't double-run a window; the collection task then
    upserts the payload and flips ``state`` to ``done`` (or ``failed``).

    FOLLOWUPS (noted back in the anstrat-1587 plan — deliberately out of scope this session):
    * ``period_bucket`` — an explicit internal storage bucket. Snapshot collectors have a null
      window, so the unique constraint (NULLs are distinct in Postgres) can't make their claim
      DB-atomic and they keep only a single "latest" row (no history). A period_bucket fixes both.
    * ``extra_params`` — a slot for collector kwargs beyond since/until. Deferred because it
      raises serializable-vs-not questions; document per-collector params when added.
    * ``data_size_bytes`` / retention wiring (foundation issue 08 — add this table to cleanup
      at a 1-year policy; existing tables' retention untouched).
    """

    STATE_PENDING = "pending"
    STATE_DONE = "done"
    STATE_FAILED = "failed"
    STATE_CHOICES = [
        # NOTE: "pending" also covers a claim whose task is currently running — collection state
        # isn't tracked separately; the task flips straight to done/failed on completion.
        (STATE_PENDING, "Pending"),
        (STATE_DONE, "Done"),
        (STATE_FAILED, "Failed"),
    ]

    class Meta:
        app_label = "analytics"
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["collector", "since"]),
            models.Index(fields=["collector", "until"]),
            models.Index(fields=["collector", "started_at"]),
        ]
        # Idempotent upsert key for windowed (hourly/daily) collectors. NOTE: Postgres treats
        # NULLs as distinct, so this does NOT dedupe snapshot collectors (null since/until) at
        # the DB level — update_or_create handles those at the ORM layer for now. A proper
        # period_bucket-based unique claim is a FOLLOWUP (API issue 06).
        unique_together = ["collector", "source", "since", "until"]
        verbose_name = "Analytics Payload"
        verbose_name_plural = "Analytics Payloads"

    # Identification
    collector = models.CharField(max_length=100, help_text="Collector name (collector_type / API path segment)")

    source = models.CharField(
        max_length=255,
        default=LOCAL_SOURCE,
        help_text="Origin of the data; defaults to the local install. Distinguishes multi-cluster origin.",
    )

    # Collection window as passed to the collector. Both nullable — some collectors
    # (snapshots such as config) do not accept a since/until window.
    since = models.DateTimeField(null=True, blank=True, help_text="`since` passed to the collector (inclusive), if any")
    until = models.DateTimeField(null=True, blank=True, help_text="`until` passed to the collector (exclusive), if any")

    # When the gather() call ran. Both nullable: an on-demand claim is created as a "pending" row
    # before gather() runs (no times yet); the task fills them in when it flips the row to "done".
    started_at = models.DateTimeField(null=True, blank=True, help_text="When collection (gather) started")
    finished_at = models.DateTimeField(null=True, blank=True, help_text="When collection (gather) finished")

    # Data
    payload = models.JSONField(default=dict, help_text="Raw pre-prepare() gather() output, JSON-serialisable")

    # On-demand claim state. Scheduled collection writes rows straight as "done"; the on-demand
    # endpoint creates a "pending" claim that its task flips to done/failed.
    state = models.CharField(max_length=10, choices=STATE_CHOICES, default=STATE_DONE, help_text="Collection state")
    claimed_at = models.DateTimeField(
        null=True, blank=True, help_text="When an on-demand claim was staked (for stale-claim TTL)"
    )
    error_message = models.TextField(blank=True, default="", help_text="Error message if collection failed")

    def __str__(self) -> str:
        """Return a readable representation: collector + window (or 'snapshot')."""
        window = f"{self.since} → {self.until}" if self.since or self.until else "snapshot"
        return f"{self.collector} [{self.source}] ({window})"

    def save(self, *args, **kwargs):
        """Warn (but don't fail) if the payload isn't JSON-serialisable before hitting the DB."""
        try:
            json.dumps(self.payload)
        except TypeError:
            logger.warning("AnalyticsPayload.payload for %s is not JSON-serialisable", self.collector)
        super().save(*args, **kwargs)
