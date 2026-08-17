from dataclasses import dataclass
from decimal import Decimal
from threading import Lock

from pyproj import Transformer
from shapely.geometry import LineString, Point
from shapely.strtree import STRtree

from planner.exceptions import StationDataUnavailableError
from planner.models import FuelStation


METERS_PER_MILE = 1609.344
CORRIDOR_MILES = 10.0
ORIGIN_RADIUS_MILES = 50.0


@dataclass(frozen=True)
class StationCandidate:
    opis_id: int
    name: str
    address: str
    city: str
    state: str
    latitude: float
    longitude: float
    price: Decimal
    geocode_quality: str
    route_mile: float
    distance_from_route_miles: float

    def public_fields(self) -> dict:
        return {
            "station_id": self.opis_id,
            "name": self.name,
            "address": self.address,
            "city": self.city,
            "state": self.state,
            "latitude": round(self.latitude, 6),
            "longitude": round(self.longitude, 6),
            "price_per_gallon": f"{self.price:.3f}",
            "geocode_quality": self.geocode_quality,
            "route_mile": round(self.route_mile, 1),
            "estimated_distance_from_route_miles": round(
                self.distance_from_route_miles, 1
            ),
        }


class StationIndex:
    _instance = None
    _lock = Lock()

    def __init__(self, stations):
        self.transformer = Transformer.from_crs("EPSG:4326", "EPSG:5070", always_xy=True)
        self.stations = list(stations)
        if not self.stations:
            raise StationDataUnavailableError(
                "No fuel stations are loaded. Run import_fuel_prices first."
            )
        self.points = [
            Point(*self.transformer.transform(float(s.longitude), float(s.latitude)))
            for s in self.stations
        ]
        self.tree = STRtree(self.points)
        self.data_version = self.stations[0].data_version

    @classmethod
    def current(cls):
        version = (
            FuelStation.objects.order_by("opis_id")
            .values_list("data_version", flat=True)
            .first()
        )
        if not version:
            raise StationDataUnavailableError(
                "No fuel stations are loaded. Run import_fuel_prices first."
            )
        if cls._instance is None or cls._instance.data_version != version:
            with cls._lock:
                if cls._instance is None or cls._instance.data_version != version:
                    rows = list(FuelStation.objects.filter(data_version=version))
                    cls._instance = cls(rows)
        return cls._instance

    @classmethod
    def clear(cls):
        with cls._lock:
            cls._instance = None

    def candidates_for_route(self, coordinates, route_distance_miles: float):
        route_line = self._project_line(coordinates)
        indices = self.tree.query(
            route_line.buffer(CORRIDOR_MILES * METERS_PER_MILE),
            predicate="intersects",
        )
        scale = route_distance_miles / route_line.length if route_line.length else 0
        candidates = []
        for index in indices.tolist():
            station = self.stations[index]
            point = self.points[index]
            distance_miles = route_line.distance(point) / METERS_PER_MILE
            if distance_miles > CORRIDOR_MILES:
                continue
            route_mile = route_line.project(point) * scale
            candidates.append(
                StationCandidate(
                    opis_id=station.opis_id,
                    name=station.name,
                    address=station.address,
                    city=station.city,
                    state=station.state,
                    latitude=float(station.latitude),
                    longitude=float(station.longitude),
                    price=station.retail_price,
                    geocode_quality=station.geocode_quality,
                    route_mile=route_mile,
                    distance_from_route_miles=distance_miles,
                )
            )
        return sorted(candidates, key=lambda item: (item.route_mile, item.price))

    def nearest_to_origin(self, coordinate):
        origin = Point(*self.transformer.transform(float(coordinate[0]), float(coordinate[1])))
        indices = self.tree.query(
            origin.buffer(ORIGIN_RADIUS_MILES * METERS_PER_MILE),
            predicate="intersects",
        ).tolist()
        if not indices:
            return None
        nearest_index = min(
            indices,
            key=lambda index: (
                self.stations[index].retail_price,
                origin.distance(self.points[index]),
            ),
        )
        distance_miles = origin.distance(self.points[nearest_index]) / METERS_PER_MILE
        station = self.stations[nearest_index]
        return StationCandidate(
            opis_id=station.opis_id,
            name=station.name,
            address=station.address,
            city=station.city,
            state=station.state,
            latitude=float(station.latitude),
            longitude=float(station.longitude),
            price=station.retail_price,
            geocode_quality=station.geocode_quality,
            route_mile=0.0,
            distance_from_route_miles=distance_miles,
        )

    def _project_line(self, coordinates):
        return LineString(
            [self.transformer.transform(float(lon), float(lat)) for lon, lat in coordinates]
        )
