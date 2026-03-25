from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, User, Trip, TripChain
from audit import write_audit
from datetime import datetime, timedelta, timezone
from collections import defaultdict
import uuid

from geopy.geocoders import Nominatim

trips_bp = Blueprint("trips", __name__)


# ---------------- PATCH PROFILE ----------------
@trips_bp.route("/api/profile", methods=["PATCH"])
@jwt_required()
def update_profile():
    uid = get_jwt_identity()
    user = User.query.get(uid)
    if not user:
        return jsonify({"error": "User not found"}), 404

    data = request.get_json() or {}

    if "language" in data:
        lang = data["language"]
        if lang in ("en", "ml", "hi"):
            user.language = lang

    if "theme" in data:
        theme = data["theme"]
        if theme in ("light", "dark"):
            user.theme = theme

    if "name" in data:
        user.name = data["name"]
    if "mobile" in data:
        user.mobile = data["mobile"]
    if "place" in data:
        user.place = data["place"]

    db.session.commit()
    write_audit("UPDATE", "user", user.id, user_id=user.id)
    return jsonify({
        "message": "Profile updated",
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "mobile": user.mobile,
        "place": user.place,
        "language": user.language,
        "theme": user.theme,
        "photo": user.photo,
    })


# ---------------- CREATE TRIP ----------------
@trips_bp.route("/api/trips", methods=["POST"])
@jwt_required()
def create_trip():
    uid = int(get_jwt_identity())

    data = request.get_json()
    trip_no = "TRIP-" + str(uuid.uuid4())[:8]

    def parse_iso(dt_str):
        """Parse ISO datetime string, handling Z suffix and microseconds."""
        if not dt_str:
            return None
        dt_str = str(dt_str).replace("Z", "").strip()
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(dt_str, fmt)
            except ValueError:
                continue
        return None

    start_dt = parse_iso(data.get("start_time"))
    end_dt = parse_iso(data.get("end_time"))

    trip_date = start_dt.date() if start_dt else None

    trip = Trip(
        user_id=uid,
        trip_no=trip_no,
        start_lat=data.get("start_lat"),
        start_lng=data.get("start_lng"),
        end_lat=data.get("end_lat"),
        end_lng=data.get("end_lng"),
        purpose=data.get("purpose"),
        start_time=str(start_dt) if start_dt else None,
        end_time=str(end_dt) if end_dt else None,
        distance=data.get("distance"),
        duration=data.get("duration"),
        trip_date=trip_date,
        mode=data.get("mode"),
        cost=data.get("cost"),
        companions=data.get("companions"),
        frequency=1,
        route=data.get("route"),
        map_image=data.get("map_image"),
    )

    db.session.add(trip)
    db.session.commit()

    # Compute and store frequency (Req 12)
    trip.frequency = compute_frequency(trip)
    db.session.commit()

    try:
        form_trip_chains(uid)
    except Exception:
        pass  # Chain formation errors must not break the trip save response

    return jsonify({"msg": "Trip saved", "frequency": trip.frequency})


# ---------------- GET USER TRIPS ----------------
@trips_bp.route("/api/trips", methods=["GET"])
@jwt_required()
def get_trips():
    uid = int(get_jwt_identity())

    # Pagination params (Req 26)
    try:
        page = max(1, int(request.args.get("page", 1)))
    except (ValueError, TypeError):
        page = 1
    try:
        page_size = max(1, int(request.args.get("page_size", 20)))
    except (ValueError, TypeError):
        page_size = 20

    total = Trip.query.filter_by(user_id=uid).count()

    # Only paginate when total exceeds 50 (Req 26)
    if total > 50:
        offset = (page - 1) * page_size
        trips = (
            Trip.query
            .filter_by(user_id=uid)
            .order_by(Trip.start_time.desc())
            .offset(offset)
            .limit(page_size)
            .all()
        )
        total_pages = (total + page_size - 1) // page_size
        paginated = True
    else:
        trips = Trip.query.filter_by(user_id=uid).order_by(Trip.start_time.desc()).all()
        total_pages = 1
        page = 1
        paginated = False

    data = []
    for t in trips:
        data.append({
            "id": t.id,
            "start_lat": t.start_lat,
            "start_lng": t.start_lng,
            "end_lat": t.end_lat,
            "end_lng": t.end_lng,
            "purpose": t.purpose,
            "start_time": t.start_time,
            "end_time": t.end_time,
            "distance": t.distance,
            "duration": t.duration,
            "mode": t.mode,
            "cost": t.cost,
            "companions": t.companions,
            "trip_date": t.trip_date,
            "frequency": t.frequency,
            "map_image": t.map_image,
            "route": t.route,
            "trip_no": t.trip_no,
            "chain_id": t.chain_id,
        })

    return jsonify({
        "trips": data,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_prev": page > 1,
        "paginated": paginated,
    })


