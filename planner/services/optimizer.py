from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from planner.exceptions import RouteNotServiceableError
from planner.services.stations import StationCandidate


MPG = Decimal("10")
MAX_RANGE_MILES = Decimal("500")
PLANNING_RANGE_MILES = Decimal("480")
TANK_CAPACITY_GALLONS = MAX_RANGE_MILES / MPG
MONEY = Decimal("0.01")
GALLONS = Decimal("0.001")


@dataclass(frozen=True)
class FuelNode:
    route_mile: Decimal
    price: Decimal
    station: StationCandidate | None


def _select_path(candidates, route_distance: Decimal, initial_price: Decimal):
    usable = [
        candidate
        for candidate in candidates
        if Decimal("0.1") < Decimal(str(candidate.route_mile)) < route_distance
    ]
    current_mile = Decimal("0")
    current_price = initial_price
    selected = []

    while route_distance - current_mile > PLANNING_RANGE_MILES:
        reachable = [
            candidate
            for candidate in usable
            if current_mile < Decimal(str(candidate.route_mile))
            <= current_mile + PLANNING_RANGE_MILES
        ]
        if not reachable:
            raise RouteNotServiceableError(
                f"No fuel station is available within {PLANNING_RANGE_MILES} miles "
                f"after route mile {current_mile.quantize(Decimal('0.1'))}."
            )

        cheaper = [candidate for candidate in reachable if candidate.price < current_price]
        if cheaper:
            next_station = min(cheaper, key=lambda item: item.route_mile)
        else:
            progress_floor = current_mile + (PLANNING_RANGE_MILES / Decimal("2"))
            forward_half = [
                item
                for item in reachable
                if Decimal(str(item.route_mile)) >= progress_floor
            ]
            pool = forward_half or reachable
            next_station = min(pool, key=lambda item: (item.price, -item.route_mile))

        selected.append(next_station)
        current_mile = Decimal(str(next_station.route_mile))
        current_price = next_station.price
        usable = [
            item for item in usable if Decimal(str(item.route_mile)) > current_mile
        ]

    return selected


def optimize_fuel_plan(
    candidates: list[StationCandidate],
    initial_station: StationCandidate,
    route_distance_miles: float,
) -> dict:
    route_distance = Decimal(str(route_distance_miles))
    selected = _select_path(candidates, route_distance, initial_station.price)
    nodes = [FuelNode(Decimal("0"), initial_station.price, initial_station)]
    nodes.extend(
        FuelNode(Decimal(str(item.route_mile)), item.price, item)
        for item in selected
    )
    nodes.append(FuelNode(route_distance, Decimal("0"), None))

    fuel_on_board = Decimal("0")
    purchases = []
    for index, node in enumerate(nodes[:-1]):
        cheaper_target = None
        for future in nodes[index + 1 :]:
            distance = future.route_mile - node.route_mile
            if distance > PLANNING_RANGE_MILES:
                break
            if future.price < node.price:
                cheaper_target = future
                break

        if cheaper_target:
            desired_fuel = (cheaper_target.route_mile - node.route_mile) / MPG
        else:
            desired_fuel = TANK_CAPACITY_GALLONS

        gallons = max(Decimal("0"), desired_fuel - fuel_on_board)
        if gallons > Decimal("0.00001"):
            subtotal = gallons * node.price
            purchases.append(
                {
                    "node": node,
                    "gallons": gallons,
                    "subtotal": subtotal,
                }
            )

        departure_fuel = fuel_on_board + gallons
        next_node = nodes[index + 1]
        leg_gallons = (next_node.route_mile - node.route_mile) / MPG
        fuel_on_board = departure_fuel - leg_gallons
        if fuel_on_board < Decimal("-0.0001"):
            raise RouteNotServiceableError("The selected fuel plan exceeds vehicle range.")
        fuel_on_board = max(Decimal("0"), fuel_on_board)

    initial_purchase = purchases[0]
    en_route = []
    for purchase in purchases[1:]:
        station = purchase["node"].station
        fields = station.public_fields()
        fields.update(
            {
                "gallons_purchased": float(
                    purchase["gallons"].quantize(GALLONS, rounding=ROUND_HALF_UP)
                ),
                "subtotal_usd": float(
                    purchase["subtotal"].quantize(MONEY, rounding=ROUND_HALF_UP)
                ),
            }
        )
        en_route.append(fields)

    total_cost = sum((item["subtotal"] for item in purchases), Decimal("0"))
    total_gallons = route_distance / MPG
    initial_fields = initial_station.public_fields()
    initial_fields.update(
        {
            "distance_from_start_miles": initial_fields.pop(
                "estimated_distance_from_route_miles"
            ),
            "gallons_purchased": float(
                initial_purchase["gallons"].quantize(GALLONS, rounding=ROUND_HALF_UP)
            ),
            "subtotal_usd": float(
                initial_purchase["subtotal"].quantize(MONEY, rounding=ROUND_HALF_UP)
            ),
        }
    )

    return {
        "mpg": float(MPG),
        "maximum_range_miles": float(MAX_RANGE_MILES),
        "planning_range_miles": float(PLANNING_RANGE_MILES),
        "estimated_gallons_consumed": float(
            total_gallons.quantize(GALLONS, rounding=ROUND_HALF_UP)
        ),
        "total_cost_usd": float(total_cost.quantize(MONEY, rounding=ROUND_HALF_UP)),
        "initial_fill": initial_fields,
        "stops": en_route,
    }
