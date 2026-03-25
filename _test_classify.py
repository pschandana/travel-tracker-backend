"""Quick smoke test for classify_mode — run from backend/ directory."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from ml_model import classify_mode
from datetime import datetime, timedelta

base = datetime(2024, 1, 1, 8, 0, 0)
DEG_PER_M = 1 / 111_000

def make_points(speed_ms, n=6):
    pts = []
    for i in range(n):
        ts = (base + timedelta(seconds=i * 10)).isoformat()
        lat = 10.0 + i * speed_ms * 10 * DEG_PER_M
        pts.append({"lat": lat, "lng": 76.0, "timestamp": ts})
    return pts

VALID_MODES = {"Walking", "Cycling", "Bus", "Car", "Train", "Auto"}

def check(label, result, expected_mode=None):
    mode, conf = result
    assert mode in VALID_MODES, f"{label}: invalid mode '{mode}'"
    assert 0.0 <= conf <= 100.0, f"{label}: confidence {conf} out of range"
    if expected_mode:
        assert mode == expected_mode, f"{label}: expected {expected_mode}, got {mode} (conf={conf})"
    print(f"  OK  {label}: ({mode}, {conf})")

print("Running classify_mode smoke tests...")

# Edge cases
check("Empty list",  classify_mode([]), "Walking")
check("Single point", classify_mode([{"lat": 10.0, "lng": 76.0}]), "Walking")

# Mode classification
check("Walking  1.0 m/s", classify_mode(make_points(1.0)), "Walking")
check("Cycling  3.5 m/s", classify_mode(make_points(3.5)), "Cycling")
check("Auto     6.0 m/s", classify_mode(make_points(6.0)), "Auto")
check("Car     12.0 m/s", classify_mode(make_points(12.0)), "Car")
check("Train   25.0 m/s", classify_mode(make_points(25.0)), "Train")

# Bus: alternating slow/fast → high std_dev
bus_pts = []
lat = 10.0
t = base
for s in [1.0, 12.0, 1.0, 12.0, 1.0, 12.0, 1.0]:
    bus_pts.append({"lat": lat, "lng": 76.0, "timestamp": t.isoformat()})
    lat += s * 10 * DEG_PER_M
    t += timedelta(seconds=10)
check("Bus stop-and-go", classify_mode(bus_pts), "Bus")

# No timestamps — fallback path
no_ts = [{"lat": 10.0, "lng": 76.0}, {"lat": 10.001, "lng": 76.0}]
mode, conf = classify_mode(no_ts)
assert mode in VALID_MODES
assert 0 <= conf <= 100
print(f"  OK  No timestamps: ({mode}, {conf})")

print("\nAll tests passed.")
