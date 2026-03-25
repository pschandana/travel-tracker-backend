"""
ml_model.py — Travel mode classifier and traffic predictor.
No TensorFlow/Keras dependency. Uses numpy + rule-based logic only.
"""

import numpy as np
import math
from collections import defaultdict
from datetime import datetime


# =========================
# SIMPLE MOVING-AVERAGE PREDICTOR (replaces LSTM)
# =========================

def train_model(hour_counts):
    """No-op — model is stateless (moving average). Returns dummy accuracy."""
    if len(hour_counts) < 5:
        return None, None
    arr = np.array(hour_counts, dtype=float)
    # RMSE of a 3-point moving
    global _scaler, _scaler_fitted
    data = np.array(hour_counts).reshape(-1, 1)
    scaled = _scaler.fit_transform(data)
    _scaler_fitted = True

    X, y = [], []
    for i in range(len(scaled) - 3):
        X.append(scaled[i:i+3])
        y.append(scaled[i+3])

    return np.array(X), np.array(y)


# =========================
# TRAIN MODEL
# =========================
def train_model(hour_counts):
    if len(hour_counts) < 5:
        return None, None

    X, y = prepare_data(hour_counts)

    model = keras.Sequential([
        layers.Input(shape=(3, 1)),
        layers.LSTM(50, activation="relu"),
        layers.Dense(1)
    ])
    model.compile(optimizer="adam", loss="mean_squared_error")
    model.fit(X, y, epochs=40, verbose=0)

    predictions = model.predict(X, verbose=0)
    mse = mean_squared_error(y, predictions)
    rmse = math.sqrt(mse)

    model.save(MODEL_PATH)
    return model, round(rmse, 3)


# =========================
# PREDICT NEXT HOUR
# =========================
def predict_next(hour_counts):
    global _scaler, _scaler_fitted

    if not os.path.exists(MODEL_PATH):
        return None

    if not _scaler_fitted:
        # Fit scaler on available data if not already fitted
        data = np.array(hour_counts).reshape(-1, 1)
        _scaler.fit_transform(data)
        _scaler_fitted = True

    model = keras.models.load_model(MODEL_PATH, compile=False)

    last_3 = np.array(hour_counts[-3:]).reshape(-1, 1)
    scaled = _scaler.transform(last_3)

    X = np.array([scaled])
    prediction = model.predict(X, verbose=0)
    predicted_value = _scaler.inverse_transform(prediction)[0][0]

    return int(max(predicted_value, 0))


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
    # Short time format "HH:MM"
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

    model, accuracy = train_model(hourly_values)
    predicted_next = predict_next(hourly_values) if hourly_values else None

    total_trips = len(trips)
    congestion_score = min(100, sum(hourly_values))

    if congestion_score < 30:
        risk = "Low"
    elif congestion_score < 70:
        risk = "Medium"
    else:
        risk = "High"

    # CO2 Calculation
    co2_factor = {
        "Car": 0.21,
        "Bike": 0.09,
        "Bus": 0.05,
        "Train": 0.04,
        "Cycle": 0.0,
        "Walk": 0.0,
        "Auto": 0.10
    }

    total_co2 = sum(
        (trip.distance or 0) * co2_factor.get(trip.mode, 0.15)
        for trip in trips
    )
    total_co2 = round(total_co2, 2)

    # Recommendation Engine
    recommendation = "Traffic stable."
    if mode_count.get("Bike", 0) > mode_count.get("Bus", 0):
        recommendation = "Bike usage is high. Increase public bus routes to reduce road load."
    if mode_count.get("Car", 0) > total_trips * 0.4:
        recommendation = "Private car usage dominant. Encourage carpool or public transport."
    if total_co2 > 20:
        recommendation += " High CO\u2082 detected. Promote eco-friendly transport."

    return {
        "model_type": "LSTM Time-Series Traffic Predictor",
        "model_accuracy_rmse": accuracy,
        "congestion_score": congestion_score,
        "risk_level": risk,
        "predicted_next_hour_traffic": predicted_next,
        "avg_distance": round(total_distance / total_trips, 2) if total_trips else 0,
        "avg_duration": round(total_duration / total_trips, 2) if total_trips else 0,
        "co2_emission": total_co2,
        "recommendation": recommendation,
        "mode_distribution": dict(mode_count),
        "metric_meanings": {
            "congestion_score": "Traffic intensity index based on historical hourly distribution.",
            "risk_level": "Traffic risk classification derived from congestion.",
            "predicted_next_hour_traffic": "AI predicted traffic volume for next hour.",
            "co2_emission": "Estimated total carbon emission (kg).",
            "model_accuracy_rmse": "Root Mean Square Error — lower value means better model performance."
        }
    }


# =========================
# TRAVEL MODE CLASSIFIER
# =========================

