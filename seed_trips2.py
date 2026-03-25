from app import app
from models import db, Trip
from datetime import datetime, timedelta, date

# Approximate coordinates for cities
COORDS = {
    "Vijayawada":  (16.5062, 80.6480),
    "Guntur":      (16.3067, 80.4365),
    "Amaravati":   (16.5150, 80.5160),
    "Tenali":      (16.2432, 80.6400),
    "Mangalagiri": (16.4307, 80.5525),
}

trips_hamidha = [
    {"user_id":5,"origin":"Vijayawada","destination":"Guntur","mode":"car","distance":30.2,"duration":48,"cost":240,"purpose":"work","companions":1},
    {"user_id":5,"origin":"Vijayawada","destination":"Guntur","mode":"bike","distance":29.8,"duration":42,"cost":90,"purpose":"work","companions":0},
    {"user_id":5,"origin":"Vijayawada","destination":"Guntur","mode":"car","distance":30.5,"duration":50,"cost":250,"purpose":"work","companions":2},
    {"user_id":5,"origin":"Vijayawada","destination":"Guntur","mode":"car","distance":30.1,"duration":47,"cost":245,"purpose":"work","companions":1},
    {"user_id":5,"origin":"Vijayawada","destination":"Guntur","mode":"bike","distance":29.7,"duration":41,"cost":85,"purpose":"work","companions":0},
    {"user_id":5,"origin":"Guntur","destination":"Vijayawada","mode":"car","distance":30.3,"duration":52,"cost":240,"purpose":"return","companions":1},
    {"user_id":5,"origin":"Guntur","destination":"Vijayawada","mode":"bike","distance":29.6,"duration":43,"cost":90,"purpose":"return","companions":0},
    {"user_id":5,"origin":"Guntur","destination":"Vijayawada","mode":"car","distance":30.4,"duration":51,"cost":250,"purpose":"return","companions":2},
    {"user_id":5,"origin":"Guntur","destination":"Vijayawada","mode":"car","distance":30.0,"duration":49,"cost":245,"purpose":"return","companions":1},
    {"user_id":5,"origin":"Guntur","destination":"Vijayawada","mode":"bike","distance":29.9,"duration":44,"cost":88,"purpose":"return","companions":0},
]

trips_bhavana = [
    {"user_id":6,"origin":"Vijayawada","destination":"Amaravati","mode":"car","distance":22,"duration":30,"cost":200,"purpose":"work","companions":1},
    {"user_id":6,"origin":"Amaravati","destination":"Vijayawada","mode":"car","distance":22,"duration":32,"cost":200,"purpose":"return","companions":1},
    {"user_id":6,"origin":"Vijayawada","destination":"Guntur","mode":"car","distance":30,"duration":45,"cost":250,"purpose":"meeting","companions":2},
    {"user_id":6,"origin":"Guntur","destination":"Vijayawada","mode":"car","distance":30,"duration":50,"cost":250,"purpose":"return","companions":2},
    {"user_id":6,"origin":"Vijayawada","destination":"Tenali","mode":"car","distance":35,"duration":55,"cost":300,"purpose":"personal","companions":3},
    {"user_id":6,"origin":"Tenali","destination":"Vijayawada","mode":"car","distance":35,"duration":60,"cost":300,"purpose":"return","companions":3},
    {"user_id":6,"origin":"Vijayawada","destination":"Mangalagiri","mode":"bike","distance":13,"duration":25,"cost":70,"purpose":"quick","companions":0},
    {"user_id":6,"origin":"Mangalagiri","destination":"Vijayawada","mode":"bike","distance":13,"duration":27,"cost":70,"purpose":"return","companions":0},
    {"user_id":6,"origin":"Vijayawada","destination":"Guntur","mode":"bus","distance":30,"duration":70,"cost":60,"purpose":"low cost","companions":0},
    {"user_id":6,"origin":"Guntur","destination":"Vijayawada","mode":"bus","distance":30,"duration":65,"cost":60,"purpose":"return","companions":0},
]

base_date = datetime(2026, 3, 1)

with app.app_context():
    all_trips = trips_hamidha + trips_bhavana
    for i, t in enumerate(all_trips):
        trip_date = base_date + timedelta(days=i)
        olat, olng = COORDS.get(t["origin"], (16.5, 80.6))
        dlat, dlng = COORDS.get(t["destination"], (16.3, 80.4))
        trip = Trip(
            user_id=t["user_id"],
            trip_no=f"SEED2-{i+1:03d}",
            start_lat=olat,
            start_lng=olng,
            end_lat=dlat,
            end_lng=dlng,
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
    print(f"Seeded {len(all_trips)} trips (10 for Hamidha uid=5, 10 for Bhavana uid=6)")
