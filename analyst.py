# analyst.py

from flask import Blueprint, request, jsonify, current_app, Response
from sqlalchemy.sql import func
from functools import wraps
from collections import defaultdict
from datetime import datetime, timedelta
import csv
import io
import jwt
import requests

from models import db, Trip, Analyst
from ml_model import run_ai_engine, train_model
from audit import write_audit

analyst_bp = Blueprint("analyst", __name__)

# =============================
# CONFIG
# =============================

VALID_ANALYST_ID = "Analyst5005"

# =============================
# AUTH DECORATOR
# =============================

def analyst_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get("Authorization")
        if not token:
            return jsonify({"error": "Token missing"}), 401
        try:
            decoded = jwt.decode(
                token,
                current_app.config["SECRET_KEY"],
                algorithms=["HS256"]
            )
            if decoded["role"] != "analyst":
                return jsonify({"error": "Unauthorized"}), 403
        except Exception:
            return jsonify({"error": "Invalid token"}), 401
        return f(*args, **kwargs)
    return decorated

# =============================
# REGISTER
# =============================

@analyst_bp.route("/api/analyst/register", methods=["POST"])
def analyst_register():
    data = request.get_json() or {}
    name = data.get("name", "").strip()
    email = data.get("email", "").strip()
    password = data.get("password", "").strip()
    analyst_id = data.get("analyst_id", "").strip()

    if not all([name, email, password, analyst_id]):
        return jsonify({"error": "All fields are required"}), 400

    if analyst_id != VALID_ANALYST_ID:
        return jsonify({"error": "Invalid Analyst ID"}), 403

    if Analyst.query.filter_by(email=email).first():
        return jsonify({"error": "Email already registered"}), 400

    from flask_bcrypt import Bcrypt
    bcrypt = Bcrypt()
    hashed = bcrypt.generate_password_hash(password).decode("utf-8")

    analyst = Analyst(name=name, email=email, password=hashed)
    db.session.add(analyst)
    db.session.commit()

    return jsonify({"msg": "Analyst registered successfully"}), 201

# =============================
# LOGIN
# =============================

@analyst_bp.route("/api/analyst/login", methods=["POST"])
def analyst_login():
    data = request.json or {}
    email = data.get("email", "").strip()
    password = data.get("password", "").strip()

    if not email or not password:
        return jsonify({"error": "Email and password required"}), 400

    analyst = Analyst.query.filter_by(email=email).first()
    if not analyst:
        return jsonify({"error": "Invalid credentials"}), 401

    from flask_bcrypt import Bcrypt
    bcrypt = Bcrypt()
    if not bcrypt.check_password_hash(analyst.password, password):
        return jsonify({"error": "Invalid credentials"}), 401

    token = jwt.encode(
        {"role": "analyst", "analyst_id": analyst.id, "exp": datetime.utcnow() + timedelta(hours=8)},
        current_app.config["SECRET_KEY"],
        algorithm="HS256"
    )
    return jsonify({"token": token})

# =============================
# DASHBOARD STATS
# =============================

def _apply_common_filters(query, start_date=None, end_date=None, mode=None, region=None):
    """Apply shared filter params (date range, mode, region) to a Trip query."""
    if start_date:
        try:
            query = query.filter(Trip.trip_date >= datetime.strptime(start_date, "%Y-%m-%d").date())
        except ValueError:
            pass
    if end_date:
        try:
            query = query.filter(Trip.trip_date <= datetime.strptime(end_date, "%Y-%m-%d").date())
        except ValueError:
            pass
    if mode:
        query = query.filter(Trip.mode == mode)
    if region:
        try:
            parts = region.split(",")
            r_lat, r_lng, r_radius = float(parts[0]), float(parts[1]), float(parts[2])
            delta = r_radius / 111
            query = query.filter(
                Trip.start_lat.between(r_lat - delta, r_lat + delta),
                Trip.start_lng.between(r_lng - delta, r_lng + delta)
            )
        except (ValueError, IndexError):
            pass
    return query