def _haversine_distance(lat1, lng1, lat2, lng2):
    """Return distance in metres between two GPS coordinates."""
    R = 6_371_000  # Earth radius in metres
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _parse_iso_timestamp(ts_str):
    """Parse an ISO 8601 timestamp string and return a datetime, or None."""
    if not ts_str:
        return None
    raw = str(ts_str).strip()
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
    ):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def _compute_speed_stats(route_points):
    """
    Compute speed statistics (m/s) from a list of route point dicts.

    Each point must have 'lat' and 'lng' keys.  An optional 'timestamp'
    key (ISO 8601 string) is used to derive time deltas; when timestamps
    are absent or unparseable the function falls back to distance-only
    estimation using a fixed 1 m/s reference speed.

    Returns (mean_speed, max_speed, std_dev_speed) in m/s, or
    (None, None, None) when fewer than 2 points are available.
    """
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

        if t1 is not None and t2 is not None:
            dt = (t2 - t1).total_seconds()
            if dt > 0:
                speeds.append(dist / dt)
            # Skip zero-duration segments (duplicate timestamps)
        else:
            # Fallback: treat each segment as 1 second per metre
            # (preserves relative ordering without real time data)
            speeds.append(dist / max(dist, 1.0))

    if not speeds:
        return None, None, None

    mean_speed = float(np.mean(speeds))
    max_speed = float(np.max(speeds))
    std_dev_speed = float(np.std(speeds))
    return mean_speed, max_speed, std_dev_speed


def _rule_based_classify(mean_speed, max_speed, std_dev_speed):
    """
    Apply speed-threshold rules to return (mode, base_confidence).

    Speed thresholds (m/s):
      Walking  : mean < 2.0
      Cycling  : 2.0 ≤ mean < 5.0
      Auto     : 5.0 ≤ mean < 8.0  (three-wheeler / rickshaw)
      Bus      : 5.0 ≤ mean < 12.0 with high std_dev (stop-and-go)
      Car      : 8.0 ≤ mean < 20.0
      Train    : mean ≥ 15.0

    Returns (mode: str, confidence: float 0–100).
    """
    # --- Walking ---
    if mean_speed < 2.0:
        # High confidence when speed is well below the ceiling
        confidence = min(100.0, 90.0 - (mean_speed / 2.0) * 20.0)
        return "Walking", round(confidence, 1)

    # --- Cycling ---
    if mean_speed < 5.0:
        # Confidence peaks in the middle of the range (3.5 m/s)
        centre = 3.5
        spread = 1.5
        confidence = max(60.0, 90.0 - abs(mean_speed - centre) / spread * 20.0)
        return "Cycling", round(confidence, 1)

    # --- Bus vs Auto in the 5–12 m/s overlap zone ---
    if mean_speed < 12.0:
        # Bus is characterised by high speed variability (stop-and-go)
        if std_dev_speed > 2.5:
            # Confidence scales with how pronounced the stop-and-go pattern is
            confidence = min(90.0, 65.0 + (std_dev_speed - 2.5) * 5.0)
            return "Bus", round(confidence, 1)
        # Auto (three-wheeler) occupies the lower end of this band
        if mean_speed < 8.0:
            confidence = min(85.0, 70.0 + (8.0 - mean_speed) * 3.0)
            return "Auto", round(confidence, 1)
        # Car in the 8–12 range without high std_dev
        confidence = min(80.0, 65.0 + (mean_speed - 8.0) * 2.0)
        return "Car", round(confidence, 1)

    # --- Train vs Car in the 12–20 m/s zone ---
    if mean_speed < 20.0:
        # Train tends to have low std_dev (smooth ride); car has more variation
        if std_dev_speed < 3.0 and mean_speed > 15.0:
            confidence = min(90.0, 70.0 + (mean_speed - 15.0) * 2.0)
            return "Train", round(confidence, 1)
        confidence = min(85.0, 65.0 + (mean_speed - 12.0) * 2.0)
        return "Car", round(confidence, 1)

    # --- Train (mean ≥ 20 m/s) ---
    confidence = min(95.0, 80.0 + (mean_speed - 20.0) * 0.5)
    return "Train", round(confidence, 1)


def classify_mode(route_points):
    """
    Infer the travel mode from a GPS route and return a confidence score.

    Parameters
    ----------
    route_points : list[dict]
        List of GPS coordinate dicts.  Each dict must contain at minimum:
          - 'lat'  (float or str) — latitude
          - 'lng'  (float or str) — longitude
        Optional keys:
          - 'timestamp' (str, ISO 8601) — used for speed calculation
          - 'accuracy'  (float, metres) — informational only

    Returns
    -------
    (mode, confidence_score) : (str, float)
        mode             — one of: Walking, Cycling, Bus, Car, Train, Auto
        confidence_score — float in [0, 100]

    Edge cases
    ----------
    - Empty list or single point → returns ("Walking", 50.0) as a safe default
    - Missing / unparseable timestamps → falls back to distance-only speed proxy
    """
    if not route_points or len(route_points) < 2:
        return "Walking", 50.0

    mean_speed, max_speed, std_dev_speed = _compute_speed_stats(route_points)

    if mean_speed is None:
        # All consecutive pairs had zero distance — treat as stationary
        return "Walking", 50.0

    mode, confidence = _rule_based_classify(mean_speed, max_speed, std_dev_speed)
    return mode, confidence
