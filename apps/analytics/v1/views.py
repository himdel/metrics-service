"""Analytics API views (ANSTRAT-1587 / AAP-87799).

Customer-facing BYO-BI surface over the stored raw collector payloads:

* ``GET  /api/v1/analytics/``                     — discovery: the enabled collectors.
* ``GET  /api/v1/analytics/<collector>/``         — the collector's raw payloads, ``since``/``until``
  window-overlap filtered and paginated (the primary BI read path).
* ``POST /api/v1/analytics/<collector>/collect/`` — out-of-band on-demand collection: stakes an
  atomic claim + enqueues a Task, returns ``202`` (NOT a BI path).

Auth/permissions mirror the tasks API (``IsSystemAdminOrAuditor``).

Window model
------------
Names are ``group.function`` (see the registry). Each collector has a *mode*:

* **hourly** / **daily** accept a since/until window; if the caller omits it, we default to the
  last finished hour / yesterday. ``until`` is exclusive throughout.
* **snapshot** collectors are current-state only — they reject since/until (400) and store a
  null window.

Read filtering is window *overlap*: a row is returned when its ``[since, until)`` overlaps the
query ``[since, until)``. Snapshot rows (null window) always match.

FOLLOWUPS (noted back in the anstrat-1587 plan):
* Per-collector generated viewsets + typed OpenAPI schemas (API issue 05/07). This session uses
  one generic viewset keyed on the collector path segment.
* Snapshot claims aren't DB-atomic (null window + NULL-distinct unique constraint); a
  ``period_bucket`` fixes that and adds snapshot history (API issue 06).
* ``since``/``until`` filter on the stored collection window, not on record-level timestamps
  inside the payload.
"""

from __future__ import annotations

import logging
from datetime import UTC, timedelta

from ansible_base.rbac.api.permissions import IsSystemAdminOrAuditor
from ansible_base.rest_pagination import DefaultPaginator
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.analytics.models import LOCAL_SOURCE, AnalyticsPayload
from apps.analytics.registry import ON_DEMAND_FUNCTION, enabled_collectors, get_entry
from apps.analytics.v1.serializers import AnalyticsPayloadSerializer

logger = logging.getLogger(__name__)

# How long a client should wait before polling the rows feed after an on-demand request.
# Matches the scheduler's 30s database-sync interval (worst-case pickup latency).
ON_DEMAND_RETRY_AFTER = 30

# A "done" row this fresh is treated as still-current: a repeat request within the window does
# NOT re-run the collector (the user just triggered / it just finished a few seconds ago).
FRESH_TTL = timedelta(seconds=60)

# A "pending" claim older than this is assumed dead (task never ran / crashed) and is re-claimed.
CLAIM_TTL = timedelta(minutes=10)

# Suggested polling / re-collection interval per mode, surfaced in the 202 response as a hint.
_SUGGESTED_INTERVAL_SECONDS = {"hourly": 3600, "daily": 86400}


def _parse_dt(value):
    """Parse an ISO datetime value from a query param / request body.

    Returns None when no value was given, the parsed datetime on success, or False when the
    value is present but malformed (so callers can distinguish "absent" from "invalid").
    """
    if not value:
        return None
    from django.utils.dateparse import parse_datetime

    try:
        parsed = parse_datetime(value)
    except (ValueError, TypeError):
        return False
    if parsed is None:
        return False
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, UTC)
    return parsed


def _default_window(mode, now):
    """Return the default (since, until) window for a collector mode.

    hourly -> the last finished hour; daily -> yesterday; snapshot -> (None, None).
    """
    if mode == "hourly":
        floor = now.replace(minute=0, second=0, microsecond=0)
        return floor - timedelta(hours=1), floor
    if mode == "daily":
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return midnight - timedelta(days=1), midnight
    return None, None