@analyst_bp.route("/api/analyst/dashboard")
@analyst_required
def dashboard():
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    mode = request.args.get("mode")
    region = request.args.get("region")

    trips = _apply_common_filters(Trip.query, start_date, end_date, mode, region).all()

    total_trips = len(trips)
    total_distance = sum(t.distance or 0 for t in trips)
    total_cost = sum(t.cost or 0 for t in trips)
    avg_duration = (sum(t.duration or 0 for t in trips) / total_trips) if total_trips else 0

    thirty_days_ago = datetime.utcnow().date() - timedelta(days=30)
    active_users = len(set(
        t.user_id for t in trips
        if t.user_id is not None and t.trip_date and t.trip_date >= thirty_days_ago
    ))

    return jsonify({
        "total_trips": total_trips,
        "total_distance": round(total_distance, 2),
        "total_cost": round(total_cost, 2),
        "avg_duration": round(avg_duration, 2),
        "active_users": active_users
    })

# =============================
# HEATMAP DATA (WEIGHTED)
# =============================

@analyst_bp.route("/api/analyst/heatmap", methods=["GET", "POST"])
@analyst_required
def heatmap():
    data = request.json or {}
    lat = float(data.get("lat", 0))
    lng = float(data.get("lng", 0))
    radius = float(data.get("radius", 5))
    delta = radius / 111

    start_date = data.get("start_date") or request.args.get("start_date")
    end_date = data.get("end_date") or request.args.get("end_date")
    mode = data.get("mode") or request.args.get("mode")

    query = Trip.query.filter(
        Trip.start_lat.between(lat - delta, lat + delta),
        Trip.start_lng.between(lng - delta, lng + delta)
    )
    query = _apply_common_filters(query, start_date, end_date, mode)
    trips = query.all()

    heat_data = {}
    mode_count = {}

    for trip in trips:
        if trip.start_lat is None or trip.start_lng is None:
            continue
        key = (round(trip.start_lat, 3), round(trip.start_lng, 3))
        heat_data[key] = heat_data.get(key, 0) + 1
        if trip.mode:
            mode_count[trip.mode] = mode_count.get(trip.mode, 0) + 1

    formatted_heat = [
        {"lat": k[0], "lng": k[1], "intensity": v}
        for k, v in heat_data.items()
    ]

    return jsonify({"heat_points": formatted_heat, "top_modes": mode_count})

# =============================
# REGION SEARCH
# =============================

@analyst_bp.route("/api/analyst/search-region")
@analyst_required
def search_region():
    query = request.args.get("q", "")
    if not query:
        return jsonify([])

    response = requests.get(
        "https://nominatim.openstreetmap.org/search",
        params={"q": query, "format": "json", "addressdetails": 1, "limit": 5},
        headers={"User-Agent": "SmartTripTracker/1.0"},
        timeout=10
    )
    return jsonify(response.json())

# =============================
# PEAK HOUR BY REGION
# =============================

def _parse_trip_hour(trip):
    """Extract hour from trip.start_time string safely."""
    if not trip.start_time:
        return None
    raw = str(trip.start_time).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt).hour
        except ValueError:
            continue
    return None


@analyst_bp.route("/api/analyst/peak-hour", methods=["POST"])
@analyst_required
def peak_hour():
    data = request.get_json() or {}
    lat = float(data.get("lat", 0))
    lng = float(data.get("lng", 0))
    selected_date = data.get("date")
    delta = 10 / 111

    start_date = data.get("start_date")
    end_date = data.get("end_date")
    mode = data.get("mode")
    region = data.get("region")

    query = Trip.query.filter(
        Trip.start_lat.between(lat - delta, lat + delta),
        Trip.start_lng.between(lng - delta, lng + delta)
    )

    # Legacy single-date filter (kept for backward compat)
    if selected_date and str(selected_date).strip():
        try:
            filter_date = datetime.strptime(selected_date, "%Y-%m-%d").date()
            query = query.filter(Trip.trip_date == filter_date)
        except ValueError:
            pass

    query = _apply_common_filters(query, start_date, end_date, mode, region)
    trips = query.all()

    if not trips:
        return jsonify({"peak_hour": None, "trip_count": 0, "modes": {}})

    hour_count = defaultdict(int)
    mode_count = defaultdict(int)

    for trip in trips:
        if trip.mode:
            mode_count[trip.mode] += 1
        hour = _parse_trip_hour(trip)
        if hour is not None:
            hour_count[hour] += 1

    if not hour_count:
        return jsonify({"peak_hour": None, "trip_count": 0, "modes": dict(mode_count)})

    peak_hour_value = max(hour_count, key=hour_count.get)

    return jsonify({
        "peak_hour": peak_hour_value,
        "trip_count": hour_count[peak_hour_value],
        "modes": dict(mode_count)
    })

# =============================
# MODE DISTRIBUTION
# =============================