# ---------------- GET SINGLE TRIP ----------------
@trips_bp.route("/api/trips/<int:trip_id>", methods=["GET"])
@jwt_required()
def get_trip(trip_id):
    uid = int(get_jwt_identity())
    trip = Trip.query.get(trip_id)
    if not trip:
        return jsonify({"msg": "Not found"}), 404
    if trip.user_id != uid:
        return jsonify({"msg": "Forbidden"}), 403
    return jsonify({
        "id": trip.id,
        "trip_no": trip.trip_no,
        "user_id": trip.user_id,
        "start_lat": trip.start_lat,
        "start_lng": trip.start_lng,
        "end_lat": trip.end_lat,
        "end_lng": trip.end_lng,
        "start_time": trip.start_time,
        "end_time": trip.end_time,
        "trip_date": str(trip.trip_date) if trip.trip_date else None,
        "distance": trip.distance,
        "duration": trip.duration,
        "mode": trip.mode,
        "ml_mode": trip.ml_mode,
        "confidence_score": trip.confidence_score,
        "purpose": trip.purpose,
        "cost": trip.cost,
        "companions": trip.companions,
        "frequency": trip.frequency,
        "chain_id": trip.chain_id,
        "route": trip.route,
        "is_incomplete": trip.is_incomplete,
        "has_gps_gap": trip.has_gps_gap,
        "data_quality_flag": trip.data_quality_flag,
    })


# ---------------- DELETE TRIP ----------------
@trips_bp.route("/api/trips/<int:trip_id>", methods=["DELETE"])
@jwt_required()
def delete_trip(trip_id):
    uid = get_jwt_identity()

    trip = Trip.query.filter_by(id=trip_id, user_id=uid).first()

    if not trip:
        return jsonify({"msg": "Not found"}), 404

    db.session.delete(trip)
    db.session.commit()

    return jsonify({"msg": "Trip deleted"})


# ---------------- PATCH TRIP (completion fields) ----------------
@trips_bp.route("/api/trips/<int:trip_id>", methods=["PATCH"])
@jwt_required()
def update_trip(trip_id):
    uid = int(get_jwt_identity())

    # Check trip exists at all
    trip = Trip.query.get(trip_id)
    if not trip:
        return jsonify({"msg": "Not found"}), 404

    # Check ownership
    if trip.user_id != uid:
        return jsonify({"msg": "Forbidden"}), 403

    data = request.get_json() or {}

    if "purpose" in data:
        trip.purpose = data["purpose"]
    if "companions" in data:
        trip.companions = data["companions"]
    if "cost" in data:
        trip.cost = data["cost"]
    if "mode" in data:
        trip.mode = data["mode"]
    if "is_incomplete" in data:
        trip.is_incomplete = data["is_incomplete"]

    db.session.commit()
    write_audit("UPDATE", "trip", trip.id, user_id=uid)

    try:
        form_trip_chains(uid)
    except Exception:
        pass  # Chain formation errors must not break the trip update response

    return jsonify({
        "id": trip.id,
        "trip_no": trip.trip_no,
        "purpose": trip.purpose,
        "companions": trip.companions,
        "cost": trip.cost,
        "mode": trip.mode,
        "ml_mode": trip.ml_mode,
        "confidence_score": trip.confidence_score,
        "is_incomplete": trip.is_incomplete,
        "start_lat": trip.start_lat,
        "start_lng": trip.start_lng,
        "end_lat": trip.end_lat,
        "end_lng": trip.end_lng,
        "start_time": trip.start_time,
        "end_time": trip.end_time,
        "distance": trip.distance,
        "duration": trip.duration,
        "trip_date": str(trip.trip_date) if trip.trip_date else None,
        "frequency": trip.frequency,
    })


