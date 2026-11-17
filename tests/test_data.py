import sys
import unittest
from pathlib import Path

# Allow running this file directly with ``python tests/test_data.py``.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as salon


class DataSchemaTest(unittest.TestCase):
    def test_required_csv_columns_are_exact(self):
        self.assertEqual(salon.HISTORY_FIELDS, ["record_id", "observation_date", "arrival_time", "service_type", "service_start_time", "service_end_time", "barber_id", "service_status"])
        self.assertEqual(salon.SERVICE_FIELDS, ["service_id", "service_name", "price", "duration_minutes", "active"])
        self.assertEqual(salon.BOOKING_FIELDS, ["booking_id", "customer_name", "service_type", "booking_date", "slot_start", "slot_end", "barber_id", "status"])

    def test_only_valid_completed_rows_count_in_estimates(self):
        # The checked-in observations provide a known baseline; changing status in
        # a temporary application fixture is covered in test_app's queue lifecycle.
        stats = salon.historical_stats("Haircut")
        self.assertEqual(stats["sample_count"], 8)
        self.assertEqual(stats["median_duration_minutes"], 20)


if __name__ == "__main__":
    unittest.main()
