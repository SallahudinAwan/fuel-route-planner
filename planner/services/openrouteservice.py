from dataclasses import asdict, dataclass
from decimal import Decimal

import requests
from django.conf import settings

from planner.exceptions import (
    InvalidLocationError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from planner.models import GeocodeCache


CONUS_STATES = {
    "AL", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA",
    "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA",
    "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM",
    "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD",
    "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
}


@dataclass(frozen=True)
class ResolvedLocation:
    query: str
    display_name: str
    latitude: float
    longitude: float
    state: str
    country_code: str

    def to_dict(self) -> dict:
        return asdict(self)


def normalize_query(value: str) -> str:
    return " ".join(value.casefold().split())


class OpenRouteServiceClient:
    def __init__(self, *, session=None, api_key=None, timeout=None, base_url=None):
        self.api_key = settings.ORS_API_KEY if api_key is None else api_key
        self.timeout = settings.ORS_TIMEOUT_SECONDS if timeout is None else timeout
        self.base_url = (base_url or settings.ORS_BASE_URL).rstrip("/")
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "Authorization": self.api_key,
                "User-Agent": "fuel-route-assessment/1.0",
            }
        )

    def _require_api_key(self):
        if not self.api_key:
            raise ProviderUnavailableError(
                "ORS_API_KEY is not configured.", code="routing_provider_not_configured"
            )

    def geocode(self, query: str) -> ResolvedLocation:
        normalized = normalize_query(query)
        cached = GeocodeCache.objects.filter(normalized_query=normalized).first()
        if cached:
            return ResolvedLocation(
                query=query,
                display_name=cached.display_name,
                latitude=float(cached.latitude),
                longitude=float(cached.longitude),
                state=cached.state,
                country_code=cached.country_code,
            )

        self._require_api_key()
        payload = self._request(
            "GET",
            f"{self.base_url}/geocode/search",
            params={
                "text": query,
                "boundary.country": "USA",
                "size": 1,
            },
        )
        try:
            feature = payload["features"][0]
            properties = feature["properties"]
            longitude, latitude = feature["geometry"]["coordinates"][:2]
        except (KeyError, IndexError, TypeError, ValueError):
            raise InvalidLocationError(f"Could not resolve location: {query}")

        country_code = str(
            properties.get("country_a") or properties.get("country_code") or ""
        ).upper()
        state = str(properties.get("region_a") or "").upper()
        if country_code not in {"US", "USA"} or state not in CONUS_STATES:
            raise InvalidLocationError(
                f"Location must resolve to the contiguous United States: {query}",
                code="location_outside_contiguous_usa",
            )

        result = ResolvedLocation(
            query=query,
            display_name=str(properties.get("label") or query),
            latitude=float(latitude),
            longitude=float(longitude),
            state=state,
            country_code="USA",
        )
        GeocodeCache.objects.update_or_create(
            normalized_query=normalized,
            defaults={
                "display_name": result.display_name,
                "latitude": Decimal(str(result.latitude)),
                "longitude": Decimal(str(result.longitude)),
                "state": result.state,
                "country_code": result.country_code,
                "provider": "openrouteservice",
            },
        )
        return result

    def directions(self, start: ResolvedLocation, finish: ResolvedLocation) -> dict:
        self._require_api_key()
        payload = self._request(
            "POST",
            f"{self.base_url}/v2/directions/driving-car/geojson",
            headers={"Accept": "application/geo+json"},
            json={
                "coordinates": [
                    [start.longitude, start.latitude],
                    [finish.longitude, finish.latitude],
                ],
                "instructions": False,
            },
        )
        try:
            feature = payload["features"][0]
            geometry = feature["geometry"]
            summary = feature["properties"]["summary"]
            distance_meters = float(summary["distance"])
            duration_seconds = float(summary["duration"])
            if geometry.get("type") != "LineString" or not geometry.get("coordinates"):
                raise ValueError
        except (KeyError, IndexError, TypeError, ValueError):
            raise ProviderUnavailableError(
                "Routing provider returned an invalid route response.",
                code="invalid_routing_response",
            )

        return {
            "geometry": geometry,
            "bbox": payload.get("bbox"),
            "distance_meters": distance_meters,
            "duration_seconds": duration_seconds,
            "attribution": payload.get("metadata", {}).get(
                "attribution", "openrouteservice.org | OpenStreetMap contributors"
            ),
        }

    def _request(self, method: str, url: str, **kwargs) -> dict:
        try:
            response = self.session.request(method, url, timeout=self.timeout, **kwargs)
        except requests.Timeout as exc:
            raise ProviderTimeoutError("Routing provider timed out.") from exc
        except requests.RequestException as exc:
            raise ProviderUnavailableError("Routing provider is unavailable.") from exc

        if response.status_code == 429:
            raise ProviderUnavailableError(
                "Routing provider quota has been exceeded.", code="routing_provider_quota"
            )
        if response.status_code in {400, 404}:
            raise InvalidLocationError(
                "The routing provider could not create a route.", code="no_route"
            )
        if response.status_code == 406:
            raise ProviderUnavailableError(
                "Routing provider rejected the requested response format.",
                code="routing_provider_format_error",
            )
        if response.status_code >= 500:
            raise ProviderUnavailableError("Routing provider is unavailable.")
        if not response.ok:
            raise ProviderUnavailableError(
                "Routing provider rejected the request.", code="routing_provider_error"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise ProviderUnavailableError(
                "Routing provider returned invalid JSON.", code="invalid_routing_response"
            ) from exc