# ---------------- DASHBOARD ----------------
@trips_bp.route("/api/dashboard")
@jwt_required()
def dashboard():
    uid = get_jwt_identity()

    trips = Trip.query.filter_by(user_id=uid).all()

    total_trips = len(trips)
    total_distance = sum([t.distance or 0 for t in trips])
    total_cost = sum([t.cost or 0 for t in trips])

    # -------- MODE COUNT --------
    mode_count = {}
    for t in trips:
        if t.mode:
            mode_count[t.mode] = mode_count.get(t.mode, 0) + 1

    top_mode = max(mode_count, key=mode_count.get) if mode_count else None

    # -------- LOCATION CLUSTER --------
    area_count = {}
    for t in trips:
        if t.route:
            for p in t.route:
                lat = round(p["lat"], 3)
                lng = round(p["lng"], 3)
                key = f"{lat},{lng}"
                area_count[key] = area_count.get(key, 0) + 1

    most_area = None
    least_area = None

    if area_count:
        sorted_areas = sorted(area_count.items(), key=lambda x: x[1], reverse=True)
        most_area = sorted_areas[0]
        least_area = sorted_areas[-1]

    # -------- REVERSE GEOCODE --------
    geolocator = Nominatim(user_agent="travel_tracker")

    def get_area_name(lat, lng):
        try:
            location = geolocator.reverse((lat, lng), exactly_one=True, timeout=10)
            if location and location.raw:
                address = location.raw.get("address", {})
                area = (
                    address.get("suburb")
                    or address.get("neighbourhood")
                    or address.get("road")
                    or address.get("village")
                    or address.get("town")
                    or address.get("city")
                )
                city = (
                    address.get("city")
                    or address.get("town")
                    or address.get("state")
                )
                if area and city:
                    return f"{area}, {city}"
                if city:
                    return city
        except Exception as e:
            print("Geo error:", e)
        return "Unknown Area"

    most_area_name = None
    least_area_name = None

    if most_area:
        lat, lng = most_area[0].split(",")
        most_area_name = get_area_name(float(lat), float(lng))

    if least_area:
        lat, lng = least_area[0].split(",")
        least_area_name = get_area_name(float(lat), float(lng))

    return jsonify({
        "total_trips": total_trips,
        "total_distance": round(total_distance, 2),
        "total_cost": round(total_cost, 2),
        "top_mode": top_mode,
        "most_travelled_area": most_area_name,
        "least_travelled_area": least_area_name,
    })


# ---------------- ANALYTICS (monthly) ----------------
@trips_bp.route("/api/analytics")
@jwt_required()
def analytics():
    uid = get_jwt_identity()

    trips = Trip.query.filter_by(user_id=uid).all()

    monthly = defaultdict(lambda: {"trips": 0, "distance": 0, "cost": 0})

    for t in trips:
        if t.created_at:
            month = t.created_at.strftime("%Y-%m")
            monthly[month]["trips"] += 1
            monthly[month]["distance"] += t.distance or 0
            monthly[month]["cost"] += t.cost or 0

    data = []
    for k in sorted(monthly.keys()):
        data.append({
            "month": k,
            "trips": monthly[k]["trips"],
            "distance": round(monthly[k]["distance"], 2),
            "cost": round(monthly[k]["cost"], 2),
        })

    return jsonify(data)


