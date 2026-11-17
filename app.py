"""SalonWait: CSV-backed salon bookings and walk-in queue."""
import csv
import os
import secrets
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import median
from functools import wraps

from flask import Flask, jsonify, redirect, render_template, request, session, url_for

BASE = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("SALONWAIT_DATA_DIR", BASE / "data"))
HISTORY = DATA_DIR / "data.csv"
SERVICES = DATA_DIR / "services.csv"
BOOKINGS = DATA_DIR / "bookings.csv"
HISTORY_FIELDS = ["record_id", "observation_date", "arrival_time", "service_type", "service_start_time", "service_end_time", "barber_id", "service_status"]
SERVICE_FIELDS = ["service_id", "service_name", "price", "duration_minutes", "active"]
BOOKING_FIELDS = ["booking_id", "customer_name", "service_type", "booking_date", "slot_start", "slot_end", "barber_id", "status"]
BARBERS = tuple(os.environ.get("SALONWAIT_BARBERS", "B1,B2,B3").split(","))
OPEN_TIME = os.environ.get("SALONWAIT_OPEN", "09:00")
CLOSE_TIME = os.environ.get("SALONWAIT_CLOSE", "21:00")
SLOT_INTERVAL = 30
write_lock = threading.RLock()
app = Flask(__name__)
app.secret_key = os.environ.get("SALONWAIT_SECRET_KEY") or secrets.token_hex(32)
app.config["JSON_SORT_KEYS"] = False


