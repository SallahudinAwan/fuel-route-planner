import hashlib
import json
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from planner.models import RoutePlanCache
from planner.services.openrouteservice import OpenRouteServiceClient
from planner.services.optimizer import optimize_fuel_plan
from planner.services.stations import StationIndex


ALGORITHM_VERSION = "price-aware-v1"
METERS_PER_MILE = 1609.344


def _cache_key(start, finish, data_version: str) -> str:
    value = {
        "algorithm": ALGORITHM_VERSION,
        "data_version": data_version,
        "start": [round(start.latitude, 6), round(start.longitude, 6)],
        "finish": [round(finish.latitude, 6), round(finish.longitude, 6)],
    }
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def create_route_plan(start_query: str, finish_query: str, *, client=None) -> tuple[dict, bool]:
    client = client or OpenRouteServiceClient()
    start = client.geocode(start_query)
    finish = client.geocode(finish_query)
    station_index = StationIndex.current()
    cache_key = _cache_key(start, finish, station_index.data_version)
    cached = RoutePlanCache.objects.filter(
        cache_key=cache_key, expires_at__gt=timezone.now()
    ).first()
    if cached:
        return cached.response, True

    route = client.directions(start, finish)
    route_distance_miles = route["distance_meters"] / METERS_PER_MILE
    coordinates = route["geometry"]["coordinates"]
    candidates = station_index.candidates_for_route(coordinates, route_distance_miles)
    initial_station = station_index.nearest_to_origin(coordinates[0])
    if initial_station is None:
        from planner.exceptions import RouteNotServiceableError

        raise RouteNotServiceableError(
            "No station in the supplied dataset is within 50 miles of the route origin."
        )
    fuel_plan = optimize_fuel_plan(candidates, initial_station, route_distance_miles)

    response = {
        "start": start.to_dict(),
        "finish": finish.to_dict(),
        "route": {
            "distance_miles": round(route_distance_miles, 1),
            "duration_hours": round(route["duration_seconds"] / 3600, 2),
            "bbox": route["bbox"],
            "geometry": route["geometry"],
        },
        "fuel": fuel_plan,
        "metadata": {
            "algorithm": ALGORITHM_VERSION,
            "station_data_version": station_index.data_version,
            "route_provider": "openrouteservice",
            "attribution": route["attribution"],
            "assumptions": [
                "Fuel cost covers route distance only; station detours are represented by a 20-mile range reserve.",
                "City-centroid station coordinates are approximate.",
            ],
        },
    }
    RoutePlanCache.objects.update_or_create(
        cache_key=cache_key,
        defaults={
            "response": response,
            "data_version": station_index.data_version,
            "expires_at": timezone.now()
            + timedelta(seconds=settings.ROUTE_CACHE_TTL_SECONDS),
        },
    )
    return response, False
