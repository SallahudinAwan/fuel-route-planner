import csv
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from planner.management.commands.import_fuel_prices import (
    aggregate_source_rows,
    load_geonames,
    normalize_place,
)


class ImportHelpersTests(SimpleTestCase):
    def test_aggregates_duplicates_with_median_and_filters_canada(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "fuel.csv"
            with source.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(
                    [
                        "OPIS Truckstop ID", "Truckstop Name", "Address", "City",
                        "State", "Rack ID", "Retail Price",
                    ]
                )
                writer.writerow([1, "One", "I-80", "Reno", "NV", 5, "3.10"])
                writer.writerow([1, "One renamed", "I-80", "Reno", "NV", 5, "3.50"])
                writer.writerow([1, "One", "I-80", "Reno", "NV", 5, "3.30"])
                writer.writerow([2, "Canada", "HWY 1", "Calgary", "AB", 6, "4.00"])
            stations, invalid = aggregate_source_rows(source)

        self.assertEqual(invalid, 0)
        self.assertEqual(len(stations), 1)
        self.assertEqual(stations[0]["name"], "One")
        self.assertEqual(str(stations[0]["retail_price"]), "3.30")

    def test_geonames_uses_highest_population_match(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "US.txt"
            fields_low = ["1", "St Louis", "St Louis", "", "38.1", "-90.1", "P", "PPL", "US", "", "MO", "", "", "", "100"]
            fields_high = ["2", "Saint Louis", "Saint Louis", "", "38.6", "-90.2", "P", "PPL", "US", "", "MO", "", "", "", "1000"]
            source.write_text("\t".join(fields_low) + "\n" + "\t".join(fields_high) + "\n", encoding="utf-8")
            places = load_geonames(source)

        self.assertEqual(normalize_place("St. Louis"), "SAINT LOUIS")
        self.assertEqual(str(places[("SAINT LOUIS", "MO")][0]), "38.6")
