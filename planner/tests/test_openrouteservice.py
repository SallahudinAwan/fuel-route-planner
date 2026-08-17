from unittest.mock import Mock

import requests
from django.test import TestCase

from planner.exceptions import InvalidLocationError, ProviderTimeoutError
from planner.models import GeocodeCache
from planner.services.openrouteservice import OpenRouteServiceClient, ResolvedLocation


class OpenRouteServiceTests(TestCase):
    def test_geocode_is_saved_and_reused(self):
        response = Mock(ok=True, status_code=200)
        response.json.return_value = {
            "features": [
                {
                    "geometry": {"coordinates": [-87.6298, 41.8781]},
                    "properties": {
                        "label": "Chicago, IL, USA",
                        "country_a": "USA",
                        "region_a": "IL",
                    },
                }
            ]
        }
        session = Mock()
        session.headers = {}
        session.request.return_value = response
        client = OpenRouteServiceClient(session=session, api_key="test")

        first = client.geocode("Chicago, IL")
        second = client.geocode("  chicago,   il ")

        self.assertEqual(first.latitude, second.latitude)
        self.assertEqual(session.request.call_count, 1)
        self.assertEqual(GeocodeCache.objects.count(), 1)

    def test_rejects_non_contiguous_state(self):
        response = Mock(ok=True, status_code=200)
        response.json.return_value = {
            "features": [
                {
                    "geometry": {"coordinates": [-149.9, 61.2]},
                    "properties": {"label": "Anchorage", "country_a": "USA", "region_a": "AK"},
                }
            ]
        }
        session = Mock(headers={})
        session.request.return_value = response
        with self.assertRaises(InvalidLocationError):
            OpenRouteServiceClient(session=session, api_key="test").geocode("Anchorage")

    def test_timeout_has_gateway_timeout_error(self):
        session = Mock(headers={})
        session.request.side_effect = requests.Timeout()
        client = OpenRouteServiceClient(session=session, api_key="test")
        with self.assertRaises(ProviderTimeoutError):
            client.geocode("Chicago")

    def test_directions_requests_geojson_media_type(self):
        response = Mock(ok=True, status_code=200)
        response.json.return_value = {
            "type": "FeatureCollection",
            "bbox": [-100.0, 40.0, -90.0, 41.0],
            "features": [
                {
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[-100.0, 40.0], [-90.0, 41.0]],
                    },
                    "properties": {
                        "summary": {"distance": 1000, "duration": 100}
                    },
                }
            ],
        }
        session = Mock(headers={})
        session.request.return_value = response
        client = OpenRouteServiceClient(session=session, api_key="test")
        start = ResolvedLocation("start", "Start", 40.0, -100.0, "NE", "USA")
        finish = ResolvedLocation("finish", "Finish", 41.0, -90.0, "IA", "USA")

        client.directions(start, finish)

        _, _, kwargs = session.request.mock_calls[0]
        self.assertEqual(kwargs["headers"]["Accept"], "application/geo+json")
