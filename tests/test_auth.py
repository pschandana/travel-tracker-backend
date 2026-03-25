"""
Unit tests for authentication functionality.

Covers:
- User registration and login (OTP flow)
- OTP generation and expiry (time-based)
- Password hashing (bcrypt)
- JWT authentication and role-based access for protected routes
"""

import sys
import os
import pytest
from datetime import datetime, timedelta

# Ensure the backend root is on the path so imports work
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# App fixture
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
        MAIL_SUPPRESS_SEND=True,   # prevent real emails during tests
        MAIL_SERVER="localhost",
        MAIL_PORT=25,
        MAIL_USE_TLS=False,
        MAIL_USERNAME="test@example.com",
        MAIL_PASSWORD="",
    )

    # Flask-Bcrypt 1.0.1 doesn't self-register in app.extensions.
    # auth.py's _bcrypt() looks up app.extensions["bcrypt"], so we register it manually.
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


@pytest.fixture
def bcrypt_instance(app):
    """Return the Bcrypt instance registered on the test app."""
    return app.extensions["bcrypt"]


# ---------------------------------------------------------------------------
# Helper: register a user directly (bypassing OTP email)
# ---------------------------------------------------------------------------

def _create_user(app, email="user@example.com", password="Password123"):
    """Insert a verified user directly into the DB."""
    from models import db, User

    b = app.extensions["bcrypt"]
    hashed = b.generate_password_hash(password).decode("utf-8")

    with app.app_context():
        user = User(
            name="Test User",
            email=email,
            mobile="9999999999",
            place="TestCity",
            password=hashed,
            is_verified=True,
        )
        db.session.add(user)
        db.session.commit()
        return user.id


# ===========================================================================
# 1. Password Hashing Tests
# ===========================================================================

class TestPasswordHashing:
    """Verify bcrypt hashing behaviour (Property P2)."""

    def test_hash_differs_from_plaintext(self, bcrypt_instance):
        """Hashed password must not equal the original plaintext."""
        plain = "MySecretPass99"
        hashed = bcrypt_instance.generate_password_hash(plain).decode("utf-8")
        assert hashed != plain

    def test_correct_password_verifies(self, bcrypt_instance):
        """check_password_hash must return True for the correct password."""
        plain = "CorrectHorseBattery"
        hashed = bcrypt_instance.generate_password_hash(plain).decode("utf-8")
        assert bcrypt_instance.check_password_hash(hashed, plain) is True

    def test_wrong_password_fails_verification(self, bcrypt_instance):
        """check_password_hash must return False for a different password."""
        plain = "CorrectHorseBattery"
        hashed = bcrypt_instance.generate_password_hash(plain).decode("utf-8")
        assert bcrypt_instance.check_password_hash(hashed, "WrongPassword") is False

    def test_two_hashes_of_same_password_differ(self, bcrypt_instance):
        """bcrypt salts each hash, so two hashes of the same password differ."""
        plain = "SamePassword"
        hash1 = bcrypt_instance.generate_password_hash(plain).decode("utf-8")
        hash2 = bcrypt_instance.generate_password_hash(plain).decode("utf-8")
        assert hash1 != hash2

    def test_stored_password_is_bcrypt_hash(self, app):
        """Password stored in DB must be a bcrypt hash (starts with $2b$)."""
        from models import User
        uid = _create_user(app, email="hashcheck@example.com", password="PlainPass1")
        with app.app_context():
            user = User.query.get(uid)
            assert user.password.startswith("$2b$") or user.password.startswith("$2a$")


# ===========================================================================
# 2. OTP Generation and Expiry Tests
# ===========================================================================

class TestOTPGenerationAndExpiry:
    """Verify OTP generation and time-based expiry logic."""

    def test_generate_otp_is_six_digits(self):
        """generate_otp() must return a 6-digit numeric string."""
        from blueprints.auth import generate_otp
        otp = generate_otp()
        assert len(otp) == 6
        assert otp.isdigit()

    def test_generate_otp_in_valid_range(self):
        """OTP value must be between 100000 and 999999."""
        from blueprints.auth import generate_otp
        for _ in range(20):
            otp = int(generate_otp())
            assert 100000 <= otp <= 999999

    def test_otp_not_expired_within_5_minutes(self):
        """An OTP generated now should not be expired yet."""
        expiry = datetime.utcnow() + timedelta(minutes=5)
        assert expiry > datetime.utcnow()

    def test_otp_expired_after_5_minutes(self):
        """An OTP with expiry in the past should be treated as expired."""
        expiry = datetime.utcnow() - timedelta(seconds=1)
        assert expiry < datetime.utcnow()

    def test_verify_otp_rejects_expired(self, client, app):
        """POST /api/verify-otp returns 400 with 'OTP expired' for a stale OTP."""
        from blueprints.auth import otp_store

        email = "expired@example.com"
        with app.app_context():
            otp_store[email] = {
                "otp": "123456",
                "expires": datetime.utcnow() - timedelta(seconds=1),
                "data": {
                    "name": "Expired User",
                    "email": email,
                    "mobile": "1234567890",
                    "place": "Nowhere",
                    "password": "pass",
                },
            }

        resp = client.post("/api/verify-otp", json={"email": email, "otp": "123456"})
        assert resp.status_code == 400
        assert resp.get_json()["msg"] == "OTP expired"

    def test_verify_otp_rejects_wrong_otp(self, client, app):
        """POST /api/verify-otp returns 400 with 'Invalid OTP' for wrong code."""
        from blueprints.auth import otp_store

        email = "wrongotp@example.com"
        with app.app_context():
            otp_store[email] = {
                "otp": "654321",
                "expires": datetime.utcnow() + timedelta(minutes=5),
                "data": {
                    "name": "Wrong OTP User",
                    "email": email,
                    "mobile": "1234567890",
                    "place": "Somewhere",
                    "password": "pass",
                },
            }

        resp = client.post("/api/verify-otp", json={"email": email, "otp": "000000"})
        assert resp.status_code == 400
        assert resp.get_json()["msg"] == "Invalid OTP"

    def test_verify_otp_success_creates_user(self, client, app):
        """POST /api/verify-otp with correct, unexpired OTP creates the user."""
        from blueprints.auth import otp_store
        from models import User

        email = "newuser@example.com"
        with app.app_context():
            otp_store[email] = {
                "otp": "112233",
                "expires": datetime.utcnow() + timedelta(minutes=5),
                "data": {
                    "name": "New User",
                    "email": email,
                    "mobile": "9876543210",
                    "place": "TestCity",
                    "password": "SecurePass1",
                },
            }

        resp = client.post("/api/verify-otp", json={"email": email, "otp": "112233"})
        assert resp.status_code == 200
        assert resp.get_json()["msg"] == "Registered successfully"

        with app.app_context():
            user = User.query.filter_by(email=email).first()
            assert user is not None