# ---------------- WEEKLY ANALYTICS ----------------
@trips_bp.route("/api/weekly-analytics")
@jwt_required()
def weekly_analytics():
    uid = get_jwt_identity()

    now = datetime.utcnow()
    week_ago = now - timedelta(days=7)

    trips = Trip.query.filter(
        Trip.user_id == uid,
        Trip.created_at >= week_ago
    ).all()

    total_trips = len(trips)
    total_distance = 0
    total_time = 0
    total_cost = 0
    mode_count = defaultdict(int)

    for t in trips:
        total_distance += t.distance or 0
        total_cost += t.cost or 0
        if t.duration:
            total_time += t.duration
        if t.mode:
            mode_count[t.mode] += 1

    # Mode %
    mode_percent = {}
    for k, v in mode_count.items():
        mode_percent[k] = round((v / total_trips) * 100, 1) if total_trips else 0

    # -------- CARBON FOOTPRINT --------
    # Emission factors (kg CO2 per km) per travel mode
    EMISSION_FACTORS = {
        "Walking": 0.0,
        "Walk": 0.0,
        "Cycling": 0.0,
        "Cycle": 0.0,
        "Bus": 0.089,
        "Car": 0.21,
        "Train": 0.041,
        "Auto": 0.15,
    }

    carbon = 0.0
    for t in trips:
        factor = EMISSION_FACTORS.get(t.mode, 0.0)
        carbon += (t.distance or 0) * factor

    carbon = round(carbon, 2)

    # -------- SMART INSIGHTS --------
    insights = []

    if total_cost > 500:
        insights.append("💰 Consider using public transport to reduce your weekly travel expenses.")

    if total_time > 600:
        insights.append("⏱️ You spend a lot of time travelling. Try optimising your routes or travel times.")

    walking_count = mode_count.get("Walk", 0) + mode_count.get("Walking", 0)
    if walking_count > 5:
        insights.append("🏃 Great job staying active! You walked on more than 5 trips this week.")

    insights.append(f"🌱 Your estimated carbon footprint this week is {carbon} kg CO₂.")

    return jsonify({
        "total_trips": total_trips,
        "total_distance": round(total_distance, 2),
        "total_time": round(total_time, 2),
        "total_cost": round(total_cost, 2),
        "mode_percent": mode_percent,
        "carbon_footprint": carbon,
        "insights": insights,
    })


# ---------------- RANGE ANALYTICS ----------------
@trips_bp.route("/api/range-analytics")
@jwt_required()
def range_analytics():
    uid = get_jwt_identity()

    # Accept start_date/end_date (frontend convention) or start/end (legacy)
    start = request.args.get("start_date") or request.args.get("start")
    end = request.args.get("end_date") or request.args.get("end")

    if not start or not end:
        return jsonify({"msg": "start_date and end_date are required"}), 400

    try:
        start_date = datetime.fromisoformat(start).date()
        end_date = datetime.fromisoformat(end).date()
    except ValueError:
        return jsonify({"msg": "Invalid date format. Use YYYY-MM-DD"}), 400

    trips = Trip.query.filter(
        Trip.user_id == uid,
        Trip.trip_date >= start_date,
        Trip.trip_date <= end_date
    ).all()

    total_trips = len(trips)
    total_distance = 0
    total_time = 0
    total_cost = 0
    mode_count = {}
    carbon = 0

    for t in trips:
        total_distance += t.distance or 0
        total_time += t.duration or 0
        total_cost += t.cost or 0

        if t.mode:
            mode_count[t.mode] = mode_count.get(t.mode, 0) + 1

        if t.mode == "Car":
            carbon += (t.distance or 0) * 0.21
        elif t.mode == "Bus":
            carbon += (t.distance or 0) * 0.08
        elif t.mode == "Bike":
            carbon += (t.distance or 0) * 0.01
        elif t.mode in ("Walk", "Walking", "Cycling", "Cycle"):
            carbon += 0
        elif t.mode == "Train":
            carbon += (t.distance or 0) * 0.04
        elif t.mode == "Auto":
            carbon += (t.distance or 0) * 0.10

    # Mode distribution — raw counts (used by frontend ModeBar)
    mode_distribution = dict(mode_count)

    # Mode % — percentage breakdown
    mode_percent = {}
    for k, v in mode_count.items():
        mode_percent[k] = round((v / total_trips) * 100, 1) if total_trips else 0

    # ---------- SMART INSIGHTS ----------
    insights = []

    if total_cost > 500:
        insights.append("💰 You are spending a lot on travel. Consider public transport.")

    if total_time > 500:
        insights.append("⏱️ You spend a lot of time traveling. Try route optimization.")

    walk_count = mode_count.get("Walk", 0) + mode_count.get("Walking", 0)
    cycle_count = mode_count.get("Cycling", 0) + mode_count.get("Cycle", 0)
    if walk_count + cycle_count >= 3:
        insights.append("🏃 Great! You are staying active by walking or cycling.")

    if carbon > 5:
        insights.append(f"🌱 High carbon footprint: {round(carbon, 2)} kg CO₂")

    if carbon < 2 and total_trips > 0:
        insights.append("🌍 Eco-friendly travel habits. Keep it up!")

    if mode_count.get("Car", 0) > mode_count.get("Bus", 0):
        insights.append("🚍 Try using bus more often to save money & fuel.")

    return jsonify({
        "total_trips": total_trips,
        "total_distance": round(total_distance, 2),
        "total_time": round(total_time, 2),
        "total_cost": round(total_cost, 2),
        "carbon_footprint": round(carbon, 2),
        "mode_distribution": mode_distribution,
        "mode_percent": mode_percent,
        "insights": insights,
    })


