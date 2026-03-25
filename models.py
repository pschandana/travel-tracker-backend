from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, date

db = SQLAlchemy()


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    photo = db.Column(db.Text)
    mobile = db.Column(db.String(15), nullable=False)
    place = db.Column(db.String(100), nullable=False)
    otp_code = db.Column(db.String(6))
    otp_expiry = db.Column(db.DateTime)
    is_verified = db.Column(db.Boolean, default=False)
    language = db.Column(db.String(10), default="en")
    theme = db.Column(db.String(10), default="light")
    consent_given = db.Column(db.Boolean, default=False)
    consent_timestamp = db.Column(db.DateTime, nullable=True)
    consent_withdrawn_at = db.Column(db.DateTime, nullable=True)


class Analyst(db.Model):
    __tablename__ = "analyst"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class TripChain(db.Model):
    __tablename__ = "trip_chain"

    id = db.Column(db.Integer, primary_key=True)
    chain_id = db.Column(db.String(50), unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    label = db.Column(db.String(200))
    total_duration = db.Column(db.Float)   # minutes
    total_distance = db.Column(db.Float)   # km
    legs_count = db.Column(db.Integer)
    mode_sequence = db.Column(db.JSON)     # e.g. ["Walk", "Bus", "Car"]
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Trip(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    trip_no = db.Column(db.String(50), unique=True)

    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), index=True)

    start_lat = db.Column(db.Float)
    start_lng = db.Column(db.Float)
    end_lat = db.Column(db.Float)
    end_lng = db.Column(db.Float)

    # Store as String to preserve full ISO datetime from frontend
    start_time = db.Column(db.String(50))
    end_time = db.Column(db.String(50))

    trip_date = db.Column(db.Date, default=date.today, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    distance = db.Column(db.Float)
    duration = db.Column(db.Float)

    mode = db.Column(db.String(50))
    purpose = db.Column(db.String(100))

    cost = db.Column(db.Float)
    companions = db.Column(db.Integer)
    frequency = db.Column(db.Integer, default=1)

    ml_mode = db.Column(db.String(50), nullable=True)
    confidence_score = db.Column(db.Float, nullable=True)
    chain_id = db.Column(db.String(50), db.ForeignKey("trip_chain.chain_id"), nullable=True)
    is_incomplete = db.Column(db.Boolean, default=False)
    has_gps_gap = db.Column(db.Boolean, default=False)
    data_quality_flag = db.Column(db.Boolean, default=False)

    route = db.Column(db.JSON)
    map_image = db.Column(db.Text)


class AuditLog(db.Model):
    __tablename__ = "audit_log"

    id = db.Column(db.Integer, primary_key=True)
    operation = db.Column(db.String(20), nullable=False)   # "CREATE", "UPDATE", "DELETE"
    table_name = db.Column(db.String(50), nullable=False)
    record_id = db.Column(db.Integer, nullable=False)
    user_id = db.Column(db.Integer, nullable=True)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class ConsentRecord(db.Model):
    __tablename__ = "consent_record"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    permission_type = db.Column(db.String(50), nullable=False)  # "location", "motion", "notification"
    granted_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    withdrawn_at = db.Column(db.DateTime, nullable=True)


def run_migrations(app):
    """Apply ALTER TABLE migrations for columns added after initial db.create_all()."""
    with app.app_context():
        from sqlalchemy import text, inspect as sa_inspect
        inspector = sa_inspect(db.engine)

        # Ensure trip_chain table exists (db.create_all handles new tables)
        db.create_all()

        existing_tables = inspector.get_table_names()

        # User table migrations
        existing_user_cols = {col["name"] for col in inspector.get_columns("user")}
        user_migrations = [
            ("theme", "VARCHAR(10) DEFAULT 'light'"),
            ("consent_given", "BOOLEAN DEFAULT 0"),
            ("consent_timestamp", "DATETIME"),
            ("consent_withdrawn_at", "DATETIME"),
        ]

        # Trip table migrations
        existing_trip_cols = {col["name"] for col in inspector.get_columns("trip")}
        trip_migrations = [
            ("ml_mode", "VARCHAR(50)"),
            ("confidence_score", "FLOAT"),
            ("chain_id", "VARCHAR(50)"),
            ("is_incomplete", "BOOLEAN DEFAULT 0"),
            ("has_gps_gap", "BOOLEAN DEFAULT 0"),
            ("data_quality_flag", "BOOLEAN DEFAULT 0"),
        ]

        with db.engine.connect() as conn:
            for col_name, col_def in user_migrations:
                if col_name not in existing_user_cols:
                    conn.execute(text(f"ALTER TABLE user ADD COLUMN {col_name} {col_def}"))
            for col_name, col_def in trip_migrations:
                if col_name not in existing_trip_cols:
                    conn.execute(text(f"ALTER TABLE trip ADD COLUMN {col_name} {col_def}"))

            # Ensure indexes exist on Trip.user_id and Trip.trip_date (Req 26)
            existing_trip_indexes = {idx["name"] for idx in inspector.get_indexes("trip")}
            if "ix_trip_user_id" not in existing_trip_indexes:
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_trip_user_id ON trip (user_id)"))
            if "ix_trip_trip_date" not in existing_trip_indexes:
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_trip_trip_date ON trip (trip_date)"))

            # Ensure analyst table exists (db.create_all handles new tables)
            if "analyst" not in existing_tables:
                db.create_all()

            conn.commit()
