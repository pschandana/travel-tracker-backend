"""
Unit tests for privacy functionality.

Covers:
- Account deletion removes the user and all related trips/consent records
- Consent record creation and retrieval via POST /api/consent
"""

import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# App fixture (mirrors test_auth.py / test_trips.py)
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
# Helpers
# ---------------------------------------------------------------------------

def _create_user_and_token(app, client, email="privacy@example.com", password="PrivPass1"):
    """Insert a verified user and return (user_id, jwt_token)."""
    from models import db, User

    b = app.extensions["bcrypt"]
    hashed = b.generate_password_hash(password).decode("utf-8")

    with app.app_context():
        user = User(
            name="Privacy Tester",
            email=email,
            mobile="7777777777",
            place="TestCity",
            password=hashed,
            is_verified=True,
        )
        db.session.add(user)
        db.session.commit()
        uid = user.id

    resp = client.post("/api/login", json={"email": email, "password": password})
    token = resp.get_json()["token"]
    return uid, token


def _trip_payload(**overrides):
    base = {
        "start_lat": 10.0,
        "start_lng": 76.0,
        "end_lat": 10.1,
        "end_lng": 76.1,
        "start_time": "2024-03-01T08:00:00",
        "end_time": "2024-03-01T08:30:00",
        "distance": 5.0,
        "duration": 30.0,
        "mode": "Bus",
        "purpose": "Work",
        "cost": 15.0,
        "companions": 0,
        "route": [{"lat": 10.0, "lng": 76.0}, {"lat": 10.1, "lng": 76.1}],
    }
    base.update(overrides)
    return base


# ===========================================================================
# 1. Account Deletion
# ===========================================================================