@analyst_bp.route("/api/analyst/mode-distribution")
@analyst_required
def mode_distribution():
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    mode = request.args.get("mode")
    region = request.args.get("region")

    query = _apply_common_filters(Trip.query, start_date, end_date, mode, region)
    modes = query.with_entities(Trip.mode, func.count(Trip.mode)).group_by(Trip.mode).all()
    return jsonify(dict(modes))

# =============================
# AI INSIGHTS (LSTM)
# =============================

@analyst_bp.route("/api/analyst/ai-insights", methods=["POST"])
@analyst_required
def ai_insights():
    data = request.get_json() or {}
    lat = float(data.get("lat", 0))
    lng = float(data.get("lng", 0))
    selected_date = data.get("date")
    delta = 10 / 111

    start_date = data.get("start_date")
    end_date = data.get("end_date")
    mode = data.get("mode")
    region = data.get("region")

    query = Trip.query.filter(
        Trip.start_lat.between(lat - delta, lat + delta),
        Trip.start_lng.between(lng - delta, lng + delta)
    )

    if selected_date:
        try:
            filter_date = datetime.strptime(selected_date, "%Y-%m-%d").date()
            query = query.filter(Trip.trip_date == filter_date)
        except ValueError:
            pass

    query = _apply_common_filters(query, start_date, end_date, mode, region)
    trips = query.all()

    if not trips:
        return jsonify({"error": "No data found for this region"})

    result = run_ai_engine(trips)
    return jsonify(result)

# =============================
# AI RETRAIN
# =============================

@analyst_bp.route("/api/analyst/ai-retrain", methods=["POST"])
@analyst_required
def ai_retrain():
    trips = Trip.query.all()
    hour_count = defaultdict(int)

    for trip in trips:
        hour = _parse_trip_hour(trip)
        if hour is not None:
            hour_count[hour] += 1

    hourly_values = [hour_count[h] for h in sorted(hour_count)]

    if len(hourly_values) >= 5:
        train_model(hourly_values)
        return jsonify({"status": "Model retrained successfully"})

    return jsonify({"status": "Not enough data to retrain (need at least 5 data points)"}), 400

# =============================
# SIMULATION
# =============================

@analyst_bp.route("/api/analyst/simulation")
@analyst_required
def simulation():
    total_trips = Trip.query.count()
    projected_growth = total_trips * 1.18
    co2_projection = projected_growth * 0.21

    return jsonify({
        "projected_trips": projected_growth,
        "co2_projection": co2_projection,
        "policy_recommendation": "Increase public transport and optimize signal timings"
    })

# =============================
# HOURLY DISTRIBUTION
# =============================

@analyst_bp.route("/api/analyst/hourly-distribution", methods=["GET"])
@analyst_required
def hourly_distribution():
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    mode = request.args.get("mode")
    region = request.args.get("region")

    hour_count = defaultdict(int)
    trips = _apply_common_filters(Trip.query, start_date, end_date, mode, region).all()

    for trip in trips:
        hour = _parse_trip_hour(trip)
        if hour is not None:
            hour_count[hour] += 1

    return jsonify(dict(sorted(hour_count.items())))

# =============================
# OD MATRIX (ZONE-TO-ZONE FLOWS)
# =============================

@analyst_bp.route("/api/analyst/od-matrix", methods=["GET"])
@analyst_required
def od_matrix():
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    mode = request.args.get("mode")
    region = request.args.get("region")  # "lat,lng,radius_km"

    query = Trip.query.filter(
        Trip.start_lat.isnot(None),
        Trip.start_lng.isnot(None),
        Trip.end_lat.isnot(None),
        Trip.end_lng.isnot(None)
    )

    if start_date:
        try:
            query = query.filter(Trip.trip_date >= datetime.strptime(start_date, "%Y-%m-%d").date())
        except ValueError:
            pass

    if end_date:
        try:
            query = query.filter(Trip.trip_date <= datetime.strptime(end_date, "%Y-%m-%d").date())
        except ValueError:
            pass

    if mode:
        query = query.filter(Trip.mode == mode)

    if region:
        try:
            parts = region.split(",")
            r_lat, r_lng, r_radius = float(parts[0]), float(parts[1]), float(parts[2])
            delta = r_radius / 111
            query = query.filter(
                Trip.start_lat.between(r_lat - delta, r_lat + delta),
                Trip.start_lng.between(r_lng - delta, r_lng + delta)
            )
        except (ValueError, IndexError):
            pass

    trips = query.all()

    # Aggregate zone-to-zone flows; zone = coords rounded to 2 decimal places (~1.1km grid)
    flow_map = defaultdict(lambda: {"count": 0, "mode_breakdown": defaultdict(int)})

    for trip in trips:
        origin = (round(trip.start_lat, 2), round(trip.start_lng, 2))
        dest = (round(trip.end_lat, 2), round(trip.end_lng, 2))
        key = (origin, dest)
        flow_map[key]["count"] += 1
        if trip.mode:
            flow_map[key]["mode_breakdown"][trip.mode] += 1

    result = [
        {
            "origin_zone": {"lat": k[0][0], "lng": k[0][1]},
            "dest_zone": {"lat": k[1][0], "lng": k[1][1]},
            "count": v["count"],
            "mode_breakdown": dict(v["mode_breakdown"])
        }
        for k, v in flow_map.items()
    ]

    return jsonify({"od_matrix": result, "total_flows": len(result)})


