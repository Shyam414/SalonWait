# SalonWait

CSV-backed customer booking website and owner dashboard for **Kiran Saloon, Bollaram, Hyderabad**. Customers can browse the live service catalogue, see historical wait and duration statistics, check appointment slots, and book. Owners can manage walk-ins, services and today's booking list.

## Stack and files

- Python 3 and Flask; CSV files are the initial storage.
- HTML, CSS and vanilla JavaScript.
- `app.py`: Flask website, APIs, CSV logic and session authentication.
- `salonwait.py`: preserved historical-data CLI estimator.
- `data/data.csv`: historical service records.
- `data/services.csv`: service catalogue; `data/bookings.csv`: bookings.
- `templates/`, `static/css/`, `static/js/`: UI assets.
- `tests/`: unittest coverage using temporary CSV files.

The historical CSV header is exactly `record_id,observation_date,arrival_time,service_type,service_start_time,service_end_time,barber_id,service_status`. Services use `service_id,service_name,price,duration_minutes,active`. Bookings use `booking_id,customer_name,service_type,booking_date,slot_start,slot_end,barber_id,status`. Existing CSV files are preserved at startup; missing files are initialized. No customer names are written to historical walk-in records.

## Local setup (Windows PowerShell)

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:SALONWAIT_ADMIN_PASSWORD="your-password"
$env:SALONWAIT_SECRET_KEY="your-long-random-secret"
python app.py
```

Open the customer website at <http://127.0.0.1:5000> and the owner page at <http://127.0.0.1:5000/admin/login>. Set both environment variables before starting. If no secret key is supplied, a random key is generated at startup; sessions then reset when the app restarts. The login is unavailable until `SALONWAIT_ADMIN_PASSWORD` is set.

Example configuration is 09:00–21:00, barbers B1/B2/B3, and 30-minute slot intervals. Confirm opening hours, staffing and example prices/durations with the owner before public use. `SALONWAIT_OPEN`, `SALONWAIT_CLOSE`, `SALONWAIT_BARBERS` (comma-separated) can change schedule settings.

## Using the app

Services are loaded from `services.csv`. The initial example catalogue is Haircut ₹150/20 min, Beard Trim ₹80/10 min, Haircut + Beard ₹200/30 min, and Head Massage ₹100/20 min. These are example values and must be verified by the owner. Add more from the signed-in dashboard.

Customers select service and date, check the generated slots, choose one, enter their name and confirm. The backend checks availability again and returns a booking reference. The owner signs in, adds walk-ins by service and barber, starts or completes queue records, and reviews today's bookings. A walk-in's arrival timestamp is recorded automatically.

## Demo recording

[Watch the 3-minute screen recording](recordings/salonwait-demo.mp4) *(recording to be added at this path).* The demo should show the customer booking flow and the owner dashboard running locally.

Historical wait is `service_start_time - arrival_time`; historical duration is `service_end_time - service_start_time`. Only completed records with valid HH:MM times, nonnegative waits and positive durations count. The API returns medians and sample count; fewer than five records are flagged as a low sample. These figures describe past observations, not live queue guarantees. Same-day calculations assume a service does not cross midnight.

Slots run from opening to closing at a 30-minute start interval, fit the service duration before closing, and are checked against confirmed bookings and active walk-in work for each barber. Cancelled bookings do not block a slot. The booking is revalidated at submission.

## API examples

```powershell
Invoke-RestMethod http://127.0.0.1:5000/api/services
Invoke-RestMethod 'http://127.0.0.1:5000/api/wait?service=Haircut'
Invoke-RestMethod 'http://127.0.0.1:5000/api/slots?date=2026-11-18&service=Haircut'
Invoke-RestMethod -Method Post http://127.0.0.1:5000/api/bookings -ContentType 'application/json' -Body '{"customer_name":"Ravi","service_type":"Haircut","booking_date":"2026-11-18","slot_start":"10:00","barber_id":"B1"}'
```

Admin API endpoints require an authenticated Flask session. Booking customer information is only returned to authenticated dashboard endpoints.

## Tests

```powershell
python -m unittest discover -s tests -v
```

## Deployment and limitations

Deploy with a Python-compatible host and a WSGI server, configure `SALONWAIT_ADMIN_PASSWORD` and a long random `SALONWAIT_SECRET_KEY`, mount persistent storage for the CSV directory (`SALONWAIT_DATA_DIR`), enable HTTPS, and back up the CSV files. Never deploy with a default password. This is basic MVP authentication; public deployment also needs CSRF protection, rate limiting and proper user management.

CSV writes are locked within one application process, but CSV storage is not suitable for robust concurrent multi-worker bookings. This is an initial single-instance prototype; migrate to PostgreSQL before real concurrent usage at scale. No deployment is implied by this repository. CSV row issues are skipped for historical estimates; midnight-crossing service records are not supported by the historical calculation.