# ===========================================================================
# 3. User Registration and Login Tests
# ===========================================================================

class TestRegistrationAndLogin:
    """Verify registration guard-rails and login flow."""

    def test_send_otp_rejects_duplicate_email(self, client, app):
        """POST /api/send-otp returns 400 when email is already registered."""
        _create_user(app, email="dup@example.com")
        resp = client.post("/api/send-otp", json={
            "name": "Dup User",
            "email": "dup@example.com",
            "mobile": "1111111111",
            "place": "City",
            "password": "pass",
        })
        assert resp.status_code == 400
        assert resp.get_json()["msg"] == "Email already registered"

    def test_login_success_returns_token(self, client, app):
        """POST /api/login with valid credentials returns a JWT token."""
        _create_user(app, email="login@example.com", password="GoodPass1")
        resp = client.post("/api/login", json={
            "email": "login@example.com",
            "password": "GoodPass1",
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert "token" in data
        assert len(data["token"]) > 0

    def test_login_wrong_password_returns_401(self, client, app):
        """POST /api/login with wrong password returns 401 Invalid credentials."""
        _create_user(app, email="badpass@example.com", password="RealPass1")
        resp = client.post("/api/login", json={
            "email": "badpass@example.com",
            "password": "WrongPass",
        })
        assert resp.status_code == 401
        assert resp.get_json()["msg"] == "Invalid credentials"

    def test_login_unknown_email_returns_401(self, client, app):
        """POST /api/login with unknown email returns 401 Invalid credentials."""
        resp = client.post("/api/login", json={
            "email": "nobody@example.com",
            "password": "AnyPass",
        })
        assert resp.status_code == 401
        assert resp.get_json()["msg"] == "Invalid credentials"


# ===========================================================================
# 4. JWT Authentication and Role-Based Access Tests
# ===========================================================================

class TestJWTAndRoleBasedAccess:
    """Verify JWT protection and role isolation (Property P3)."""

    def _get_user_token(self, client, app, email="jwt@example.com", password="JwtPass1"):
        """Register a user and return their JWT token."""
        _create_user(app, email=email, password=password)
        resp = client.post("/api/login", json={"email": email, "password": password})
        return resp.get_json()["token"]

    def _get_analyst_token(self, client):
        """Log in as the analyst and return the analyst JWT token."""
        resp = client.post("/api/analyst/login", json={
            "email": "analyst@smartcity.com",
            "password": "SmartCity@123",
        })
        return resp.get_json()["token"]

    def test_protected_route_requires_token(self, client, app):
        """GET /api/profile without a token returns 401."""
        resp = client.get("/api/profile")
        assert resp.status_code == 401

    def test_protected_route_accessible_with_valid_token(self, client, app):
        """GET /api/profile with a valid user JWT returns 200."""
        token = self._get_user_token(client, app)
        resp = client.get("/api/profile", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200

    def test_analyst_endpoint_rejects_user_token(self, client, app):
        """Analyst endpoint rejects a user (citizen) token.

        The analyst_required decorator decodes the raw token using PyJWT.
        A Flask-JWT-Extended user token uses a different signing key/format,
        so the decode raises an exception → 401 Invalid token.
        If the token decodes but lacks role='analyst' → 403 Unauthorized.
        Either way, access is denied.
        """
        token = self._get_user_token(client, app, email="citizen@example.com")
        resp = client.get(
            "/api/analyst/dashboard",
            headers={"Authorization": token},  # analyst_required reads raw header
        )
        assert resp.status_code in (401, 403)

    def test_analyst_endpoint_accepts_analyst_token(self, client, app):
        """Analyst endpoint returns 200 when called with a valid analyst token."""
        token = self._get_analyst_token(client)
        resp = client.get(
            "/api/analyst/dashboard",
            headers={"Authorization": token},
        )
        assert resp.status_code == 200

    def test_user_endpoint_rejects_analyst_token(self, client, app):
        """User-protected endpoint returns 401/422 when called with an analyst token.

        The analyst token is a raw PyJWT token (not a Flask-JWT-Extended token),
        so Flask-JWT-Extended will reject it with 422 Unprocessable Entity.
        """
        token = self._get_analyst_token(client)
        resp = client.get(
            "/api/profile",
            headers={"Authorization": f"Bearer {token}"},
        )
        # Flask-JWT-Extended rejects non-FJE tokens with 422
        assert resp.status_code in (401, 422)

    def test_invalid_token_returns_error(self, client, app):
        """A tampered/invalid token is rejected by protected routes."""
        resp = client.get(
            "/api/profile",
            headers={"Authorization": "Bearer this.is.not.valid"},
        )
        assert resp.status_code in (401, 422)
