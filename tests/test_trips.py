"""
Unit tests for trip functionality.

Covers:
- Trip creation and retrieval (POST /api/trips, GET /api/trips)
- Distance calculation returns positive values
- GPS filtering removes invalid points (accuracy > 50m threshold)
- Trip update (PATCH /api/trips/:id)
- Trip chain formation logic (grouping trips within 60 minutes)
"""

import sys
import os
import pytest
from datetime import datetime, timedelta, timezone

# Ensure the backend root is on the path so imports work
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

GPS_ACCURACY_THRESHOLD = 50  # metres — matches Req 27 / design P5


def filter_gps_points(points):
    """
    Filter GPS readings, removing any with accuracy > GPS_ACCURACY_THRESHOLD.
    This mirrors the frontend useTripTracking logic (Req 27 / P5).
    """
    return [p for p in points if p.get("accuracy", 0) <= GPS_ACCURACY_THRESHOLD]


def haversine_km(lat1, lng1, lat2, lng2):
    """Return the Haversine distance in km between two lat/lng points."""
    import math
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def compute_route_distance(route):
    """Sum Haversine distances between consecutive route points."""
    if not route or len(route) < 2:
        return 0.0
    total = 0.0
    for i in range(1, len(route)):
        total += haversine_km(
            route[i - 1]["lat"], route[i - 1]["lng"],
            route[i]["lat"], route[i]["lng"],
        )
    return total


# ---------------------------------------------------------------------------
# App fixture (mirrors test_auth.py)
# ---------------------------------------------------------------------------

@pytest.fixture
def app():
    """Create a Flask app configured for testing with an in-memory SQLite DB."""
    from app import app as flask_app
    from flask_bcrypt import Bcrypt

    flask_app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        JWT_SECRET_KEY="test-jwt-secret",
        SECRET_KEY="test-secret",
        MAIL_SUPPRESS_SEND=True,
        MAIL_SERVER="localhost",
        MAIL_PORT=25,
        MAIL_USE_TLS=False,
        MAIL_USERNAME="test@example.com",
        MAIL_PASSWORD="",
    )

    b = Bcrypt()
    b.init_app(flask_app)
    flask_app.extensions["bcrypt"] = b

    from models import db
    with flask_app.app_context():
        db.create_all()
        yield flask_app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


# ---------------------------------------------------------------------------
# Helper: create a verified user and return a JWT token
# ---------------------------------------------------------------------------

def _create_user_and_token(app, client, email="tripper@example.com", password="TripPass1"):
    """Insert a verified user and return their JWT token."""
    from models import db, User

    b = app.extensions["bcrypt"]
    hashed = b.generate_password_hash(password).decode("utf-8")

    with app.app_context():
        user = User(
            name="Trip Tester",
            email=email,
            mobile="8888888888",
            place="TestCity",
            password=hashed,
            is_verified=True,
        )
        db.session.add(user)
        db.session.commit()

    resp = client.post("/api/login", json={"email": email, "password": password})
    return resp.get_json()["token"]


# ---------------------------------------------------------------------------
# Helper: build a minimal trip payload
# ---------------------------------------------------------------------------

def _trip_payload(**overrides):
    base = {
        "start_lat": 10.0,
        "start_lng": 76.0,
        "end_lat": 10.1,
        "end_lng": 76.1,
        "start_time": "2024-01-15T08:00:00",
        "end_time": "2024-01-15T08:30:00",
        "distance": 5.2,
        "duration": 30.0,
        "mode": "Bus",
        "purpose": "Work",
        "cost": 20.0,
        "companions": 0,
        "route": [
            {"lat": 10.0, "lng": 76.0},
            {"lat": 10.05, "lng": 76.05},
            {"lat": 10.1, "lng": 76.1},
        ],
    }
    base.update(overrides)
    return base


# ===========================================================================
# 1. Trip Creation and Retrieval
# ===========================================================================

