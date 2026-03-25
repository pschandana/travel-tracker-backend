"""
Recompute frequency for all trips in the database.
Frequency = number of trips by the same user, same mode, same OD zone
(coords rounded to 2dp), within a 30-day window ending on that trip's date.
"""
from app import app
from models import db, Trip
from datetime import timedelta

def compute_frequency(trip, all_user_trips):
    if trip.start_lat is None or trip.end_lat is None:
        return 1

    origin_lat = round(float(trip.start_lat), 2)
    origin_lng = round(float(trip.start_lng), 2)
    dest_lat   = round(float(trip.end_lat),   2)
    dest_lng   = round(float(trip.end_lng),   2)

    if trip.trip_date is None:
        return 1

    window_start = trip.trip_date - timedelta(days=30)

    count = 0
    for t in all_user_trips:
        if t.start_lat is None or t.end_lat is None:
            continue
        if t.trip_date is None:
            continue
        if t.trip_date < window_start or t.trip_date > trip.trip_date:
            continue
        if t.mode != trip.mode:
            continue
        if (
            round(float(t.start_lat), 2) == origin_lat and
            round(float(t.start_lng), 2) == origin_lng and
            round(float(t.end_lat),   2) == dest_lat   and
            round(float(t.end_lng),   2) == dest_lng
        ):
            count += 1

    return max(count, 1)

with app.app_context():
    all_trips = Trip.query.all()

    # Group by user for efficiency
    by_user = {}
    for t in all_trips:
        by_user.setdefault(t.user_id, []).append(t)

    updated = 0
    for user_id, user_trips in by_user.items():
        for trip in user_trips:
            freq = compute_frequency(trip, user_trips)
            if trip.frequency != freq:
                trip.frequency = freq
                updated += 1

    db.session.commit()
    print(f"Done. Updated frequency for {updated} trips across {len(by_user)} users.")

    # Print summary per user
    for user_id, user_trips in by_user.items():
        print(f"\n  User {user_id}:")
        for t in sorted(user_trips, key=lambda x: x.trip_date or ''):
            print(f"    trip_no={t.trip_no} mode={t.mode} {t.start_lat:.2f},{t.start_lng:.2f} -> {t.end_lat:.2f},{t.end_lng:.2f}  freq={t.frequency}")
