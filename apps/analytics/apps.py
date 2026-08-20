"""Analytics app configuration.

Customer-facing BYO-BI analytics API (ANSTRAT-1587 / AAP-87799). Exposes the raw
pre-``prepare()`` output of the metrics collectors so customers can point their own BI
tools at ``/api/v1/analytics/``. Kept separate from ``dashboard_reports``.
"""

from django.apps import AppConfig


class AnalyticsConfig(AppConfig):
    """Configuration for the analytics app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.analytics"
    verbose_name = "Analytics"
