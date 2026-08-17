from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from planner.exceptions import RouteNotServiceableError


class RoutePlanApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_validates_payload(self):
        response = self.client.post(reverse("route-plan"), {"start": "Same", "finish": "same"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "invalid_request")
        self.assertIn("finish", response.json()["error"]["fields"])

    def test_malformed_json_uses_error_envelope(self):
        response = self.client.post(
            reverse("route-plan"), data="{bad json", content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "invalid_request")

    @patch("planner.views.create_route_plan")
    def test_returns_plan_and_cache_header(self, create_plan):
        create_plan.return_value = (
            {
                "start": {"display_name": "Chicago"},
                "finish": {"display_name": "Los Angeles"},
                "route": {"geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]}},
                "fuel": {"total_cost_usd": 100.0, "stops": []},
                "metadata": {"attribution": "test"},
            },
            True,
        )
        response = self.client.post(
            reverse("route-plan"),
            {"start": "Chicago, IL", "finish": "Los Angeles, CA"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["X-Route-Cache"], "HIT")
        create_plan.assert_called_once_with(
            start_query="Chicago, IL", finish_query="Los Angeles, CA"
        )

    def test_demo_page_loads(self):
        response = self.client.get(reverse("demo"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Fuel Route Planner")
        self.assertContains(response, "leaflet@1.9.4")
        self.assertContains(response, "marker-bubble")

    @patch("planner.views.create_route_plan")
    def test_domain_error_uses_stable_envelope(self, create_plan):
        create_plan.side_effect = RouteNotServiceableError("No reachable station.")
        response = self.client.post(
            reverse("route-plan"),
            {"start": "Chicago, IL", "finish": "Los Angeles, CA"},
            format="json",
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "route_not_serviceable")
