from decimal import Decimal

from django.test import SimpleTestCase

from planner.exceptions import RouteNotServiceableError
from planner.services.optimizer import optimize_fuel_plan
from planner.services.stations import StationCandidate


def station(station_id, mile, price):
    return StationCandidate(
        opis_id=station_id,
        name=f"Station {station_id}",
        address="I-80",
        city="Test",
        state="NE",
        latitude=41.0,
        longitude=-100.0,
        price=Decimal(str(price)),
        geocode_quality="exact",
        route_mile=float(mile),
        distance_from_route_miles=1.0,
    )


class OptimizerTests(SimpleTestCase):
    def test_short_trip_charges_all_consumed_fuel(self):
        result = optimize_fuel_plan([], station(1, 0, "3.00"), 100)
        self.assertEqual(result["estimated_gallons_consumed"], 10.0)
        self.assertEqual(result["total_cost_usd"], 30.0)
        self.assertEqual(result["stops"], [])

    def test_long_trip_uses_multiple_price_aware_stops(self):
        result = optimize_fuel_plan(
            [station(2, 400, "4.00"), station(3, 800, "3.00")],
            station(1, 0, "3.50"),
            1000,
        )
        self.assertEqual(result["estimated_gallons_consumed"], 100.0)
        self.assertEqual([item["station_id"] for item in result["stops"]], [2, 3])
        self.assertEqual(result["total_cost_usd"], 355.0)

    def test_fails_when_no_station_is_inside_safe_range(self):
        with self.assertRaises(RouteNotServiceableError):
            optimize_fuel_plan([], station(1, 0, "3.00"), 481)

    def test_station_at_safe_range_boundary_is_reachable(self):
        result = optimize_fuel_plan(
            [station(2, 480, "3.10")], station(1, 0, "3.00"), 900
        )
        self.assertEqual(result["estimated_gallons_consumed"], 90.0)
        self.assertEqual(result["stops"][0]["station_id"], 2)
