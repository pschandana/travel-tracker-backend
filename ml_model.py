"""
ml_model.py — Travel mode classifier and traffic predictor.
Pure Python — no numpy, tensorflow, or sklearn required.
"""

import math
from collections import defaultdict
from datetime import datetime


# =========================
# SIMPLE MOVING-AVERAGE PREDICTOR
# =========================

def train_model(hour_counts):
    """No-op stub — returns None for compatibility."""
    return None, None


def predict_next(hour_counts):
    """Predict next hour traffic using 3-point moving average."""
    if len(hour_counts) < 3:
        return None
    return int(sum(hour_counts[-3:]) / 3)


# =========================
# PARSE TRIP HOUR
# =========================

def _parse_hour(start_time):
    if not start_time:
        return None
    raw = str(start_time).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt).hour
        except ValueError:
            continue
    if ":" in raw and len(raw) <= 8:
        try:
            return int(raw.split(":")[0])
        except ValueError:
            pass
    return None


# =========================
# FULL AI ENGINE
# =========================

def run_ai_engine(trips):
    if not trips:
        return None

    hour_count = defaultdict(int)
    mode_count = defaultdict(int)
    total_distance = 0
    total_duration = 0

    for trip in trips:
        hour = _parse_hour(trip.start_time)
        if hour is not None:
            hour_count[hour] += 1
        if trip.mode:
            mode_count[trip.mode] += 1
        total_distance += trip.distance or 0
        total_duration += trip.duration or 0

    hourly_values = [hour_count[h] for h in sorted(hour_count)]
    predicted_next = predict_next(hourly_values) if hourly_values else None

    total_trips = len(trips)
    congestion_score = min(100, sum(hourly_values))

    if congestion_score < 30:
        risk = "Low"
    elif congestion_score < 70:
        risk = "Medium"
    else:
        risk = "High"

    co2_factor = {
        "Car": 0.21, "Bike": 0.09, "Bus": 0.05,
        "Train": 0.04, "Cycle": 0.0, "Walk": 0.0, "Auto": 0.10
    }
    total_co2 = round(sum(
        (t.distance or 0) * co2_factor.get(t.mode, 0.15) for t in trips
    ), 2)

    recommendation = "Traffic stable."
    if mode_count.get("Bike", 0) > mode_count.get("Bus", 0):
        recommendation = "Bike usage is high. Increase public bus routes."
    if mode_count.get("Car", 0) > total_trips * 0.4:
        recommendation = "Private car usage dominant. Encourage carpool or public transport."
    if total_co2 > 20:
        recommendation += " High CO\u2082 detected. Promote eco-friendly transport."

    return {
        "model_type": "Moving Average Traffic Predictor",
        "model_accuracy_rmse": None,
        "congestion_score": congestion_score,
        "risk_level": risk,
        "predicted_next_hour_traffic": predicted_next,
        "avg_distance": round(total_distance / total_trips, 2) if total_trips else 0,
        "avg_duration": round(total_duration / total_trips, 2) if total_trips else 0,
        "co2_emission": total_co2,
        "recommendation": recommendation,
        "mode_distribution": dict(mode_count),
    }


# =========================
# TRAVEL MODE CLASSIFIER (pure Python)
# =========================

def _haversine_distance(lat1, lng1, lat2, lng2):
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _parse_iso_timestamp(ts_str):
    if not ts_str:
        return None
    raw = str(ts_str).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def _compute_speed_stats(route_points):
    if len(route_points) < 2:
        return None, None, None

    speeds = []
    for i in range(1, len(route_points)):
        p1, p2 = route_points[i - 1], route_points[i]
        dist = _haversine_distance(
            float(p1["lat"]), float(p1["lng"]),
            float(p2["lat"]), float(p2["lng"]),
        )
        t1 = _parse_iso_timestamp(p1.get("timestamp"))
        t2 = _parse_iso_timestamp(p2.get("timestamp"))
        if t1 and t2:
            dt = (t2 - t1).total_seconds()
            if dt > 0:
                speeds.append(dist / dt)
        else:
            speeds.append(dist / max(dist, 1.0))

    if not speeds:
        return None, None, None

    mean_speed = sum(speeds) / len(speeds)
    max_speed = max(speeds)
    variance = sum((s - mean_speed) ** 2 for s in speeds) / len(speeds)
    std_dev_speed = math.sqrt(variance)
    return mean_speed, max_speed, std_dev_speed


def _rule_based_classify(mean_speed, max_speed, std_dev_speed):
    if mean_speed < 2.0:
        confidence = min(100.0, 90.0 - (mean_speed / 2.0) * 20.0)
        return "Walking", round(confidence, 1)
    if mean_speed < 5.0:
        centre, spread = 3.5, 1.5
        confidence = max(60.0, 90.0 - abs(mean_speed - centre) / spread * 20.0)
        return "Cycling", round(confidence, 1)
    if mean_speed < 12.0:
        if std_dev_speed > 2.5:
            confidence = min(90.0, 65.0 + (std_dev_speed - 2.5) * 5.0)
            return "Bus", round(confidence, 1)
        if mean_speed < 8.0:
            confidence = min(85.0, 70.0 + (8.0 - mean_speed) * 3.0)
            return "Auto", round(confidence, 1)
        confidence = min(80.0, 65.0 + (mean_speed - 8.0) * 2.0)
        return "Car", round(confidence, 1)
    if mean_speed < 20.0:
        if std_dev_speed < 3.0 and mean_speed > 15.0:
            confidence = min(90.0, 70.0 + (mean_speed - 15.0) * 2.0)
            return "Train", round(confidence, 1)
        confidence = min(85.0, 65.0 + (mean_speed - 12.0) * 2.0)
        return "Car", round(confidence, 1)
    confidence = min(95.0, 80.0 + (mean_speed - 20.0) * 0.5)
    return "Train", round(confidence, 1)


def classify_mode(route_points):
    if not route_points or len(route_points) < 2:
        return "Walking", 50.0
    mean_speed, max_speed, std_dev_speed = _compute_speed_stats(route_points)
    if mean_speed is None:
        return "Walking", 50.0
    return _rule_based_classify(mean_speed, max_speed, std_dev_speed)