class TestAccountDeletion:
    """Verify DELETE /api/account removes the user and all related data."""

    def test_delete_account_returns_200(self, client, app):
        """DELETE /api/account returns 200 with success message."""
        _, token = _create_user_and_token(app, client, email="del1@example.com")
        resp = client.delete("/api/account", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.get_json()["message"] == "Account deleted successfully"

    def test_delete_account_removes_user_from_db(self, client, app):
        """After deletion the User row no longer exists in the database."""
        from models import User

        uid, token = _create_user_and_token(app, client, email="del2@example.com")
        client.delete("/api/account", headers={"Authorization": f"Bearer {token}"})

        with app.app_context():
            assert User.query.get(uid) is None

    def test_delete_account_removes_related_trips(self, client, app):
        """After deletion all trips belonging to the user are removed."""
        from models import Trip

        uid, token = _create_user_and_token(app, client, email="del3@example.com")
        headers = {"Authorization": f"Bearer {token}"}

        # Create two trips
        client.post("/api/trips", json=_trip_payload(start_time="2024-03-01T08:00:00"), headers=headers)
        client.post("/api/trips", json=_trip_payload(start_time="2024-03-01T10:00:00"), headers=headers)

        # Confirm trips exist before deletion
        with app.app_context():
            assert Trip.query.filter_by(user_id=uid).count() == 2

        client.delete("/api/account", headers=headers)

        with app.app_context():
            assert Trip.query.filter_by(user_id=uid).count() == 0

    def test_delete_account_removes_consent_records(self, client, app):
        """After deletion all ConsentRecords belonging to the user are removed."""
        from models import ConsentRecord

        uid, token = _create_user_and_token(app, client, email="del4@example.com")
        headers = {"Authorization": f"Bearer {token}"}

        # Grant consent so a ConsentRecord is created
        client.post("/api/consent", json={"permission_type": "location", "granted": True}, headers=headers)

        with app.app_context():
            assert ConsentRecord.query.filter_by(user_id=uid).count() == 1

        client.delete("/api/account", headers=headers)

        with app.app_context():
            assert ConsentRecord.query.filter_by(user_id=uid).count() == 0

    def test_delete_account_requires_auth(self, client, app):
        """DELETE /api/account without a token returns 401."""
        resp = client.delete("/api/account")
        assert resp.status_code == 401

    def test_delete_account_with_no_trips_succeeds(self, client, app):
        """DELETE /api/account works even when the user has no trips."""
        uid, token = _create_user_and_token(app, client, email="del5@example.com")
        resp = client.delete("/api/account", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200


# ===========================================================================
# 2. Consent Record Creation and Retrieval
# ===========================================================================

class TestConsentRecord:
    """Verify POST /api/consent creates and returns consent records correctly."""

    def test_grant_consent_returns_201(self, client, app):
        """POST /api/consent with granted=True returns 201."""
        _, token = _create_user_and_token(app, client, email="consent1@example.com")
        resp = client.post(
            "/api/consent",
            json={"permission_type": "location", "granted": True},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201

    def test_grant_consent_response_fields(self, client, app):
        """Consent response includes id, user_id, permission_type, granted_at."""
        uid, token = _create_user_and_token(app, client, email="consent2@example.com")
        resp = client.post(
            "/api/consent",
            json={"permission_type": "motion", "granted": True},
            headers={"Authorization": f"Bearer {token}"},
        )
        data = resp.get_json()
        assert data["user_id"] == uid
        assert data["permission_type"] == "motion"
        assert data["granted_at"] is not None
        assert data["withdrawn_at"] is None

    def test_grant_consent_persists_to_db(self, client, app):
        """A granted consent is stored as a ConsentRecord in the database."""
        from models import ConsentRecord

        uid, token = _create_user_and_token(app, client, email="consent3@example.com")
        client.post(
            "/api/consent",
            json={"permission_type": "notification", "granted": True},
            headers={"Authorization": f"Bearer {token}"},
        )

        with app.app_context():
            record = ConsentRecord.query.filter_by(user_id=uid, permission_type="notification").first()
            assert record is not None
            assert record.withdrawn_at is None

    def test_withdraw_consent_sets_withdrawn_at(self, client, app):
        """POST /api/consent with granted=False sets withdrawn_at on the record."""
        from models import ConsentRecord

        uid, token = _create_user_and_token(app, client, email="consent4@example.com")
        headers = {"Authorization": f"Bearer {token}"}

        # Grant first
        client.post("/api/consent", json={"permission_type": "location", "granted": True}, headers=headers)

        # Then withdraw
        resp = client.post("/api/consent", json={"permission_type": "location", "granted": False}, headers=headers)
        assert resp.status_code == 201
        assert resp.get_json()["withdrawn_at"] is not None

        with app.app_context():
            record = (
                ConsentRecord.query
                .filter_by(user_id=uid, permission_type="location")
                .order_by(ConsentRecord.granted_at.desc())
                .first()
            )
            assert record.withdrawn_at is not None

    def test_consent_requires_auth(self, client, app):
        """POST /api/consent without a token returns 401."""
        resp = client.post("/api/consent", json={"permission_type": "location", "granted": True})
        assert resp.status_code == 401

    def test_consent_invalid_permission_type_returns_400(self, client, app):
        """POST /api/consent with an unknown permission_type returns 400."""
        _, token = _create_user_and_token(app, client, email="consent5@example.com")
        resp = client.post(
            "/api/consent",
            json={"permission_type": "invalid_type", "granted": True},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400

    def test_consent_missing_permission_type_returns_400(self, client, app):
        """POST /api/consent without permission_type returns 400."""
        _, token = _create_user_and_token(app, client, email="consent6@example.com")
        resp = client.post(
            "/api/consent",
            json={"granted": True},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400

    def test_multiple_consent_types_stored_independently(self, client, app):
        """Granting location and motion consent creates two separate records."""
        from models import ConsentRecord

        uid, token = _create_user_and_token(app, client, email="consent7@example.com")
        headers = {"Authorization": f"Bearer {token}"}

        client.post("/api/consent", json={"permission_type": "location", "granted": True}, headers=headers)
        client.post("/api/consent", json={"permission_type": "motion", "granted": True}, headers=headers)

        with app.app_context():
            count = ConsentRecord.query.filter_by(user_id=uid).count()
            assert count == 2
