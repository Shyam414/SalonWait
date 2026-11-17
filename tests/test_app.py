import csv
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

# Allow running this file directly with ``python tests/test_app.py``.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as salon


class SalonWaitTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old = (salon.DATA_DIR, salon.HISTORY, salon.SERVICES, salon.BOOKINGS)
        history_fixture = salon.HISTORY.read_bytes()
        salon.DATA_DIR = Path(self.temp.name)
        salon.HISTORY, salon.SERVICES, salon.BOOKINGS = (salon.DATA_DIR / n for n in ("data.csv", "services.csv", "bookings.csv"))
        salon.HISTORY.write_bytes(history_fixture)
        salon.ensure_files()
        self.client = salon.app.test_client()
        self.client.application.config.update(TESTING=True, SECRET_KEY="test")
        import os
        self.old_password = os.environ.get("SALONWAIT_ADMIN_PASSWORD")
        os.environ["SALONWAIT_ADMIN_PASSWORD"] = "test-password"

    def tearDown(self):
        import os
        if self.old_password is None: os.environ.pop("SALONWAIT_ADMIN_PASSWORD", None)
        else: os.environ["SALONWAIT_ADMIN_PASSWORD"] = self.old_password
        salon.DATA_DIR, salon.HISTORY, salon.SERVICES, salon.BOOKINGS = self.old
        self.temp.cleanup()

    def login(self):
        return self.client.post("/admin/login", json={"password": "test-password"})

    def test_home_and_services(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(len(self.client.get("/api/services").json), 4)

    def test_wait_unknown_and_valid_median(self):
        self.assertEqual(self.client.get("/api/wait?service=missing").status_code, 404)
        d = self.client.get("/api/wait?service=Haircut").json
        self.assertEqual(d["sample_count"], 8)
        self.assertEqual(d["median_duration_minutes"], 20)

    def test_slots_and_booking_barber_conflict(self):
        day = (date.today() + timedelta(days=2)).isoformat()
        first_slot = self.client.get(f"/api/slots?date={day}&service=Haircut").json["slots"][0]
        data = {"customer_name": "Ravi", "service_type": "Haircut", "booking_date": day, "slot_start": first_slot["start"], "barber_id": first_slot["barber_id"]}
        self.assertEqual(self.client.post("/api/bookings", json=data).status_code, 201)
        self.assertEqual(self.client.post("/api/bookings", json=data).status_code, 409)
        data["barber_id"] = "B2" if data["barber_id"] != "B2" else "B1"
        self.assertEqual(self.client.post("/api/bookings", json=data).status_code, 201)
        self.assertNotIn(first_slot["barber_id"], [s["barber_id"] for s in self.client.get(f"/api/slots?date={day}&service=Haircut").json["slots"] if s["start"] == first_slot["start"]])

    def test_auth_and_walkin_lifecycle(self):
        self.assertEqual(self.client.get("/api/admin/overview").status_code, 401)
        self.login()
        r = self.client.post("/api/admin/walkins", json={"service_type": "Haircut", "barber_id": "B1"})
        self.assertEqual(r.status_code, 201)
        rid = r.json["record_id"]
        self.assertEqual(self.client.post(f"/api/admin/queue/{rid}/start", json={}).status_code, 200)
        self.assertEqual(self.client.post(f"/api/admin/queue/{rid}/complete", json={}).status_code, 200)
        with salon.HISTORY.open(newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows[-1]), 8)
        self.assertEqual(rows[-1]["service_status"], "completed")

    def test_add_service_duplicate_rejected(self):
        self.login()
        payload = {"service_name": "Scalp Care", "price": 90, "duration_minutes": 15}
        self.assertEqual(self.client.post("/api/admin/services", json=payload).status_code, 201)
        self.assertEqual(self.client.post("/api/admin/services", json=payload).status_code, 409)

    def test_cancelled_booking_does_not_block_slot_and_invalid_booking_rejected(self):
        day = (date.today() + timedelta(days=3)).isoformat()
        slot = self.client.get(f"/api/slots?date={day}&service=Haircut").json["slots"][0]
        payload = {"customer_name": "Ravi", "service_type": "Haircut", "booking_date": day, "slot_start": slot["start"], "barber_id": slot["barber_id"]}
        self.assertEqual(self.client.post("/api/bookings", json={"service_type": "Haircut"}).status_code, 400)
        self.assertEqual(self.client.post("/api/bookings", json={**payload, "service_type": "Unknown"}).status_code, 400)
        result = self.client.post("/api/bookings", json=payload)
        self.assertEqual(result.status_code, 201)
        bookings = salon.read_csv(salon.BOOKINGS, salon.BOOKING_FIELDS)
        bookings[0]["status"] = "cancelled"
        salon.write_rows(salon.BOOKINGS, salon.BOOKING_FIELDS, bookings)
        self.assertTrue(any(s["start"] == slot["start"] and s["barber_id"] == slot["barber_id"] for s in self.client.get(f"/api/slots?date={day}&service=Haircut").json["slots"]))

    def test_startup_preserves_existing_historical_file(self):
        original = salon.HISTORY.read_bytes()
        salon.ensure_files()
        self.assertEqual(salon.HISTORY.read_bytes(), original)

    def test_cancel_walkin_preserves_other_fields(self):
        self.login()
        record = self.client.post("/api/admin/walkins", json={"service_type": "Beard Trim", "barber_id": "B2"}).json["record_id"]
        row_before = next(r for r in salon.read_csv(salon.HISTORY, salon.HISTORY_FIELDS) if r["record_id"] == record)
        self.client.post(f"/api/admin/queue/{record}/cancel", json={})
        row_after = next(r for r in salon.read_csv(salon.HISTORY, salon.HISTORY_FIELDS) if r["record_id"] == record)
        self.assertEqual(row_after["service_status"], "cancelled")
        self.assertEqual(row_after["arrival_time"], row_before["arrival_time"])


if __name__ == "__main__": unittest.main()