# ---------------- COMPUTE FREQUENCY (Req 12) ----------------
def compute_frequency(trip):
    """
    Count trips for the same user with matching origin zone, destination zone,
    and travel mode within a 30-day rolling window ending at trip.trip_date.

    Origin/destination zones are derived by rounding coordinates to 2 decimal
    places (~1 km grid).
    """
    if trip.start_lat is None or trip.start_lng is None:
        return 1
    if trip.end_lat is None or trip.end_lng is None:
        return 1

    origin_lat = round(float(trip.start_lat), 2)
    origin_lng = round(float(trip.start_lng), 2)
    dest_lat = round(float(trip.end_lat), 2)
    dest_lng = round(float(trip.end_lng), 2)

    trip_date = trip.trip_date
    if trip_date is None:
        return 1

    window_start = trip_date - timedelta(days=30)

    matching = Trip.query.filter(
        Trip.user_id == trip.user_id,
        Trip.mode == trip.mode,
        Trip.trip_date >= window_start,
        Trip.trip_date <= trip_date,
    ).all()

    count = 0
    for t in matching:
        if t.start_lat is None or t.start_lng is None:
            continue
        if t.end_lat is None or t.end_lng is None:
            continue
        if (
            round(float(t.start_lat), 2) == origin_lat
            and round(float(t.start_lng), 2) == origin_lng
            and round(float(t.end_lat), 2) == dest_lat
            and round(float(t.end_lng), 2) == dest_lng
        ):
            count += 1

    return max(count, 1)


