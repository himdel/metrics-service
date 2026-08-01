from rest_framework import serializers

from apps.tasks.models import AnonymizedMetricsPayload, DailyMetricsSummary, HourlyMetricsCollection


class CollectionMetadataSerializer(serializers.ModelSerializer):
    class Meta:
        model = HourlyMetricsCollection
        fields = [
            "id",
            "collector_type",
            "collection_timestamp",
            "status",
            "data_size_bytes",
            "error_message",
            "created",
            "modified",
        ]


class RollupMetadataSerializer(serializers.ModelSerializer):
    class Meta:
        model = DailyMetricsSummary
        fields = [
            "id",
            "summary_date",
            "status",
            "hourly_collections_count",
            "missing_hours",
            "aggregation_completed_at",
            "error_message",
            "created",
            "modified",
        ]


class PayloadMetadataSerializer(serializers.ModelSerializer):
    class Meta:
        model = AnonymizedMetricsPayload
        fields = [
            "id",
            "summary_date",
            "status",
            "retry_count",
            "segment_event_name",
            "sent_at",
            "payload_size_bytes",
            "error_message",
            "created",
            "modified",
        ]
