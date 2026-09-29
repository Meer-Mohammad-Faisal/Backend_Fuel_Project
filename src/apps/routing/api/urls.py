from django.urls import path

from apps.routing.api.views import RoutePlanView

urlpatterns = [
    path("", RoutePlanView.as_view(), name="route-plan"),
]
