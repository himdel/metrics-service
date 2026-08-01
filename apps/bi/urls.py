from django.urls import include, path

app_name = "bi"

urlpatterns = [
    path("api/v1/bi/", include("apps.bi.v1.urls", namespace="v1")),
]
