from app import app
from models import db, Trip
from datetime import datetime, timedelta

COORDS = {
    "Vijayawada":  (16.5062, 80.6480),
    "Guntur":      (16.3067, 80.4365),
}

trips_chandana = [
    {"user_id":4,"origin":"Vijayawada","destination":"Guntur","mode":"car","distance":30.2,"duration":48,"cost":240,"purpose":"work","companions":1},
    {"user_id":4,"origin":"Vijayawada","destination":"Guntur","mode":"car","distance":30.3,"duration":49,"cost":245,"purpose":"work","companions":2},
    {"user_id":4,"origin":"Vijayawada","destination":"Guntur","mode":"car","distance":30.1,"duration":47,"cost":235,"purpose":"work","companions":1},
    {"user_id":4,"origin":"Vijayawada","destination":"Guntur","mode":"bike","distance":29.8,"duration":42,"cost":90,"purpose":"work","companions":0},
    {"user_id":4,"origin":"Vijayawada","destination":"Guntur","mode":"bike","distance":29.7,"duration":41,"cost":85,"purpose":"work","companions":0},
]

trips_hamidha = [
    {"user_id":5,"origin":"Guntur","destination":"Vijayawada","mode":"car","distance":30.3,"duration":52,"cost":240,"purpose":"return","companions":1},
    {"user_id":5,"origin":"Guntur","destination":"Vijayawada","mode":"car","distance":30.4,"duration":51,"cost":250,"purpose":"return","companions":2},
    {"user_id":5,"origin":"Guntur","destination":"Vijayawada","mode":"car","distance":30.2,"duration":50,"cost":245,"purpose":"return","companions":1},
    {"user_id":5,"origin":"Guntur","destination":"Vijayawada","mode":"bike","distance":29.9,"duration":44,"cost":88,"purpose":"return","companions":0},
]

base_date = datetime(2026, 3, 15)

with app.app_context():
    all_trips = trips_chandana + trips_hamidha
    for i, t in enumerate(all_trips):
        trip_date = base_date + timedelta(days=i)
        olat, olng = COORDS.get(t["origin"], (16.5, 80.6))
        dlat, dlng = COORDS.get(t["destination"], (16.3, 80.4))
        trip = Trip(
            user_id=t["user_id"],
            trip_no=f"SEED3-{i+1:03d}",
            start_lat=olat, start_lng=olng,
            end_lat=dlat, end_lng=dlng,
            start_time=trip_date.isoformat(),
            end_time=(trip_date + timedelta(minutes=t["duration"])).isoformat(),
            trip_date=trip_date.date(),
            distance=t["distance"],
            duration=t["duration"],
            mode=t["mode"],
            purpose=t["purpose"],
            cost=t["cost"],
            companions=t["companions"],
        )
        db.session.add(trip)
    db.session.commit()
    print(f"Seeded {len(trips_chandana)} trips for Chandana (uid=4), {len(trips_hamidha)} for Hamidha (uid=5)")


