from flask import Blueprint, request, jsonify, current_app
from flask_bcrypt import Bcrypt
from flask_jwt_extended import (
    create_access_token,
    jwt_required,
    get_jwt_identity,
)
from flask_mail import Message
from models import db, User, Trip, ConsentRecord
from audit import write_audit
from datetime import datetime, timedelta
import random
import os

auth_bp = Blueprint("auth", __name__)

otp_store = {}

# Standalone bcrypt instance — works without app context extensions lookup
_bcrypt_instance = Bcrypt()


def _bcrypt() -> Bcrypt:
    return _bcrypt_instance


def generate_otp():
    return str(random.randint(100000, 999999))


def send_email(to, otp):
    from flask_mail import Message, Mail
    mail: Mail = current_app.extensions["mail"]
    msg = Message(
        "Your OTP Verification",
        sender=current_app.config["MAIL_USERNAME"],
        recipients=[to],
    )
    msg.body = f"""
Hello 👋

Your OTP for Travel Tracker is:

{otp}

Valid for 5 minutes.

Do not share it.

Thanks ❤️
"""
    mail.send(msg)


# ---------------- DIRECT REGISTER (no OTP) ----------------
@auth_bp.route("/api/register", methods=["POST"])
def register():
    data = request.get_json() or {}
    name = data.get("name")
    email = data.get("email")
    place = data.get("place")
    password = data.get("password")

    if not all([name, email, place, password]):
        return jsonify({"msg": "All fields are required"}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({"msg": "Email already registered"}), 400

    bcrypt: Bcrypt = _bcrypt()
    hashed = bcrypt.generate_password_hash(password).decode("utf-8")

    user = User(name=name, email=email, mobile="", place=place, password=hashed)
    db.session.add(user)
    db.session.commit()

    return jsonify({"msg": "Registered successfully"}), 201


# ---------------- SEND OTP ----------------
@auth_bp.route("/api/send-otp", methods=["POST"])
def send_otp():
    data = request.get_json()
    email = data.get("email")

    if not email:
        return jsonify({"msg": "Email required"}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({"msg": "Email already registered"}), 400

    otp = generate_otp()
    expiry = datetime.utcnow() + timedelta(minutes=5)

    otp_store[email] = {
        "otp": otp,
        "expires": expiry,
        "data": data,
    }

    send_email(email, otp)
    return jsonify({"msg": "OTP sent"}), 200


# ---------------- RESEND OTP ----------------
@auth_bp.route("/api/resend-otp", methods=["POST"])
def resend_otp():
    data = request.get_json()
    email = data.get("email")

    if email not in otp_store:
        return jsonify({"msg": "OTP session expired"}), 404

    otp = generate_otp()
    otp_store[email]["otp"] = otp
    otp_store[email]["expires"] = datetime.utcnow() + timedelta(minutes=5)

    send_email(email, otp)
    return jsonify({"msg": "OTP resent"}), 200


# ---------------- VERIFY OTP ----------------
@auth_bp.route("/api/verify-otp", methods=["POST"])
def verify_otp():
    data = request.get_json()
    email = data.get("email")
    otp = data.get("otp")

    if email not in otp_store:
        return jsonify({"msg": "OTP not found"}), 404

    record = otp_store[email]

    if record["expires"] < datetime.utcnow():
        del otp_store[email]
        return jsonify({"msg": "OTP expired"}), 400

    if record["otp"] != otp:
        return jsonify({"msg": "Invalid OTP"}), 400

    user_data = record["data"]
    bcrypt: Bcrypt = _bcrypt()
    hashed = bcrypt.generate_password_hash(user_data["password"]).decode("utf-8")

    user = User(
        name=user_data["name"],
        email=user_data["email"],
        mobile=user_data["mobile"],
        place=user_data["place"],
        password=hashed,
    )

    db.session.add(user)
    db.session.commit()

    del otp_store[email]
    return jsonify({"msg": "Registered successfully"}), 200


# ---------------- LOGIN ----------------
@auth_bp.route("/api/login", methods=["POST"])
def login():
    data = request.json
    user = User.query.filter_by(email=data["email"]).first()

    if not user:
        return jsonify({"msg": "Invalid credentials"}), 401

    bcrypt: Bcrypt = _bcrypt()
    if not bcrypt.check_password_hash(user.password, data["password"]):
        return jsonify({"msg": "Invalid credentials"}), 401

    token = create_access_token(identity=str(user.id))
    return jsonify({"token": token})


# ---------------- DELETE ACCOUNT ----------------
@auth_bp.route("/api/account", methods=["DELETE"])
@jwt_required()
def delete_account():
    uid = int(get_jwt_identity())

    try:
        user = User.query.get(uid)

        if not user:
            return jsonify({"msg": "User not found"}), 404

        # Collect local file paths to remove after the transaction commits
        files_to_delete = []

        # Gather uploaded file paths from trips
        trips = Trip.query.filter_by(user_id=uid).all()
        for trip in trips:
            if trip.map_image and trip.map_image.startswith("/uploads/"):
                files_to_delete.append(trip.map_image)

        # Gather user photo path
        if user.photo and user.photo.startswith("/uploads/"):
            files_to_delete.append(user.photo)

        # Write audit log before deletion (record_id = user id)
        write_audit("DELETE", "user", uid, user_id=uid, autocommit=False)

        # Delete ConsentRecords
        ConsentRecord.query.filter_by(user_id=uid).delete()

        # Delete Trips
        Trip.query.filter_by(user_id=uid).delete()

        # Delete User
        db.session.delete(user)

        # Commit everything in one transaction
        db.session.commit()

        # Remove files from disk after successful commit
        upload_folder = current_app.config.get("UPLOAD_FOLDER", "uploads")
        for file_path in files_to_delete:
            # file_path is like "/uploads/user_1.jpg" — strip leading "/uploads/"
            filename = file_path.lstrip("/").replace("uploads/", "", 1)
            abs_path = os.path.join(upload_folder, filename)
            try:
                if os.path.isfile(abs_path):
                    os.remove(abs_path)
            except OSError:
                pass  # Best-effort file removal; DB deletion already committed

        return jsonify({"message": "Account deleted successfully"}), 200

    except Exception:
        db.session.rollback()
        return jsonify({"message": "Failed to delete account"}), 500


# ---------------- CONSENT ----------------
VALID_PERMISSION_TYPES = {"location", "motion", "notification"}


@auth_bp.route("/api/consent", methods=["POST"])
@jwt_required()
def record_consent():
    uid = int(get_jwt_identity())
    user = User.query.get(uid)

    if not user:
        return jsonify({"msg": "User not found"}), 404

    data = request.get_json() or {}
    permission_type = data.get("permission_type")
    granted = data.get("granted", True)

    if not permission_type:
        return jsonify({"msg": "permission_type is required"}), 400

    if permission_type not in VALID_PERMISSION_TYPES:
        return jsonify({"msg": f"Invalid permission_type. Must be one of: {', '.join(sorted(VALID_PERMISSION_TYPES))}"}), 400

    now = datetime.utcnow()

    if granted:
        # Create a new ConsentRecord for this grant
        record = ConsentRecord(
            user_id=uid,
            permission_type=permission_type,
            granted_at=now,
        )
        db.session.add(record)

        # Update User consent fields
        user.consent_given = True
        user.consent_timestamp = now
    else:
        # Withdrawal: find the most recent active ConsentRecord for this user+permission_type
        record = (
            ConsentRecord.query
            .filter_by(user_id=uid, permission_type=permission_type)
            .filter(ConsentRecord.withdrawn_at.is_(None))
            .order_by(ConsentRecord.granted_at.desc())
            .first()
        )

        if record is None:
            # No active record found — create one that is immediately withdrawn
            record = ConsentRecord(
                user_id=uid,
                permission_type=permission_type,
                granted_at=now,
                withdrawn_at=now,
            )
            db.session.add(record)
        else:
            record.withdrawn_at = now

        # Update User withdrawal timestamp
        user.consent_withdrawn_at = now

    db.session.flush()  # populate record.id before audit
    write_audit("CREATE", "consent_record", record.id, uid, autocommit=False)
    db.session.commit()

    return jsonify({
        "id": record.id,
        "user_id": record.user_id,
        "permission_type": record.permission_type,
        "granted_at": record.granted_at.isoformat(),
        "withdrawn_at": record.withdrawn_at.isoformat() if record.withdrawn_at else None,
    }), 201
