from django.conf import settings
from django.db import connection
from django.views.generic import TemplateView
from rest_framework.response import Response
from rest_framework.views import APIView

from planner.exceptions import PlannerError
from planner.models import FuelStation
from planner.serializers import RoutePlanRequestSerializer
from planner.services.planner import create_route_plan


class RoutePlanView(APIView):
    authentication_classes = []

    def post(self, request):
        serializer = RoutePlanRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result, cache_hit = create_route_plan(**{
                "start_query": serializer.validated_data["start"],
                "finish_query": serializer.validated_data["finish"],
            })
        except PlannerError as exc:
            return Response(
                {"error": {"code": exc.code, "detail": exc.detail}},
                status=exc.status_code,
            )
        response = Response(result)
        response["X-Route-Cache"] = "HIT" if cache_hit else "MISS"
        return response


class HealthView(APIView):
    authentication_classes = []

    def get(self, request):
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        return Response(
            {
                "status": "ok",
                "stations_loaded": FuelStation.objects.count(),
                "routing_configured": bool(settings.ORS_API_KEY),
            }
        )


class DemoView(TemplateView):
    template_name = "planner/demo.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["map_tile_url"] = settings.MAP_TILE_URL
        return context
