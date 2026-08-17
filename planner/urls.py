from django.urls import path

from planner.views import HealthView, RoutePlanView


urlpatterns = [
    path("routes/plan/", RoutePlanView.as_view(), name="route-plan"),
    path("health/", HealthView.as_view(), name="health"),
]
