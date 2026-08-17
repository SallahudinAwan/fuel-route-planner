# Fuel-Optimized Route API

A Django 6.1 REST API that plans a driving route within the contiguous United States, recommends price-aware truck-stop fuel purchases, estimates the trip's total fuel cost, and returns GeoJSON for map rendering.

The vehicle model is fixed at 10 MPG and a 500-mile physical range. Planning uses 480 miles, reserving 20 miles for station-coordinate and detour uncertainty.

## Architecture

- **openrouteservice:** two address geocodes and one `driving-car` directions request on the first request. Geocodes and complete plans are persisted in SQLite, so repeated requests make no provider calls.
- **Local station data:** the supplied CSV is deduplicated by OPIS ID, conflicting prices use their median, Canadian rows are removed, and coordinates are prepared before serving traffic.
- **Spatial selection:** Shapely and the continental U.S. Albers projection find stations within 10 miles of the returned route and order them by route distance.
- **Fuel strategy:** the planner buys enough to reach a cheaper station when one is safely reachable; otherwise it advances to a cost-effective station while retaining range feasibility.
- **Map demo:** `/` calls the API and renders the returned GeoJSON and stops with Leaflet.

## Quick start

Prerequisites: Python 3.12+ (3.13 recommended) and a free [openrouteservice API key](https://openrouteservice.org/dev/#/signup).

### uv (recommended)

```powershell
uv sync --python 3.13
Copy-Item .env.example .env
# Edit .env and set ORS_API_KEY.
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py import_fuel_prices .\data\fuel_stations_enriched.csv --enriched-input
.\.venv\Scripts\python.exe manage.py runserver
```

On Linux/macOS, use `.venv/bin/python` in place of `.venv\Scripts\python.exe`.

### pip

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py import_fuel_prices data/fuel_stations_enriched.csv --enriched-input
python manage.py runserver
```

Open `http://127.0.0.1:8000/` for the demo. Health information is available at `GET /api/v1/health/`.

## API

`POST /api/v1/routes/plan/`

```json
{
  "start": "Chicago, IL",
  "finish": "Los Angeles, CA"
}
```

Example request:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/routes/plan/ \
  -H "Content-Type: application/json" \
  -d '{"start":"Chicago, IL","finish":"Los Angeles, CA"}'
```

The response contains:

```json
{
  "start": {"display_name": "Chicago, IL, USA", "latitude": 41.88, "longitude": -87.63},
  "finish": {"display_name": "Los Angeles, CA, USA", "latitude": 34.05, "longitude": -118.24},
  "route": {
    "distance_miles": 2015.0,
    "duration_hours": 30.4,
    "bbox": [-118.24, 34.05, -87.63, 41.88],
    "geometry": {"type": "LineString", "coordinates": []}
  },
  "fuel": {
    "mpg": 10.0,
    "maximum_range_miles": 500.0,
    "planning_range_miles": 480.0,
    "estimated_gallons_consumed": 201.5,
    "total_cost_usd": 618.17,
    "initial_fill": {},
    "stops": []
  },
  "metadata": {
    "algorithm": "price-aware-v1",
    "route_provider": "openrouteservice",
    "attribution": "openrouteservice.org | OpenStreetMap contributors"
  }
}
```

The numbers above illustrate the response shape; live distance and cost depend on the provider route. `X-Route-Cache` is `MISS` for a newly calculated plan and `HIT` for a cached one.

Errors use a stable envelope:

```json
{"error": {"code": "route_not_serviceable", "detail": "..."}}
```

- `400`: invalid request JSON or fields.
- `422`: unresolved/non-CONUS endpoint, no route, or a station-coverage gap.
- `503`: station data missing, API key missing, provider failure, or provider quota.
- `504`: provider timeout.

## Fuel-data preparation

The checked-in `data/fuel_stations_enriched.csv` is the runtime-ready derivative of `fuel-prices-for-be-assessment.csv`:

- 8,151 source rows;
- 6,626 unique contiguous-U.S. OPIS station IDs after filtering/deduplication;
- 6,059 stations resolved and retained (91.4% coverage);
- all retained records currently use GeoNames city-centroid coordinates because the Census batch geocoder did not match the highway-exit-style addresses.

Runtime requests never geocode fuel stations. To regenerate the derivative, download and extract the free [GeoNames `cities500.zip`](https://download.geonames.org/export/dump/), then run:

```powershell
.\.venv\Scripts\python.exe manage.py import_fuel_prices `
  "C:\path\to\fuel-prices-for-be-assessment.csv" `
  --use-census `
  --geonames-file "C:\path\to\cities500.txt" `
  --output .\data\fuel_stations_enriched.csv
```

The command makes at most one U.S. Census batch request, falls back to GeoNames by normalized city/state, atomically replaces station records, clears stale plan caches, and reports exact/fallback/unresolved counts. GeoNames data is licensed under CC BY 4.0; U.S. Census data is public domain.

## Tests and checks

```powershell
.\.venv\Scripts\python.exe manage.py test --verbosity 2
.\.venv\Scripts\python.exe manage.py check
```

The suite covers import behavior, median prices, country filtering, geocoding cache and failures, range gaps, multi-stop optimization, cost accounting, API validation, response/cache headers, and the demo page. A local 6,059-station benchmark selected route candidates in approximately 4 ms; uncached API latency is dominated by openrouteservice.

## Operational assumptions

- Only the lower 48 states plus DC are accepted; the supplied data has no Alaska or Hawaii coverage.
- The initial tank is charged using the lowest-priced supplied station within 50 miles of the resolved origin.
- Total gallons are `primary route miles / 10`; estimated station detours are not added to cost because routing through every stop would exceed the provider-call budget.
- City-centroid station coordinates and straight-line corridor distances are estimates. The 20-mile reserve reduces, but cannot eliminate, that uncertainty.
- Public OpenStreetMap tiles are appropriate for this assessment demo, with visible attribution. Configure `MAP_TILE_URL` to use a production tile provider for sustained traffic.