class TestTripCreationAndRetrieval:
    """Verify POST /api/trips and GET /api/trips."""

    def test_create_trip_returns_200(self, client, app):
        """POST /api/trips with valid data returns 200 and 'Trip saved'."""
        token = _create_user_and_token(app, client)
        resp = client.post(
            "/api/trips",
            json=_trip_payload(),
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.get_json()["msg"] == "Trip saved"

    def test_create_trip_requires_auth(self, client, app):
        """POST /api/trips without a token returns 401."""
        resp = client.post("/api/trips", json=_trip_payload())
        assert resp.status_code == 401

    def test_get_trips_returns_list(self, client, app):
        """GET /api/trips returns a list containing the created trip."""
        token = _create_user_and_token(app, client, email="getter@example.com")
        client.post(
            "/api/trips",
            json=_trip_payload(),
            headers={"Authorization": f"Bearer {token}"},
        )
        resp = client.get("/api/trips", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert "trips" in data
        assert len(data["trips"]) == 1

    def test_get_trips_returns_correct_fields(self, client, app):
        """GET /api/trips trip objects include expected fields."""
        token = _create_user_and_token(app, client, email="fields@example.com")
        client.post(
            "/api/trips",
            json=_trip_payload(mode="Car", purpose="Shopping"),
            headers={"Authorization": f"Bearer {token}"},
        )
        resp = client.get("/api/trips", headers={"Authorization": f"Bearer {token}"})
        trip = resp.get_json()["trips"][0]
        assert trip["mode"] == "Car"
        assert trip["purpose"] == "Shopping"
        assert trip["distance"] == 5.2

    def test_get_trips_only_returns_own_trips(self, client, app):
        """GET /api/trips does not return trips belonging to another user."""
        token_a = _create_user_and_token(app, client, email="usera@example.com")
        token_b = _create_user_and_token(app, client, email="userb@example.com")

        # User A creates a trip
        client.post(
            "/api/trips",
            json=_trip_payload(),
            headers={"Authorization": f"Bearer {token_a}"},
        )

        # User B should see zero trips
        resp = client.get("/api/trips", headers={"Authorization": f"Bearer {token_b}"})
        assert len(resp.get_json()["trips"]) == 0

    def test_create_multiple_trips_all_retrieved(self, client, app):
        """Creating two trips results in both being returned by GET /api/trips."""
        token = _create_user_and_token(app, client, email="multi@example.com")
        headers = {"Authorization": f"Bearer {token}"}

        client.post("/api/trips", json=_trip_payload(start_time="2024-01-15T08:00:00"), headers=headers)
        client.post("/api/trips", json=_trip_payload(start_time="2024-01-15T10:00:00"), headers=headers)

        resp = client.get("/api/trips", headers=headers)
        assert len(resp.get_json()["trips"]) == 2


# ===========================================================================
# 2. Distance Calculation
# ===========================================================================

class TestDistanceCalculation:
    """Verify that distance calculations return positive values (P4)."""

    def test_haversine_returns_positive(self):
        """Haversine distance between two distinct points is positive."""
        d = haversine_km(10.0, 76.0, 10.1, 76.1)
        assert d > 0

    def test_haversine_same_point_is_zero(self):
        """Haversine distance from a point to itself is zero."""
        d = haversine_km(10.0, 76.0, 10.0, 76.0)
        assert d == pytest.approx(0.0, abs=1e-9)

    def test_route_distance_positive_for_valid_route(self):
        """compute_route_distance returns a positive value for a multi-point route."""
        route = [
            {"lat": 10.0, "lng": 76.0},
            {"lat": 10.05, "lng": 76.05},
            {"lat": 10.1, "lng": 76.1},
        ]
        d = compute_route_distance(route)
        assert d > 0

    def test_route_distance_zero_for_single_point(self):
        """compute_route_distance returns 0 for a single-point route."""
        route = [{"lat": 10.0, "lng": 76.0}]
        assert compute_route_distance(route) == 0.0

    def test_route_distance_zero_for_empty_route(self):
        """compute_route_distance returns 0 for an empty route."""
        assert compute_route_distance([]) == 0.0

    def test_route_distance_equals_sum_of_legs(self):
        """Route distance equals the sum of individual leg distances."""
        p1 = {"lat": 10.0, "lng": 76.0}
        p2 = {"lat": 10.05, "lng": 76.05}
        p3 = {"lat": 10.1, "lng": 76.1}
        route = [p1, p2, p3]
        expected = haversine_km(p1["lat"], p1["lng"], p2["lat"], p2["lng"]) + \
                   haversine_km(p2["lat"], p2["lng"], p3["lat"], p3["lng"])
        assert compute_route_distance(route) == pytest.approx(expected, rel=1e-6)

    def test_stored_trip_distance_is_positive(self, client, app):
        """A trip saved with a positive distance value is stored and returned correctly."""
        token = _create_user_and_token(app, client, email="dist@example.com")
        client.post(
            "/api/trips",
            json=_trip_payload(distance=12.5),
            headers={"Authorization": f"Bearer {token}"},
        )
        resp = client.get("/api/trips", headers={"Authorization": f"Bearer {token}"})
        trip = resp.get_json()["trips"][0]
        assert trip["distance"] > 0
        assert trip["distance"] == 12.5


# ===========================================================================
# 3. GPS Accuracy Filtering
# ===========================================================================

class TestGPSFiltering:
    """Verify GPS accuracy filtering removes invalid points (P5)."""

    def test_accurate_points_are_kept(self):
        """Points with accuracy ≤ 50m are retained."""
        points = [
            {"lat": 10.0, "lng": 76.0, "accuracy": 5},
            {"lat": 10.01, "lng": 76.01, "accuracy": 50},
        ]
        result = filter_gps_points(points)
        assert len(result) == 2

    def test_inaccurate_points_are_removed(self):
        """Points with accuracy > 50m are filtered out."""
        points = [
            {"lat": 10.0, "lng": 76.0, "accuracy": 51},
            {"lat": 10.01, "lng": 76.01, "accuracy": 100},
        ]
        result = filter_gps_points(points)
        assert len(result) == 0

    def test_mixed_points_only_keeps_accurate(self):
        """Only points with accuracy ≤ 50m survive filtering."""
        points = [
            {"lat": 10.0, "lng": 76.0, "accuracy": 10},   # keep
            {"lat": 10.01, "lng": 76.01, "accuracy": 75},  # remove
            {"lat": 10.02, "lng": 76.02, "accuracy": 30},  # keep
            {"lat": 10.03, "lng": 76.03, "accuracy": 51},  # remove
        ]
        result = filter_gps_points(points)
        assert len(result) == 2
        assert all(p["accuracy"] <= GPS_ACCURACY_THRESHOLD for p in result)

    def test_boundary_accuracy_50_is_kept(self):
        """A point with accuracy exactly 50m is kept (boundary inclusive)."""
        points = [{"lat": 10.0, "lng": 76.0, "accuracy": 50}]
        result = filter_gps_points(points)
        assert len(result) == 1

    def test_boundary_accuracy_51_is_removed(self):
        """A point with accuracy 51m is removed (just above threshold)."""
        points = [{"lat": 10.0, "lng": 76.0, "accuracy": 51}]
        result = filter_gps_points(points)
        assert len(result) == 0

    def test_empty_list_returns_empty(self):
        """Filtering an empty list returns an empty list."""
        assert filter_gps_points([]) == []

    def test_no_inaccurate_points_unchanged(self):
        """A list with all accurate points is returned unchanged."""
        points = [
            {"lat": 10.0, "lng": 76.0, "accuracy": 5},
            {"lat": 10.01, "lng": 76.01, "accuracy": 20},
        ]
        result = filter_gps_points(points)
        assert result == points


# ===========================================================================
# 4. Trip Update (PATCH /api/trips/:id)
# ===========================================================================

class TestTripUpdate:
    """Verify PATCH /api/trips/:id updates trip fields correctly."""

    def _create_trip_and_get_id(self, client, token):
        """Create a trip and return its database id."""
        client.post(
            "/api/trips",
            json=_trip_payload(),
            headers={"Authorization": f"Bearer {token}"},
        )
        resp = client.get("/api/trips", headers={"Authorization": f"Bearer {token}"})
        return resp.get_json()["trips"][0]["id"]

    def test_patch_updates_purpose(self, client, app):
        """PATCH /api/trips/:id updates the purpose field."""
        token = _create_user_and_token(app, client, email="patch1@example.com")
        trip_id = self._create_trip_and_get_id(client, token)

        resp = client.patch(
            f"/api/trips/{trip_id}",
            json={"purpose": "Shopping"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.get_json()["purpose"] == "Shopping"

    def test_patch_updates_cost(self, client, app):
        """PATCH /api/trips/:id updates the cost field."""
        token = _create_user_and_token(app, client, email="patch2@example.com")
        trip_id = self._create_trip_and_get_id(client, token)

        resp = client.patch(
            f"/api/trips/{trip_id}",
            json={"cost": 99.5},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.get_json()["cost"] == 99.5

    def test_patch_updates_mode(self, client, app):
        """PATCH /api/trips/:id updates the travel mode."""
        token = _create_user_and_token(app, client, email="patch3@example.com")
        trip_id = self._create_trip_and_get_id(client, token)

        resp = client.patch(
            f"/api/trips/{trip_id}",
            json={"mode": "Walking"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.get_json()["mode"] == "Walking"

    def test_patch_updates_companions(self, client, app):
        """PATCH /api/trips/:id updates the companions count."""
        token = _create_user_and_token(app, client, email="patch4@example.com")
        trip_id = self._create_trip_and_get_id(client, token)

        resp = client.patch(
            f"/api/trips/{trip_id}",
            json={"companions": 3},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.get_json()["companions"] == 3

    def test_patch_nonexistent_trip_returns_404(self, client, app):
        """PATCH /api/trips/9999 returns 404 when trip does not exist."""
        token = _create_user_and_token(app, client, email="patch5@example.com")
        resp = client.patch(
            "/api/trips/9999",
            json={"purpose": "Work"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404

    def test_patch_another_users_trip_returns_403(self, client, app):
        """PATCH /api/trips/:id returns 403 when trip belongs to another user."""
        token_a = _create_user_and_token(app, client, email="owner@example.com")
        token_b = _create_user_and_token(app, client, email="thief@example.com")

        # User A creates a trip
        client.post(
            "/api/trips",
            json=_trip_payload(),
            headers={"Authorization": f"Bearer {token_a}"},
        )
        trip_id = client.get(
            "/api/trips", headers={"Authorization": f"Bearer {token_a}"}
        ).get_json()["trips"][0]["id"]

        # User B tries to update it
        resp = client.patch(
            f"/api/trips/{trip_id}",
            json={"purpose": "Theft"},
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert resp.status_code == 403

    def test_patch_requires_auth(self, client, app):
        """PATCH /api/trips/:id without a token returns 401."""
        resp = client.patch("/api/trips/1", json={"purpose": "Work"})
        assert resp.status_code == 401


# ===========================================================================
# 5. Trip Chain Formation
# ===========================================================================

class TestTripChainFormation:
    """Verify trip chain formation groups trips within 60 minutes (P6)."""

    def _post_trip(self, client, token, start_time, end_time, **kwargs):
        """Helper to post a trip with given start/end times."""
        payload = _trip_payload(start_time=start_time, end_time=end_time, **kwargs)
        return client.post(
            "/api/trips",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )

    def test_two_trips_within_60_min_form_a_chain(self, client, app):
        """Two trips with a 30-minute gap are grouped into the same chain."""
        token = _create_user_and_token(app, client, email="chain1@example.com")

        # Trip 1: 08:00 → 08:30
        self._post_trip(client, token, "2024-01-15T08:00:00", "2024-01-15T08:30:00")
        # Trip 2: 08:45 → 09:15  (gap = 15 min)
        self._post_trip(client, token, "2024-01-15T08:45:00", "2024-01-15T09:15:00")

        resp = client.get("/api/trips", headers={"Authorization": f"Bearer {token}"})
        trips = resp.get_json()["trips"]

        chain_ids = {t["chain_id"] for t in trips if t["chain_id"] is not None}
        assert len(chain_ids) == 1, "Both trips should share one chain_id"

    def test_two_trips_beyond_60_min_not_chained(self, client, app):
        """Two trips with a 90-minute gap are NOT grouped into a chain."""
        token = _create_user_and_token(app, client, email="chain2@example.com")

        # Trip 1: 08:00 → 08:30
        self._post_trip(client, token, "2024-01-15T08:00:00", "2024-01-15T08:30:00")
        # Trip 2: 10:00 → 10:30  (gap = 90 min)
        self._post_trip(client, token, "2024-01-15T10:00:00", "2024-01-15T10:30:00")

        resp = client.get("/api/trips", headers={"Authorization": f"Bearer {token}"})
        trips = resp.get_json()["trips"]

        # No trip should have a chain_id (solo trips are not chained)
        assert all(t["chain_id"] is None for t in trips), \
            "Trips with >60 min gap should not be chained"

    def test_three_consecutive_trips_form_one_chain(self, client, app):
        """Three trips each within 60 minutes of the previous form a single chain."""
        token = _create_user_and_token(app, client, email="chain3@example.com")

        self._post_trip(client, token, "2024-01-15T08:00:00", "2024-01-15T08:30:00")
        self._post_trip(client, token, "2024-01-15T09:00:00", "2024-01-15T09:30:00")  # gap 30 min
        self._post_trip(client, token, "2024-01-15T10:00:00", "2024-01-15T10:30:00")  # gap 30 min

        resp = client.get("/api/trips", headers={"Authorization": f"Bearer {token}"})
        trips = resp.get_json()["trips"]

        chain_ids = {t["chain_id"] for t in trips if t["chain_id"] is not None}
        assert len(chain_ids) == 1, "All three trips should share one chain_id"

    def test_chain_endpoint_returns_chain_summary(self, client, app):
        """GET /api/trip-chains returns a chain with correct legs_count."""
        token = _create_user_and_token(app, client, email="chain4@example.com")

        self._post_trip(client, token, "2024-01-15T08:00:00", "2024-01-15T08:30:00", distance=5.0, duration=30.0)
        self._post_trip(client, token, "2024-01-15T09:00:00", "2024-01-15T09:30:00", distance=3.0, duration=30.0)

        resp = client.get("/api/trip-chains", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        chains = resp.get_json()
        assert isinstance(chains, list)
        assert len(chains) == 1
        assert chains[0]["legs_count"] == 2

    def test_exactly_60_min_gap_forms_chain(self, client, app):
        """Two trips with exactly 60-minute gap are included in the same chain."""
        token = _create_user_and_token(app, client, email="chain5@example.com")

        self._post_trip(client, token, "2024-01-15T08:00:00", "2024-01-15T08:30:00")
        # Gap = exactly 60 minutes
        self._post_trip(client, token, "2024-01-15T09:30:00", "2024-01-15T10:00:00")

        resp = client.get("/api/trips", headers={"Authorization": f"Bearer {token}"})
        trips = resp.get_json()["trips"]

        chain_ids = {t["chain_id"] for t in trips if t["chain_id"] is not None}
        assert len(chain_ids) == 1, "Trips with exactly 60 min gap should be chained"