# =============================
# COST TREND (DAILY AGGREGATES)
# =============================

@analyst_bp.route("/api/analyst/cost-trend", methods=["GET"])
@analyst_required
def cost_trend():
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    mode = request.args.get("mode")
    region = request.args.get("region")

    base = _apply_common_filters(
        Trip.query.filter(Trip.cost.isnot(None), Trip.trip_date.isnot(None)),
        start_date, end_date, mode, region
    )

    # Aggregate per day using a subquery approach
    trip_ids = [t.id for t in base.with_entities(Trip.id).all()]

    if not trip_ids:
        return jsonify([])

    agg_query = db.session.query(
        Trip.trip_date,
        func.sum(Trip.cost).label("total_cost"),
        func.avg(Trip.cost).label("avg_cost"),
        func.count(Trip.id).label("trip_count"),
    ).filter(Trip.id.in_(trip_ids))

    rows = agg_query.group_by(Trip.trip_date).order_by(Trip.trip_date.asc()).all()

    result = [
        {
            "date": str(row.trip_date),
            "total_cost": round(row.total_cost, 2),
            "avg_cost": round(row.avg_cost, 2),
            "trip_count": row.trip_count,
        }
        for row in rows
    ]

    return jsonify(result)


# =============================
# ANALYTICS DATA (REGIONAL + DATE)
# =============================

@analyst_bp.route("/api/analyst/analytics-data", methods=["POST"])
@analyst_required
def analytics_data():
    data = request.get_json() or {}
    lat = data.get("lat")
    lng = data.get("lng")
    from_date = data.get("from_date")
    to_date = data.get("to_date")

    query = Trip.query

    if lat and lng:
        delta = 10 / 111
        query = query.filter(
            Trip.start_lat.between(float(lat) - delta, float(lat) + delta),
            Trip.start_lng.between(float(lng) - delta, float(lng) + delta)
        )

    if from_date:
        query = query.filter(Trip.trip_date >= from_date)
    if to_date:
        query = query.filter(Trip.trip_date <= to_date)

    trips = query.all()

    mode_count = defaultdict(int)
    hour_count = defaultdict(int)

    for trip in trips:
        if trip.mode:
            mode_count[trip.mode] += 1
        hour = _parse_trip_hour(trip)
        if hour is not None:
            hour_count[hour] += 1

    return jsonify({
        "mode_distribution": dict(mode_count),
        "hourly_distribution": dict(sorted(hour_count.items()))
    })

# =============================
# AI INSIGHTS ENGINE
# =============================

