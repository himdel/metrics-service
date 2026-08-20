"""Serializers for the analytics API."""

from rest_framework import serializers

from apps.analytics.models import AnalyticsPayload


class AnalyticsPayloadSerializer(serializers.ModelSerializer):
    """Serialises a stored raw collector payload.

    FOLLOWUP: this returns the payload *envelope* (collector + window + the raw ``payload``
    blob). The plan's end state flattens ``payload`` into individual raw rows with a typed
    per-collector schema (API issue 05/07); that needs registry-generated per-collector
    serializers and is out of scope this session.
    """

    class Meta:
        model = AnalyticsPayload
        fields = ["id", "collector", "source", "since", "until", "state", "started_at", "finished_at", "payload"]
        read_only_fields = fields
