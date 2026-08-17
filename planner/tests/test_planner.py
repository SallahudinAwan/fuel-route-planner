from decimal import Decimal
from unittest.mock import Mock

from django.test import TestCase, override_settings

from planner.models import FuelStation, RoutePlanCache
from planner.services.openrouteservice import ResolvedLocation
from planner.services.planner import create_route_plan
from planner.services.stations import StationIndex


@override_settings(ROUTE_CACHE_TTL_SECONDS=3600)
class RoutePlannerTests(TestCase):
    def setUp(self):
        FuelStation.objects.bulk_create(
            [
                FuelStation(
                    opis_id=1, name="Origin Fuel", address="I-80", city="Start",
                    state="NE", rack_id="1", retail_price=Decimal("3.50"),
                    latitude=Decimal("40.0000"), longitude=Decimal("-100.0000"),
                    geocode_quality="exact", data_version="test-v1",
                ),
                FuelStation(
                    opis_id=2, name="Cheaper Fuel", address="I-80", city="Middle",
                    state="NE", rack_id="2", retail_price=Decimal("3.00"),
                    latitude=Decimal("40.0000"), longitude=Decimal("-96.0000"),
                    geocode_quality="exact", data_version="test-v1",
                ),
                FuelStation(
                    opis_id=3, name="Late Fuel", address="I-80", city="End",
                    state="NE", rack_id="3", retail_price=Decimal("3.25"),
                    latitude=Decimal("40.0000"), longitude=Decimal("-92.0000"),
                    geocode_quality="exact", data_version="test-v1",
                ),
            ]
        )
        StationIndex.clear()

    def tearDown(self):
        StationIndex.clear()

    def test_complete_plan_is_cached_before_second_directions_call(self):
        client = Mock()

        def geocode(query):
            if query == "Start, NE":
                return ResolvedLocation(query, "Start, NE, USA", 40.0, -100.0, "NE", "USA")
            return ResolvedLocation(query, "Finish, NE, USA", 40.0, -90.0, "NE", "USA")

        client.geocode.side_effect = geocode
        client.directions.return_value = {
            "geometry": {"type": "LineString", "coordinates": [[-100.0, 40.0], [-90.0, 40.0]]},
            "bbox": [-100.0, 40.0, -90.0, 40.0],
            "distance_meters": 700 * 1609.344,
            "duration_seconds": 36000,
            "attribution": "test attribution",
        }

        first, first_hit = create_route_plan("Start, NE", "Finish, NE", client=client)
        second, second_hit = create_route_plan("Start, NE", "Finish, NE", client=client)

        self.assertFalse(first_hit)
        self.assertTrue(second_hit)
        self.assertEqual(first, second)
        self.assertEqual(client.directions.call_count, 1)
        self.assertEqual(RoutePlanCache.objects.count(), 1)
        self.assertEqual(first["fuel"]["estimated_gallons_consumed"], 70.0)
        self.assertEqual(first["metadata"]["station_data_version"], "test-v1")