# ---------------- FORM TRIP CHAINS (Req 10) ----------------
def form_trip_chains(user_id):
    """
    Group consecutive trips for a user into TripChain records.

    Algorithm (P6 invariant):
      - Fetch all trips ordered by start_time ascending.
      - Walk through trips; if gap between end_time[i] and start_time[i+1] ≤ 60 min,
        they belong to the same chain group.
      - Groups of 2+ trips become a TripChain; solo trips get chain_id = None.
      - Existing chain assignments are cleared first so re-evaluation is clean.
    """

    def _parse_dt(dt_str):
        """Return a timezone-aware datetime from an ISO 8601 string, or None."""
        if not dt_str:
            return None
        s = str(dt_str).strip()
        # Normalise 'Z' suffix
        s = s.replace("Z", "+00:00")
        # Try fromisoformat (Python 3.7+)
        try:
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            pass
        # Fallback: strip offset and treat as UTC
        for fmt in (
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S",
        ):
            try:
                dt = datetime.strptime(s[:len(fmt) + 6], fmt)
                return dt.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        return None

    def _reverse_geocode(lat, lng, geolocator):
        """Return a human-readable place name for the given coordinates."""
        if lat is None or lng is None:
            return f"{lat},{lng}"
        try:
            location = geolocator.reverse((lat, lng), exactly_one=True, timeout=10)
            if location and location.raw:
                address = location.raw.get("address", {})
                name = (
                    address.get("suburb")
                    or address.get("neighbourhood")
                    or address.get("road")
                    or address.get("village")
                    or address.get("town")
                    or address.get("city")
                    or address.get("state")
                )
                if name:
                    return name
        except Exception as e:
            print(f"[form_trip_chains] Geocode error: {e}")
        return f"{round(lat, 4)},{round(lng, 4)}"

    try:
        # 1. Clear existing chain assignments for this user so we start fresh.
        Trip.query.filter_by(user_id=user_id).update({"chain_id": None})
        db.session.flush()

        # 2. Fetch trips ordered by start_time ascending.
        trips = (
            Trip.query
            .filter_by(user_id=user_id)
            .order_by(Trip.start_time.asc())
            .all()
        )

        if not trips:
            db.session.commit()
            return

        # 3. Build groups of consecutive trips with gap ≤ 60 minutes.
        groups = []          # list of lists of Trip objects
        current_group = [trips[0]]

        for i in range(1, len(trips)):
            prev = trips[i - 1]
            curr = trips[i]

            prev_end = _parse_dt(prev.end_time)
            curr_start = _parse_dt(curr.start_time)

            if prev_end and curr_start:
                gap_minutes = (curr_start - prev_end).total_seconds() / 60.0
                if gap_minutes <= 60.0:
                    current_group.append(curr)
                    continue

            # Gap too large or timestamps missing — start a new group
            groups.append(current_group)
            current_group = [curr]

        groups.append(current_group)

        # 4. For each group of 2+ trips, create/update a TripChain.
        geolocator = Nominatim(user_agent="travel_tracker_chain")

        for group in groups:
            if len(group) < 2:
                # Solo trip — leave chain_id as None
                continue

            # Build label: origin → stop1 → … → destination
            waypoints = []
            waypoints.append(_reverse_geocode(group[0].start_lat, group[0].start_lng, geolocator))
            for leg in group[1:]:
                waypoints.append(_reverse_geocode(leg.start_lat, leg.start_lng, geolocator))
            waypoints.append(_reverse_geocode(group[-1].end_lat, group[-1].end_lng, geolocator))
            label = " → ".join(waypoints)

            total_duration = sum(t.duration or 0 for t in group)
            total_distance = sum(t.distance or 0 for t in group)
            legs_count = len(group)
            mode_sequence = [t.mode for t in group if t.mode]

            # Reuse an existing chain if one already covers the same first trip,
            # otherwise create a new one.
            new_chain_id = "CHAIN-" + str(uuid.uuid4())[:8]

            chain = TripChain(
                chain_id=new_chain_id,
                user_id=user_id,
                label=label,
                total_duration=round(total_duration, 2),
                total_distance=round(total_distance, 2),
                legs_count=legs_count,
                mode_sequence=mode_sequence,
            )
            db.session.add(chain)
            db.session.flush()  # get chain.chain_id persisted before updating trips

            for trip in group:
                trip.chain_id = chain.chain_id

        db.session.commit()

    except Exception as e:
        db.session.rollback()
        print(f"[form_trip_chains] Error: {e}")
        raise


# ---------------- TRIP CHAINS ----------------
@trips_bp.route("/api/trip-chains")
@jwt_required()
def get_trip_chains():
    uid = int(get_jwt_identity())

    chains = (
        TripChain.query
        .filter_by(user_id=uid)
        .order_by(TripChain.created_at.desc())
        .all()
    )

    data = []
    for c in chains:
        data.append({
            "chain_id": c.chain_id,
            "label": c.label,
            "total_duration": c.total_duration,
            "total_distance": c.total_distance,
            "legs_count": c.legs_count,
            "mode_sequence": c.mode_sequence,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        })

    return jsonify(data)