@analyst_bp.route("/api/analyst/insights", methods=["GET"])
@analyst_required
def insights():
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    mode = request.args.get("mode")
    region = request.args.get("region")

    trips = _apply_common_filters(Trip.query, start_date, end_date, mode, region).all()

    results = []
    total_trips = len(trips)

    if total_trips == 0:
        return jsonify([])

    # ── 1. Congestion Insight (OD Matrix) ────────────────────────────────────
    od_count = defaultdict(int)
    for t in trips:
        if t.start_lat and t.end_lat:
            origin = (round(t.start_lat, 2), round(t.start_lng, 2))
            dest   = (round(t.end_lat,   2), round(t.end_lng,   2))
            od_count[(origin, dest)] += 1

    if od_count:
        top_pair, top_count = max(od_count.items(), key=lambda x: x[1])
        ratio = top_count / total_trips
        if ratio > 0.40:
            results.append({
                "type": "congestion",
                "priority": "high",
                "title": "High Congestion Corridor Detected",
                "description": (
                    f"The corridor ({top_pair[0][0]:.2f},{top_pair[0][1]:.2f}) → "
                    f"({top_pair[1][0]:.2f},{top_pair[1][1]:.2f}) accounts for "
                    f"{round(ratio * 100, 1)}% of all trips. Consider traffic management interventions."
                )
            })
        elif ratio > 0.25:
            results.append({
                "type": "congestion",
                "priority": "medium",
                "title": "Moderate Corridor Concentration",
                "description": (
                    f"One corridor handles {round(ratio * 100, 1)}% of trips. "
                    "Monitor for potential congestion build-up."
                )
            })

    # ── 2. Cost Trend Insight ─────────────────────────────────────────────────
    dated_trips = [t for t in trips if t.trip_date and t.cost is not None]
    if dated_trips:
        dated_trips.sort(key=lambda t: t.trip_date)
        mid = len(dated_trips) // 2
        first_half_avg = sum(t.cost for t in dated_trips[:mid]) / mid if mid else 0
        second_half_avg = sum(t.cost for t in dated_trips[mid:]) / (len(dated_trips) - mid) if (len(dated_trips) - mid) else 0

        if first_half_avg > 0:
            change_pct = ((second_half_avg - first_half_avg) / first_half_avg) * 100
            if change_pct > 15:
                results.append({
                    "type": "cost",
                    "priority": "high",
                    "title": "Travel Costs Rising",
                    "description": (
                        f"Average trip cost increased by {round(change_pct, 1)}% in the recent period "
                        f"(₹{round(first_half_avg, 2)} → ₹{round(second_half_avg, 2)}). "
                        "Review fare structures or promote cost-effective modes."
                    )
                })
            elif change_pct < -15:
                results.append({
                    "type": "cost",
                    "priority": "low",
                    "title": "Travel Costs Decreasing",
                    "description": (
                        f"Average trip cost dropped by {round(abs(change_pct), 1)}% "
                        f"(₹{round(first_half_avg, 2)} → ₹{round(second_half_avg, 2)}). "
                        "Positive trend — cost-effective travel is increasing."
                    )
                })

    # ── 3. Revenue vs Cost / Trip Frequency Insight ───────────────────────────
    if dated_trips and len(dated_trips) >= 4:
        q1 = dated_trips[:len(dated_trips)//2]
        q2 = dated_trips[len(dated_trips)//2:]
        avg_cost_q1 = sum(t.cost for t in q1) / len(q1)
        avg_cost_q2 = sum(t.cost for t in q2) / len(q2)
        if avg_cost_q2 > avg_cost_q1 * 1.10 and len(q2) < len(q1):
            results.append({
                "type": "revenue",
                "priority": "high",
                "title": "Rising Costs Reducing Trip Frequency",
                "description": (
                    f"Trip count fell from {len(q1)} to {len(q2)} while average cost rose "
                    f"from ₹{round(avg_cost_q1, 2)} to ₹{round(avg_cost_q2, 2)}. "
                    "Higher fares may be deterring travel."
                )
            })

    # ── 4. Trip Trend — Peak Day Insight ─────────────────────────────────────
    day_count = defaultdict(int)
    DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    for t in trips:
        if t.trip_date:
            day_count[t.trip_date.weekday()] += 1

    if day_count:
        peak_day_idx = max(day_count, key=day_count.get)
        peak_day_trips = day_count[peak_day_idx]
        avg_daily = total_trips / 7
        if peak_day_trips > avg_daily * 1.5:
            results.append({
                "type": "trend",
                "priority": "medium",
                "title": f"Peak Demand on {DAY_NAMES[peak_day_idx]}",
                "description": (
                    f"{DAY_NAMES[peak_day_idx]} records {peak_day_trips} trips — "
                    f"{round((peak_day_trips / avg_daily - 1) * 100, 1)}% above daily average. "
                    "Consider increasing transport capacity on this day."
                )
            })

    # ── 5. Mode Optimization Insight ─────────────────────────────────────────
    mode_count = defaultdict(int)
    for t in trips:
        if t.mode:
            mode_count[t.mode.lower()] += 1

    if mode_count:
        dominant_mode, dominant_count = max(mode_count.items(), key=lambda x: x[1])
        dominant_pct = (dominant_count / total_trips) * 100
        if dominant_pct > 60:
            alt = "public transport (bus/train)" if dominant_mode in ("car", "bike") else "shared mobility options"
            results.append({
                "type": "mode",
                "priority": "medium",
                "title": f"High {dominant_mode.title()} Usage Detected",
                "description": (
                    f"{round(dominant_pct, 1)}% of trips use {dominant_mode}. "
                    f"Promoting {alt} could reduce congestion and emissions."
                )
            })

    # ── 6. Low Activity Insight ───────────────────────────────────────────────
    if total_trips < 5:
        results.append({
            "type": "low_activity",
            "priority": "low",
            "title": "Low Travel Activity",
            "description": (
                f"Only {total_trips} trip(s) recorded for the selected filters. "
                "Insufficient data for reliable trend analysis — broaden the date range or region."
            )
        })

    # ── 7. Recommendation: Off-peak suggestion ────────────────────────────────
    hour_count = defaultdict(int)
    for t in trips:
        h = _parse_trip_hour(t)
        if h is not None:
            hour_count[h] += 1

    if hour_count:
        peak_h = max(hour_count, key=hour_count.get)
        if 7 <= peak_h <= 10 or 17 <= peak_h <= 20:
            off_peak = "early morning (before 7am) or after 8pm" if peak_h <= 10 else "before 5pm or after 9pm"
            results.append({
                "type": "recommendation",
                "priority": "low",
                "title": "Off-Peak Travel Recommended",
                "description": (
                    f"Peak travel occurs at {peak_h}:00. Travellers can save time by travelling "
                    f"during {off_peak} when congestion is lower."
                )
            })

    return jsonify(results)


# =============================
# ANALYST EXPORT (Req 20)
# =============================

@analyst_bp.route("/api/analyst/export", methods=["GET"])
@analyst_required
def analyst_export():
    """Export anonymised trip records as CSV matching the current filter selection.

    Query params: region, start_date, end_date, mode
    Anonymisation: user_id stripped, coordinates rounded to 3 decimal places.
    Audit log: records analyst id, timestamp, and applied filters.
    """
    # Decode analyst identity from token for audit log
    token = request.headers.get("Authorization", "")
    try:
        decoded = jwt.decode(token, current_app.config["SECRET_KEY"], algorithms=["HS256"])
        analyst_id = decoded.get("analyst_id") or decoded.get("email") or "analyst"
    except Exception:
        analyst_id = "analyst"

    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    mode = request.args.get("mode")
    region = request.args.get("region")

    query = _apply_common_filters(Trip.query, start_date, end_date, mode, region)
    trips = query.all()

    # Build CSV in memory
    output = io.StringIO()
    writer = csv.writer(output)

    # Header row — user_id intentionally omitted for anonymisation
    writer.writerow([
        "trip_no", "trip_date", "start_time", "end_time",
        "start_lat", "start_lng", "end_lat", "end_lng",
        "distance", "duration", "mode", "purpose",
        "cost", "companions", "frequency",
        "ml_mode", "confidence_score",
        "is_incomplete", "has_gps_gap", "data_quality_flag",
    ])

    for t in trips:
        writer.writerow([
            t.trip_no,
            t.trip_date,
            t.start_time,
            t.end_time,
            round(t.start_lat, 3) if t.start_lat is not None else "",
            round(t.start_lng, 3) if t.start_lng is not None else "",
            round(t.end_lat, 3) if t.end_lat is not None else "",
            round(t.end_lng, 3) if t.end_lng is not None else "",
            t.distance,
            t.duration,
            t.mode,
            t.purpose,
            t.cost,
            t.companions,
            t.frequency,
            t.ml_mode,
            t.confidence_score,
            t.is_incomplete,
            t.has_gps_gap,
            t.data_quality_flag,
        ])

    # Write audit log entry (Req 20.3) — records export event with analyst id,
    # timestamp, and applied filters via the app logger for full detail.
    applied_filters = {
        "region": region,
        "start_date": start_date,
        "end_date": end_date,
        "mode": mode,
    }
    write_audit(
        operation="EXPORT",
        table_name="trip",
        record_id=0,
        user_id=None,
        autocommit=True,
    )
    current_app.logger.info(
        "Analyst export: analyst=%s, timestamp=%s, filters=%s, rows=%d",
        analyst_id,
        datetime.utcnow().isoformat(),
        applied_filters,
        len(trips),
    )

    csv_bytes = output.getvalue().encode("utf-8")
    timestamp_str = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"trips_export_{timestamp_str}.csv"

    return Response(
        csv_bytes,
        status=200,
        mimetype="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": "text/csv; charset=utf-8",
        },
    )
