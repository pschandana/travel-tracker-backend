from flask import Flask, request, jsonify, send_from_directory

from flask_bcrypt import Bcrypt
from flask_jwt_extended import JWTManager, jwt_required, get_jwt_identity
from flask_cors import CORS
import os

from config import Config
from models import db, User, Trip, TripChain, run_migrations
from flask_mail import Mail
from datetime import datetime

from analyst import analyst_bp
from blueprints.auth import auth_bp
from blueprints.trips import trips_bp
from blueprints.export import export_bp


app = Flask(__name__)
app.config.from_object(Config)

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

CORS(app)
app.register_blueprint(analyst_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(trips_bp)
app.register_blueprint(export_bp)

mail = Mail(app)

db.init_app(app)
bcrypt = Bcrypt(app)
jwt = JWTManager(app)


# ---------------- PROFILE (GET) ----------------
@app.route("/api/profile")
@jwt_required()
def profile():
    uid = get_jwt_identity()
    user = User.query.get(uid)

    return jsonify({
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "mobile": user.mobile,
        "place": user.place,
        "photo": user.photo,
    })


# ---------------- UPDATE PASSWORD ----------------
@app.route("/api/update-password", methods=["POST"])
@jwt_required()
def update_password():
    uid = get_jwt_identity()
    data = request.json
    user = User.query.get(uid)

    if not bcrypt.check_password_hash(user.password, data["old_password"]):
        return jsonify({"msg": "Wrong password"}), 400

    new_hash = bcrypt.generate_password_hash(data["new_password"]).decode("utf-8")
    user.password = new_hash
    db.session.commit()

    return jsonify({"msg": "Password updated"})


# ---------------- UPDATE PHOTO ----------------
from werkzeug.utils import secure_filename

@app.route("/api/update-photo", methods=["POST"])
@jwt_required()
def update_photo():
    uid = get_jwt_identity()

    if "photo" not in request.files:
        return jsonify({"msg": "No file"}), 400

    file = request.files["photo"]
    filename = secure_filename(f"user_{uid}.jpg")
    path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    file.save(path)

    user = User.query.get(uid)
    user.photo = f"/uploads/{filename}"
    db.session.commit()

    return jsonify({"photo": user.photo})


# ---------------- SERVE UPLOADS ----------------
@app.route("/uploads/<filename>")
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


@app.route("/api/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    run_migrations(app)
    app.run(host="0.0.0.0", port=5000)
