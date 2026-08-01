from django.urls import path

from apps.bi.v1.views import (
    CollectionDetailView,
    CollectionListView,
    PayloadDetailView,
    PayloadListView,
    RollupDetailView,
    RollupListView,
)

app_name = "bi"

urlpatterns = [
    path("collections/", CollectionListView.as_view(), name="collection-list"),
    path(
        "collections/<str:collector_type>/<str:date_filter>/",
        CollectionDetailView.as_view(),
        name="collection-detail",
    ),
    path("rollups/", RollupListView.as_view(), name="rollup-list"),
    path("rollups/<str:date>/", RollupDetailView.as_view(), name="rollup-detail"),
    path("payloads/", PayloadListView.as_view(), name="payload-list"),
    path("payloads/<str:date>/", PayloadDetailView.as_view(), name="payload-detail"),
]