# ---------------- RECOMMENDATIONS ----------------
@trips_bp.route("/api/recommendations")
@jwt_required()
def recommendations():
    uid = int(get_jwt_identity())

    origin = request.args.get("origin")
    destination = request.args.get("destination")

    if not origin or not destination:
        return jsonify({"msg": "Origin and destination required"}), 400

    # Find historical trips matching the origin-destination pair (by proximity)
    trips = Trip.query.filter_by(user_id=uid).all()

    # Simple matching: trips with similar start/end coordinates (within ~0.01 deg ≈ 1km)
    def coords_match(a, b, tol=0.01):
        try:
            a_lat, a_lng = map(float, a.split(","))
            b_lat, b_lng = map(float, b.split(","))
            return abs(a_lat - b_lat) < tol and abs(a_lng - b_lng) < tol
        except Exception:
            return False

    matched = [
        t for t in trips
        if t.start_lat and t.start_lng and t.end_lat and t.end_lng
        and coords_match(origin, f"{t.start_lat},{t.start_lng}")
        and coords_match(destination, f"{t.end_lat},{t.end_lng}")
    ]

    if len(matched) < 5:
        return jsonify({
            "msg": "Insufficient data for this route",
            "routes": [],
        })

    # Group by mode and compute averages
    by_mode = defaultdict(list)
    for t in matched:
        if t.mode:
            by_mode[t.mode].append(t)

    routes = []
    for mode, mode_trips in by_mode.items():
        avg_duration = sum(t.duration or 0 for t in mode_trips) / len(mode_trips)
        avg_distance = sum(t.distance or 0 for t in mode_trips) / len(mode_trips)
        routes.append({
            "mode": mode,
            "estimated_duration": round(avg_duration, 1),
            "estimated_distance": round(avg_distance, 2),
            "sample_count": len(mode_trips),
        })

    routes.sort(key=lambda r: r["estimated_duration"])
    return jsonify({"routes": routes[:3]})


# ---------------- ML CLASSIFY TRIP ----------------
@trips_bp.route("/api/trips/<int:trip_id>/classify", methods=["POST"])
@jwt_required()
def classify_trip(trip_id):
    uid = int(get_jwt_identity())

    trip = Trip.query.filter_by(id=trip_id, user_id=uid).first()
    if not trip:
        return jsonify({"msg": "Not found"}), 404

    try:
        from ml_model import classify_mode
        ml_mode, confidence_score = classify_mode(trip.route or [])
        trip.ml_mode = ml_mode
        trip.confidence_score = confidence_score
        db.session.commit()
        return jsonify({"ml_mode": ml_mode, "confidence_score": confidence_score})
    except Exception as e:
        return jsonify({"msg": f"Classification error: {str(e)}"}), 500


# ---------------- INCOMPLETE REMINDER ----------------
@trips_bp.route("/api/trips/<int:trip_id>/incomplete-reminder", methods=["POST"])
@jwt_required()
def incomplete_reminder(trip_id):
    uid = int(get_jwt_identity())

    trip = Trip.query.filter_by(id=trip_id, user_id=uid).first()
    if not trip:
        return jsonify({"msg": "Not found"}), 404

    # Check if completion data has already been submitted
    has_completion_data = (
        trip.purpose not in (None, "")
        or trip.companions is not None
        or trip.cost is not None
    )
    if has_completion_data:
        return jsonify({"msg": "Trip already has completion data"}), 400

    # Verify 24 hours have passed since trip end (Req 9)
    if trip.end_time:
        try:
            from datetime import timezone
            # Parse ISO 8601 end_time; handle both offset-aware and naive strings
            end_time_str = trip.end_time.replace("Z", "+00:00")
            trip_end = datetime.fromisoformat(end_time_str)
            # Make both datetimes timezone-aware for comparison
            if trip_end.tzinfo is None:
                trip_end = trip_end.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            elapsed_hours = (now - trip_end).total_seconds() / 3600
            if elapsed_hours < 24:
                return jsonify({
                    "msg": "24 hours have not yet passed since trip end",
                    "hours_elapsed": round(elapsed_hours, 2)
                }), 400
        except (ValueError, TypeError):
            # If end_time cannot be parsed, proceed without the time check
            pass

    trip.is_incomplete = True
    db.session.commit()

    write_audit("UPDATE", "trip", trip.id, user_id=uid)

    return jsonify({"msg": "Trip marked as incomplete", "trip_id": trip_id})