class AnalyticsRootView(APIView):
    """List the collectors the analytics API exposes (discovery entry point)."""

    permission_classes = [IsSystemAdminOrAuditor]

    def get(self, request, *args, **kwargs):
        """Return the enabled collectors and their rows/collect URLs."""
        base = request.build_absolute_uri(request.path).rstrip("/")
        collectors = [
            {
                "name": entry.name,
                "mode": entry.mode,
                "accepts_window": entry.accepts_window,
                "rows_url": f"{base}/{entry.name}/",
                "collect_url": f"{base}/{entry.name}/collect/",
            }
            for entry in enabled_collectors().values()
        ]
        return Response({"collectors": collectors})


class CollectorRowsView(generics.ListAPIView):
    """Return one collector's stored raw payloads, window-overlap filtered + paginated."""

    permission_classes = [IsSystemAdminOrAuditor]
    serializer_class = AnalyticsPayloadSerializer
    pagination_class = DefaultPaginator
    # Disable the DAB field-lookup/filter backends: they would treat ``since``/``until`` as
    # exact-match field lookups on the model and override our window-*overlap* semantics. We keep
    # DAB pagination but own the filtering here.
    filter_backends: list = []

    def get_queryset(self):
        """Filter completed payloads for the collector by since/until *window overlap*.

        A row matches when its stored ``[since, until)`` overlaps the query window (``until``
        exclusive). Snapshot rows have a null window and always match. Only ``done`` rows are
        served — pending/failed claims carry no usable payload.
        """
        collector = self.kwargs["collector"]
        qs = AnalyticsPayload.objects.filter(collector=collector, state=AnalyticsPayload.STATE_DONE)

        parsed_since = _parse_dt(self.request.query_params.get("since"))
        parsed_until = _parse_dt(self.request.query_params.get("until"))
        # Overlap: row.until > q_since AND row.since < q_until (null bounds = open-ended = match).
        if parsed_since:
            qs = qs.filter(Q(until__isnull=True) | Q(until__gt=parsed_since))
        if parsed_until:
            qs = qs.filter(Q(since__isnull=True) | Q(since__lt=parsed_until))
        return qs.order_by("-started_at")

    def list(self, request, *args, **kwargs):
        """Reject unknown/disabled collectors (404) and malformed since/until (400) up front."""
        entry = get_entry(self.kwargs["collector"])
        if entry is None or not entry.enabled:
            return Response(
                {"detail": f"Unknown or disabled collector: {self.kwargs['collector']}"},
                status=status.HTTP_404_NOT_FOUND,
            )
        for param in ("since", "until"):
            if _parse_dt(request.query_params.get(param)) is False:
                return Response(
                    {"detail": f"Invalid {param}: {request.query_params.get(param)}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        return super().list(request, *args, **kwargs)


class CollectorCollectView(APIView):
    """On-demand collection: stake an atomic claim + enqueue a Task, return 202.

    Out-of-band human/script action — NOT part of the BI read path. The claim is the payload row
    itself (unique on collector+source+since+until): concurrent requests can't double-run the same
    window, and a repeat request for a freshly-collected/in-progress window is a no-op re-poll.
    """

    permission_classes = [IsSystemAdminOrAuditor]

    def _resolve_window(self, entry, request):
        """Resolve (since, until) for a collect request, or a 400 Response on invalid input.

        Snapshot collectors reject any since/until. Windowed collectors accept both-or-neither;
        neither -> registry default window for the mode.
        """
        raw_since = request.data.get("since")
        raw_until = request.data.get("until")

        if not entry.accepts_window:
            if raw_since or raw_until:
                return None, Response(
                    {"detail": f"Collector {entry.name} is snapshot-only and does not accept since/until"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            return (None, None), None

        since = _parse_dt(raw_since)
        until = _parse_dt(raw_until)
        if since is False or until is False:
            return None, Response(
                {"detail": "Invalid since/until"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if (since is None) != (until is None):
            return None, Response(
                {"detail": "Provide both since and until, or neither (for the default window)"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if since is None:
            since, until = _default_window(entry.mode, timezone.now())
        elif until <= since:
            return None, Response(
                {"detail": "until must be after since"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return (since, until), None

    def post(self, request, *args, **kwargs):
        """Stake a claim for the (collector, window) and enqueue the on-demand task if needed.

        Returns 202 in all success cases with the claim ``state`` and a suggested re-collection
        interval. Repeat requests for an in-progress or freshly-completed window do NOT re-run the
        collector (they report the existing claim). Unknown/disabled collectors return 404.
        """
        collector = self.kwargs["collector"]
        entry = get_entry(collector)
        if entry is None or not entry.enabled:
            return Response(
                {"detail": f"Unknown or disabled collector: {collector}"},
                status=status.HTTP_404_NOT_FOUND,
            )

        window, error = self._resolve_window(entry, request)
        if error is not None:
            return error
        since, until = window
        source = request.data.get("source") or LOCAL_SOURCE

        now = timezone.now()
        with transaction.atomic():
            claim, created = AnalyticsPayload.objects.select_for_update().get_or_create(
                collector=collector,
                source=source,
                since=since,
                until=until,
                defaults={"state": AnalyticsPayload.STATE_PENDING, "claimed_at": now, "payload": {}},
            )
            should_enqueue, reason = self._claim_decision(claim, created, now)
            if should_enqueue:
                claim.state = AnalyticsPayload.STATE_PENDING
                claim.claimed_at = now
                claim.error_message = ""
                claim.save(update_fields=["state", "claimed_at", "error_message", "modified"])

        if should_enqueue:
            self._enqueue(collector, source, since, until, request)

        response = Response(
            {
                "detail": reason,
                "collector": collector,
                "state": claim.state,
                "since": since,
                "until": until,
                "suggested_interval_seconds": _SUGGESTED_INTERVAL_SECONDS.get(entry.mode),
                "poll_url": request.build_absolute_uri(request.path).rstrip("/").rsplit("/collect", 1)[0] + "/",
            },
            status=status.HTTP_202_ACCEPTED,
        )
        response["Retry-After"] = str(ON_DEMAND_RETRY_AFTER)
        return response

    @staticmethod
    def _claim_decision(claim, created, now):
        """Decide whether to (re)enqueue collection for an existing/new claim row.

        Returns (should_enqueue, human_reason). Treats a running claim and a just-finished ``done``
        row as still-active (no re-run); re-claims stale-pending, failed, and aged-out done rows.
        """
        if created:
            return True, "Collection queued"
        if claim.state == AnalyticsPayload.STATE_PENDING:
            if claim.claimed_at and (now - claim.claimed_at) > CLAIM_TTL:
                return True, "Stale claim reclaimed; collection re-queued"
            return False, "Collection already in progress"
        if claim.state == AnalyticsPayload.STATE_DONE:
            if claim.finished_at and (now - claim.finished_at) < FRESH_TTL:
                return False, "Recently collected; serving existing data"
            return True, "Refreshing stale data; collection queued"
        # failed (or any unexpected state) -> retry.
        return True, "Previous collection failed; collection re-queued"

    @staticmethod
    def _enqueue(collector, source, since, until, request):
        """Create the immediate on-demand Task row; the 30s scheduler sync dispatches it."""
        from apps.tasks.models import Task

        task_data = {"collector": collector, "source": source}
        if since is not None:
            task_data["since"] = since.isoformat()
        if until is not None:
            task_data["until"] = until.isoformat()

        window_suffix = since.isoformat() if since is not None else "snapshot"
        Task.objects.update_or_create(
            name=f"ondemand_analytics_{collector}_{source}_{window_suffix}",
            defaults={
                "description": f"On-demand analytics collection for {collector}",
                "function_name": ON_DEMAND_FUNCTION,
                "task_data": task_data,
                "is_system_task": False,
                "status": "pending",
                "scheduled_time": None,
                "created_by": request.user if request.user.is_authenticated else None,
            },
        )
