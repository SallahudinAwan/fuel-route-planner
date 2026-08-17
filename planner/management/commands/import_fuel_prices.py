import csv
import hashlib
import io
import statistics
import unicodedata
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

import requests
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from planner.models import FuelStation, RoutePlanCache
from planner.services.openrouteservice import CONUS_STATES
from planner.services.stations import StationIndex


CENSUS_BATCH_URL = "https://geocoding.geo.census.gov/geocoder/locations/addressbatch"


def normalize_place(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    normalized = " ".join(
        "".join(character if character.isalnum() else " " for character in ascii_value.upper()).split()
    )
    expansions = {"FT ": "FORT ", "MT ": "MOUNT ", "ST ": "SAINT "}
    for prefix, replacement in expansions.items():
        if normalized.startswith(prefix):
            normalized = replacement + normalized[len(prefix) :]
            break
    return normalized


def aggregate_source_rows(source_path: Path):
    grouped = defaultdict(list)
    invalid_rows = 0
    with source_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {
            "OPIS Truckstop ID", "Truckstop Name", "Address", "City", "State",
            "Rack ID", "Retail Price",
        }
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise CommandError(f"Source CSV is missing columns: {sorted(required)}")
        for row in reader:
            state = row["State"].strip().upper()
            if state not in CONUS_STATES:
                continue
            try:
                station_id = int(row["OPIS Truckstop ID"])
                price = Decimal(row["Retail Price"].strip())
                if price <= 0:
                    raise InvalidOperation
            except (ValueError, InvalidOperation):
                invalid_rows += 1
                continue
            grouped[station_id].append((row, price))

    stations = []
    for station_id, records in grouped.items():
        first = records[0][0]
        median_price = statistics.median(record[1] for record in records)
        stations.append(
            {
                "opis_id": station_id,
                "name": first["Truckstop Name"].strip(),
                "address": first["Address"].strip(),
                "city": first["City"].strip(),
                "state": first["State"].strip().upper(),
                "rack_id": first["Rack ID"].strip(),
                "retail_price": median_price,
            }
        )
    return stations, invalid_rows


def census_geocode(stations, timeout=180):
    input_buffer = io.StringIO(newline="")
    writer = csv.writer(input_buffer, lineterminator="\n")
    for station in stations:
        writer.writerow(
            [
                station["opis_id"], station["address"], station["city"],
                station["state"], "",
            ]
        )
    files = {
        "addressFile": (
            "fuel-stations.csv", input_buffer.getvalue().encode("utf-8"), "text/csv"
        )
    }
    response = requests.post(
        CENSUS_BATCH_URL,
        data={"benchmark": "Public_AR_Current"},
        files=files,
        timeout=timeout,
        headers={"User-Agent": "fuel-route-assessment/1.0"},
    )
    response.raise_for_status()
    matches = {}
    for row in csv.reader(io.StringIO(response.text)):
        if len(row) < 9 or row[5].strip().lower() != "match":
            continue
        try:
            longitude, latitude = row[8].split(",", maxsplit=1)
            matches[int(row[0])] = (Decimal(latitude), Decimal(longitude))
        except (ValueError, InvalidOperation):
            continue
    return matches


def load_geonames(geonames_path: Path):
    places = {}
    with geonames_path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            fields = line.rstrip("\n").split("\t")
            if len(fields) < 15 or fields[6] != "P" or fields[8] != "US":
                continue
            state = fields[10].upper()
            if state not in CONUS_STATES:
                continue
            try:
                latitude = Decimal(fields[4])
                longitude = Decimal(fields[5])
                population = int(fields[14] or 0)
            except (InvalidOperation, ValueError):
                continue
            for name in {fields[1], fields[2]}:
                key = (normalize_place(name), state)
                existing = places.get(key)
                if existing is None or population > existing[2]:
                    places[key] = (latitude, longitude, population)
    return places


def read_enriched(source_path: Path):
    stations = []
    with source_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {
            "opis_id", "name", "address", "city", "state", "rack_id",
            "retail_price", "latitude", "longitude", "geocode_quality",
        }
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise CommandError(f"Enriched CSV is missing columns: {sorted(required)}")
        for row in reader:
            try:
                stations.append(
                    {
                        "opis_id": int(row["opis_id"]),
                        "name": row["name"],
                        "address": row["address"],
                        "city": row["city"],
                        "state": row["state"],
                        "rack_id": row["rack_id"],
                        "retail_price": Decimal(row["retail_price"]),
                        "latitude": Decimal(row["latitude"]),
                        "longitude": Decimal(row["longitude"]),
                        "geocode_quality": row["geocode_quality"],
                    }
                )
            except (ValueError, InvalidOperation) as exc:
                raise CommandError(f"Invalid enriched row for station {row.get('opis_id')}") from exc
    return stations


def write_enriched(path: Path, stations):
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "opis_id", "name", "address", "city", "state", "rack_id", "retail_price",
        "latitude", "longitude", "geocode_quality",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows({field: station[field] for field in fields} for station in stations)


class Command(BaseCommand):
    help = "Clean, enrich, and load the supplied fuel-price CSV."

    def add_arguments(self, parser):
        parser.add_argument("source_csv", type=Path)
        parser.add_argument("--enriched-input", action="store_true")
        parser.add_argument("--geonames-file", type=Path)
        parser.add_argument("--use-census", action="store_true")
        parser.add_argument("--output", type=Path)

    def handle(self, *args, **options):
        source_path = options["source_csv"].resolve()
        if not source_path.is_file():
            raise CommandError(f"CSV does not exist: {source_path}")
        data_version = hashlib.sha256(source_path.read_bytes()).hexdigest()

        if options["enriched_input"]:
            prepared = read_enriched(source_path)
            invalid_rows = 0
            exact_count = sum(s["geocode_quality"] == "exact" for s in prepared)
        else:
            prepared, invalid_rows = aggregate_source_rows(source_path)
            exact_matches = {}
            if options["use_census"]:
                self.stdout.write("Submitting one Census batch geocoding request...")
                try:
                    exact_matches = census_geocode(prepared)
                except requests.RequestException as exc:
                    raise CommandError(f"Census batch geocoding failed: {exc}") from exc
            geonames_file = options.get("geonames_file")
            places = load_geonames(geonames_file.resolve()) if geonames_file else {}
            enriched = []
            for station in prepared:
                coordinates = exact_matches.get(station["opis_id"])
                quality = "exact"
                if coordinates is None:
                    place = places.get(
                        (normalize_place(station["city"]), station["state"])
                    )
                    if place:
                        coordinates = place[:2]
                        quality = "city_centroid"
                if coordinates is None:
                    continue
                station.update(
                    {
                        "latitude": coordinates[0],
                        "longitude": coordinates[1],
                        "geocode_quality": quality,
                    }
                )
                enriched.append(station)
            prepared = enriched
            exact_count = len(exact_matches)

        if not prepared:
            raise CommandError(
                "No stations could be prepared. Supply --geonames-file, --use-census, "
                "or an --enriched-input file."
            )
        if options.get("output"):
            write_enriched(options["output"].resolve(), prepared)

        station_models = [
            FuelStation(
                opis_id=item["opis_id"],
                name=item["name"],
                address=item["address"],
                city=item["city"],
                state=item["state"],
                rack_id=item["rack_id"],
                retail_price=item["retail_price"],
                latitude=item["latitude"],
                longitude=item["longitude"],
                geocode_quality=item["geocode_quality"],
                data_version=data_version,
            )
            for item in prepared
        ]
        with transaction.atomic():
            FuelStation.objects.all().delete()
            FuelStation.objects.bulk_create(station_models, batch_size=500)
            RoutePlanCache.objects.all().delete()
        StationIndex.clear()

        city_count = sum(s["geocode_quality"] == "city_centroid" for s in prepared)
        self.stdout.write(
            self.style.SUCCESS(
                f"Loaded {len(prepared)} stations "
                f"({exact_count} exact, {city_count} city-centroid); "
                f"ignored {invalid_rows} invalid source rows. Data version: {data_version[:12]}"
            )
        )
