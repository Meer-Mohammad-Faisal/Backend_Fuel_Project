"""Project URL configuration."""

from django.contrib import admin
from django.urls import include, path

from apps.core.views import ApiRootView

urlpatterns = [
    path("", ApiRootView.as_view(), name="api-root"),
    path("admin/", admin.site.urls),
    path("api/v1/", include("apps.core.urls")),
    path("api/v1/routes/", include("apps.routing.api.urls")),
]
