from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.serializers import HealthResponseSerializer


class HealthView(APIView):
    """Lightweight liveness endpoint for local and container health checks."""

    authentication_classes: list = []
    permission_classes: list = []

    def get(self, request: Request) -> Response:
        payload = HealthResponseSerializer({"status": "ok"}).data
        return Response(payload)


class ApiRootView(APIView):
    """Small API landing response for the browser root URL."""

    authentication_classes: list = []
    permission_classes: list = []

    def get(self, request: Request) -> Response:
        return Response(
            {
                "service": "fuel-route-optimizer",
                "status": "ok",
                "health_url": "/api/v1/health/",
                "route_url": "/api/v1/routes/",
            }
        )