def ensure_files():
    """Create missing CSVs without replacing existing user files."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for path, fields in ((HISTORY, HISTORY_FIELDS), (SERVICES, SERVICE_FIELDS), (BOOKINGS, BOOKING_FIELDS)):
        if not path.exists():
            with path.open("w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(fields)
    try:
        with SERVICES.open(newline="", encoding="utf-8-sig") as f:
            header_only = next(csv.reader(f), []) == SERVICE_FIELDS and not next(csv.reader(f), [])
    except (OSError, csv.Error):
        header_only = False
    if header_only:
        with SERVICES.open("a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows([["1", "Haircut", "150", "20", "true"], ["2", "Beard Trim", "80", "10", "true"], ["3", "Haircut + Beard", "200", "30", "true"], ["4", "Head Massage", "100", "20", "true"]])


def read_csv(path, fields):
    ensure_files()
    try:
        with path.open(newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames or any(field not in reader.fieldnames for field in fields):
                return []
            return [{k: (v or "").strip() for k, v in row.items() if k is not None} for row in reader if row and any(row.values())]
    except (OSError, csv.Error):
        return []


def write_rows(path, fields, rows):
    with write_lock:
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)


def append_row(path, fields, row):
    ensure_files()
    with write_lock:
        with path.open("a", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=fields, extrasaction="ignore").writerow(row)


def parse_time(value):
    parsed = datetime.strptime(value, "%H:%M")
    if parsed.strftime("%H:%M") != value:
        raise ValueError("time must use HH:MM")
    return parsed


def service_by_name(name, active_only=True):
    return next((s for s in read_csv(SERVICES, SERVICE_FIELDS) if s["service_name"].casefold() == (name or "").strip().casefold() and (not active_only or s["active"].lower() == "true")), None)


def historical_stats(service_name):
    waits, durations = [], []
    for row in read_csv(HISTORY, HISTORY_FIELDS):
        if row.get("service_status", "").lower() != "completed" or row.get("service_type", "").casefold() != service_name.casefold():
            continue
        try:
            arrival, start, end = (parse_time(row[k]) for k in ("arrival_time", "service_start_time", "service_end_time"))
            wait, duration = int((start-arrival).total_seconds()/60), int((end-start).total_seconds()/60)
            if wait >= 0 and duration > 0:
                waits.append(wait); durations.append(duration)
        except (ValueError, TypeError):
            continue
    return {"service": service_name, "median_wait_minutes": median(waits) if waits else None,
            "median_duration_minutes": median(durations) if durations else None, "sample_count": len(waits), "low_sample": len(waits) < 5}


def intervals_overlap(start, end, other_start, other_end):
    return start < other_end and end > other_start


def barber_available(day, start, end, barber, exclude_id=None):
    for b in read_csv(BOOKINGS, BOOKING_FIELDS):
        if b.get("booking_date") != day or b.get("barber_id") != barber or b.get("status") != "confirmed" or b.get("booking_id") == exclude_id:
            continue
        try:
            if intervals_overlap(parse_time(start), parse_time(end), parse_time(b["slot_start"]), parse_time(b["slot_end"])): return False
        except ValueError: continue
    for row in read_csv(HISTORY, HISTORY_FIELDS):
        if row.get("observation_date") != day or row.get("barber_id") != barber or row.get("service_status") not in ("waiting", "in_service"): continue
        try:
            qstart = parse_time(row["service_start_time"]) if row["service_status"] == "in_service" else parse_time(row["arrival_time"])
            qend = parse_time(row["service_end_time"]) if row.get("service_end_time") else qstart + timedelta(minutes=30)
            if intervals_overlap(parse_time(start), parse_time(end), qstart, qend): return False
        except ValueError: continue
    return True


def available_slots(day, service):
    duration = int(service["duration_minutes"])
    opening, closing = parse_time(OPEN_TIME), parse_time(CLOSE_TIME)
    slots = []
    cursor = opening
    while cursor + timedelta(minutes=duration) <= closing:
        end = cursor + timedelta(minutes=duration)
        for barber in BARBERS:
            start_text, end_text = cursor.strftime("%H:%M"), end.strftime("%H:%M")
            is_future = day != date.today().isoformat() or cursor.time() > datetime.now().replace(second=0, microsecond=0).time()
            if is_future and barber_available(day, start_text, end_text, barber):
                slots.append({"start": start_text, "end": end_text, "barber_id": barber})
        cursor += timedelta(minutes=SLOT_INTERVAL)
    return slots


def owner_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get("owner"):
            return jsonify({"error": "Authentication required"}), 401
        return fn(*args, **kwargs)
    return wrapped


@app.get("/")
def home(): return render_template("index.html", opening=OPEN_TIME, closing=CLOSE_TIME)


@app.get("/api/services")
def api_services():
    return jsonify([{"service_id": s["service_id"], "service_name": s["service_name"], "price": float(s["price"]), "duration_minutes": int(s["duration_minutes"])} for s in read_csv(SERVICES, SERVICE_FIELDS) if s.get("active", "").lower() == "true" and s.get("price", "").strip() and s.get("duration_minutes", "").isdigit()])


@app.get("/api/wait")
def api_wait():
    name = request.args.get("service", "")
    if not service_by_name(name): return jsonify({"error": "Unknown or inactive service"}), 404
    return jsonify(historical_stats(name.strip()))


@app.get("/api/slots")
def api_slots():
    day_text, name = request.args.get("date", ""), request.args.get("service", "")
    try: day = date.fromisoformat(day_text)
    except ValueError: return jsonify({"error": "Date must be YYYY-MM-DD"}), 400
    if day.isoformat() != day_text: return jsonify({"error": "Date must be YYYY-MM-DD"}), 400
    service = service_by_name(name)
    if not service: return jsonify({"error": "Unknown or inactive service"}), 404
    if day < date.today(): return jsonify({"error": "Choose today or a future date"}), 400
    return jsonify({"date": day_text, "service": service["service_name"], "slots": available_slots(day_text, service)})


@app.post("/api/bookings")
def api_create_booking():
    data = request.get_json(silent=True) or {}
    customer = str(data.get("customer_name", "")).strip()
    name, day_text, start, barber = (str(data.get(k, "")).strip() for k in ("service_type", "booking_date", "slot_start", "barber_id"))
    service = service_by_name(name)
    if not customer or len(customer) > 80 or not service or barber not in BARBERS: return jsonify({"error": "Enter a customer name and choose a valid service and barber"}), 400
    try:
        day = date.fromisoformat(day_text); start_dt = parse_time(start)
    except ValueError: return jsonify({"error": "Invalid booking date or time"}), 400
    if day.isoformat() != day_text: return jsonify({"error": "Invalid booking date or time"}), 400
    end_dt = start_dt + timedelta(minutes=int(service["duration_minutes"]))
    with write_lock:
        if day < date.today() or (day == date.today() and start <= datetime.now().strftime("%H:%M")) or start_dt.strftime("%H:%M") < OPEN_TIME or end_dt.strftime("%H:%M") > CLOSE_TIME or not barber_available(day_text, start, end_dt.strftime("%H:%M"), barber):
            return jsonify({"error": "That slot is no longer available. Please choose another."}), 409
        booking_id = "BK" + secrets.token_hex(4).upper()
        append_row(BOOKINGS, BOOKING_FIELDS, {"booking_id": booking_id, "customer_name": customer, "service_type": service["service_name"], "booking_date": day_text, "slot_start": start, "slot_end": end_dt.strftime("%H:%M"), "barber_id": barber, "status": "confirmed"})
    return jsonify({"booking_id": booking_id, "service": service["service_name"], "date": day_text, "time": start, "price": float(service["price"])}), 201


@app.get("/admin/login")
def login_page(): return render_template("login.html")


@app.post("/admin/login")
def login():
    data = request.get_json(silent=True) or request.form
    password = os.environ.get("SALONWAIT_ADMIN_PASSWORD", "")
    if password and secrets.compare_digest(str(data.get("password", "")), password):
        session["owner"] = True
        return jsonify({"ok": True}) if request.is_json else redirect(url_for("admin_page"))
    if request.is_json:
        return jsonify({"error": "Incorrect password"}), 401
    return render_template("login.html", error="Incorrect password"), 401


@app.post("/admin/logout")
@owner_required
def logout(): session.clear(); return jsonify({"ok": True})


@app.get("/admin")
@owner_required
def admin_page(): return render_template("admin.html")


@app.get("/api/admin/overview")
@owner_required
def admin_overview():
    today = date.today().isoformat()
    history = read_csv(HISTORY, HISTORY_FIELDS)
    bookings = [b for b in read_csv(BOOKINGS, BOOKING_FIELDS) if b["booking_date"] == today]
    queue = [r for r in history if r["observation_date"] == today and r["service_status"] in ("waiting", "in_service")]
    return jsonify({"bookings": bookings, "queue": queue, "summary": {"bookings": len([b for b in bookings if b["status"] == "confirmed"]), "waiting": sum(r["service_status"] == "waiting" for r in queue), "in_service": sum(r["service_status"] == "in_service" for r in queue), "completed": sum(r["observation_date"] == today and r["service_status"] == "completed" for r in history)}, "services": read_csv(SERVICES, SERVICE_FIELDS), "barbers": BARBERS})


@app.post("/api/admin/services")
@owner_required
def admin_add_service():
    data = request.get_json(silent=True) or {}
    name = str(data.get("service_name", "")).strip()
    try:
        price, duration = float(data.get("price")), int(data.get("duration_minutes"))
        if not name or len(name) > 80 or price < 0 or duration <= 0: raise ValueError
    except (TypeError, ValueError): return jsonify({"error": "Provide a name, nonnegative price and positive duration"}), 400
    rows = read_csv(SERVICES, SERVICE_FIELDS)
    if any(s["service_name"].casefold() == name.casefold() for s in rows): return jsonify({"error": "A service with that name already exists"}), 409
    sid = str(max((int(s["service_id"]) for s in rows if s["service_id"].isdigit()), default=0) + 1)
    append_row(SERVICES, SERVICE_FIELDS, {"service_id": sid, "service_name": name, "price": f"{price:g}", "duration_minutes": str(duration), "active": "true"})
    return jsonify({"ok": True}), 201


@app.post("/api/admin/walkins")
@owner_required
def admin_walkin():
    data = request.get_json(silent=True) or {}
    name, barber = str(data.get("service_type", "")).strip(), str(data.get("barber_id", "")).strip()
    if not service_by_name(name) or barber not in BARBERS: return jsonify({"error": "Choose a valid service and barber"}), 400
    rid = "W" + secrets.token_hex(4).upper()
    append_row(HISTORY, HISTORY_FIELDS, {"record_id": rid, "observation_date": date.today().isoformat(), "arrival_time": datetime.now().strftime("%H:%M"), "service_type": name, "service_start_time": "", "service_end_time": "", "barber_id": barber, "service_status": "waiting"})
    return jsonify({"record_id": rid}), 201


@app.post("/api/admin/queue/<record_id>/<action>")
@owner_required
def admin_queue_action(record_id, action):
    if action not in ("start", "complete", "cancel"): return jsonify({"error": "Unknown action"}), 400
    rows = read_csv(HISTORY, HISTORY_FIELDS)
    row = next((r for r in rows if r["record_id"] == record_id), None)
    if not row: return jsonify({"error": "Queue record not found"}), 404
    if action == "start" and row["service_status"] == "waiting": row["service_status"], row["service_start_time"] = "in_service", datetime.now().strftime("%H:%M")
    elif action == "complete" and row["service_status"] == "in_service": row["service_status"], row["service_end_time"] = "completed", datetime.now().strftime("%H:%M")
    elif action == "cancel" and row["service_status"] in ("waiting", "in_service"): row["service_status"] = "cancelled"
    else: return jsonify({"error": "Action does not match this record's current status"}), 409
    write_rows(HISTORY, HISTORY_FIELDS, rows)
    return jsonify({"ok": True})


@app.get("/api/admin/bookings")
@owner_required
def admin_bookings(): return jsonify([b for b in read_csv(BOOKINGS, BOOKING_FIELDS) if b["booking_date"] == request.args.get("date", date.today().isoformat())])


ensure_files()
if __name__ == "__main__": app.run()
