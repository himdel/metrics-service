from datetime import date

from ansible_base.rbac.api.permissions import IsSystemAdminOrAuditor
from django.http import HttpResponse
from rest_framework import generics, status
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.bi.v1.renderers import CsvRenderer, json_to_csv
from apps.bi.v1.serializers import CollectionMetadataSerializer, PayloadMetadataSerializer, RollupMetadataSerializer
from apps.tasks.models import AnonymizedMetricsPayload, DailyMetricsSummary, HourlyMetricsCollection


class _BiListBase(generics.ListAPIView):
    permission_classes = [IsSystemAdminOrAuditor]
    filter_backends = []

    def _filter_by_status(self, qs):
        if val := self.request.query_params.get("status"):
            qs = qs.filter(status=val)
        return qs


class CollectionListView(_BiListBase):
    serializer_class = CollectionMetadataSerializer

    def get_queryset(self):
        qs = HourlyMetricsCollection.objects.all().order_by("-collection_timestamp")
        if val := self.request.query_params.get("date_from"):
            qs = qs.filter(collection_timestamp__date__gte=val)
        if val := self.request.query_params.get("date_to"):
            qs = qs.filter(collection_timestamp__date__lte=val)
        if val := self.request.query_params.get("data_type"):
            qs = qs.filter(collector_type=val)
        return self._filter_by_status(qs)


class RollupListView(_BiListBase):
    serializer_class = RollupMetadataSerializer

    def get_queryset(self):
        qs = DailyMetricsSummary.objects.all().order_by("-summary_date")
        if val := self.request.query_params.get("date_from"):
            qs = qs.filter(summary_date__gte=val)
        if val := self.request.query_params.get("date_to"):
            qs = qs.filter(summary_date__lte=val)
        return self._filter_by_status(qs)


class PayloadListView(_BiListBase):
    serializer_class = PayloadMetadataSerializer

    def get_queryset(self):
        qs = AnonymizedMetricsPayload.objects.all().order_by("-summary_date")
        if val := self.request.query_params.get("date_from"):
            qs = qs.filter(summary_date__gte=val)
        if val := self.request.query_params.get("date_to"):
            qs = qs.filter(summary_date__lte=val)
        return self._filter_by_status(qs)


def _parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def _data_response(request, data: dict | list, filename: str) -> HttpResponse | Response:
    fmt = request.query_params.get("format", "json")
    if fmt == "csv":
        csv_content = json_to_csv(data)
        resp = HttpResponse(csv_content, content_type="text/csv; charset=UTF-8")
        resp["Content-Disposition"] = f'attachment; filename="{filename}.csv"'
        return resp
    return Response(data)


class _BiDetailBase(APIView):
    permission_classes = [IsSystemAdminOrAuditor]
    renderer_classes = [JSONRenderer, CsvRenderer]


class CollectionDetailView(_BiDetailBase):
    def get(self, request, collector_type: str, date_filter: str):
        valid_types = [c[0] for c in HourlyMetricsCollection.COLLECTOR_TYPE_CHOICES]
        if collector_type not in valid_types:
            return Response(
                {"detail": f"Unknown collector_type '{collector_type}'. Valid: {valid_types}"},
                status=status.HTTP_404_NOT_FOUND,
            )

        qs = HourlyMetricsCollection.objects.filter(collector_type=collector_type)

        if "T" in date_filter:
            date_str, hour_str = date_filter.split("T", 1)
            d = _parse_date(date_str)
            if d is None:
                return Response({"detail": f"Invalid date: '{date_str}'"}, status=status.HTTP_400_BAD_REQUEST)
            try:
                hour = int(hour_str)
            except ValueError:
                return Response({"detail": f"Invalid hour: '{hour_str}'"}, status=status.HTTP_400_BAD_REQUEST)
            qs = qs.filter(collection_timestamp__date=d, collection_timestamp__hour=hour)
        else:
            d = _parse_date(date_filter)
            if d is None:
                return Response({"detail": f"Invalid date: '{date_filter}'"}, status=status.HTTP_400_BAD_REQUEST)
            qs = qs.filter(collection_timestamp__date=d)

        obj = qs.order_by("-collection_timestamp").first()
        if obj is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        return _data_response(request, obj.raw_data, f"collections_{collector_type}_{date_filter}")


class RollupDetailView(_BiDetailBase):
    def get(self, request, date: str):
        d = _parse_date(date)
        if d is None:
            return Response({"detail": f"Invalid date: '{date}'"}, status=status.HTTP_400_BAD_REQUEST)

        obj = DailyMetricsSummary.objects.filter(summary_date=d).first()
        if obj is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        data = obj.aggregated_metrics
        if data_type := request.query_params.get("data_type"):
            if data_type not in data:
                return Response(
                    {"detail": f"Unknown data_type '{data_type}'. Available: {list(data.keys())}"},
                    status=status.HTTP_404_NOT_FOUND,
                )
            data = data[data_type]

        return _data_response(request, data, f"rollups_{date}")


class PayloadDetailView(_BiDetailBase):
    def get(self, request, date: str):
        d = _parse_date(date)
        if d is None:
            return Response({"detail": f"Invalid date: '{date}'"}, status=status.HTTP_400_BAD_REQUEST)

        obj = AnonymizedMetricsPayload.objects.filter(summary_date=d).order_by("-created").first()
        if obj is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        data = obj.anonymized_data
        if data_type := request.query_params.get("data_type"):
            if data_type not in data:
                return Response(
                    {"detail": f"Unknown data_type '{data_type}'. Available: {list(data.keys())}"},
                    status=status.HTTP_404_NOT_FOUND,
                )
            data = data[data_type]

        return _data_response(request, data, f"payloads_{date}")
