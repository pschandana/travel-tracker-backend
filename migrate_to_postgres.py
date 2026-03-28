"""
One-time migration: copies all data from local SQLite (app.db)
to a remote PostgreSQL database on Render.

Usage:
    python migrate_to_postgres.py <POSTGRES_URL>

Example:
    python migrate_to_postgres.py postgresql://user:pass@host/dbname
"""
import sys
import sqlite3
import psycopg2
from datetime import datetime

if len(sys.argv) < 2:
    print("Usage: python migrate_to_postgres.py <POSTGRES_URL>")
    sys.exit(1)

PG_URL = sys.argv[1]
SQLITE_PATH = "instance/app.db"

print(f"Connecting to SQLite: {SQLITE_PATH}")
sqlite_conn = sqlite3.connect(SQLITE_PATH)
sqlite_conn.row_factory = sqlite3.Row
sc = sqlite_conn.cursor()

print(f"Connecting to PostgreSQL...")
pg_conn = psycopg2.connect(PG_URL)
pg_conn.autocommit = False
pc = pg_conn.cursor()

# ── Create tables on PostgreSQL ───────────────────────────────────────────────
print("Creating tables...")
pc.execute("""
CREATE TABLE IF NOT EXISTS "user" (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100),
    email VARCHAR(120) UNIQUE NOT NULL,
    password VARCHAR(200) NOT NULL,
    photo TEXT,
    mobile VARCHAR(15) NOT NULL DEFAULT '',
    place VARCHAR(100) NOT NULL DEFAULT '',
    otp_code VARCHAR(6),
    otp_expiry TIMESTAMP,
    is_verified BOOLEAN DEFAULT FALSE,
    language VARCHAR(10) DEFAULT 'en',
    theme VARCHAR(10) DEFAULT 'light',
    consent_given BOOLEAN DEFAULT FALSE,
    consent_timestamp TIMESTAMP,
    consent_withdrawn_at TIMESTAMP
)
""")

pc.execute("""
CREATE TABLE IF NOT EXISTS analyst (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(120) UNIQUE NOT NULL,
    password VARCHAR(200) NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
)
""")

pc.execute("""
CREATE TABLE IF NOT EXISTS trip_chain (
    id SERIAL PRIMARY KEY,
    chain_id VARCHAR(50) UNIQUE NOT NULL,
    user_id INTEGER NOT NULL,
    label VARCHAR(200),
    total_duration FLOAT,
    total_distance FLOAT,
    legs_count INTEGER,
    mode_sequence JSON,
    created_at TIMESTAMP DEFAULT NOW()
)
""")

pc.execute("""
CREATE TABLE IF NOT EXISTS trip (
    id SERIAL PRIMARY KEY,
    trip_no VARCHAR(50) UNIQUE,
    user_id INTEGER,
    start_lat FLOAT,
    start_lng FLOAT,
    end_lat FLOAT,
    end_lng FLOAT,
    start_time VARCHAR(50),
    end_time VARCHAR(50),
    trip_date DATE,
    created_at TIMESTAMP DEFAULT NOW(),
    distance FLOAT,
    duration FLOAT,
    mode VARCHAR(50),
    purpose VARCHAR(100),
    cost FLOAT,
    companions INTEGER,
    frequency INTEGER DEFAULT 1,
    ml_mode VARCHAR(50),
    confidence_score FLOAT,
    chain_id VARCHAR(50),
    is_incomplete BOOLEAN DEFAULT FALSE,
    has_gps_gap BOOLEAN DEFAULT FALSE,
    data_quality_flag BOOLEAN DEFAULT FALSE,
    route JSON,
    map_image TEXT
)
""")

pc.execute("""
CREATE TABLE IF NOT EXISTS audit_log (
    id SERIAL PRIMARY KEY,
    operation VARCHAR(20) NOT NULL,
    table_name VARCHAR(50) NOT NULL,
    record_id INTEGER NOT NULL,
    user_id INTEGER,
    timestamp TIMESTAMP DEFAULT NOW()
)
""")

pc.execute("""
CREATE TABLE IF NOT EXISTS consent_record (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    permission_type VARCHAR(50) NOT NULL,
    granted_at TIMESTAMP DEFAULT NOW(),
    withdrawn_at TIMESTAMP
)
""")

pg_conn.commit()
print("Tables created.")

# ── Migrate users ─────────────────────────────────────────────────────────────
sc.execute('SELECT * FROM "user"')
users = sc.fetchall()
print(f"Migrating {len(users)} users...")
for u in users:
    pc.execute("""
        INSERT INTO "user" (id, name, email, password, photo, mobile, place,
            otp_code, otp_expiry, is_verified, language, theme,
            consent_given, consent_timestamp, consent_withdrawn_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (email) DO NOTHING
    """, (
        u["id"], u["name"], u["email"], u["password"], u["photo"],
        u["mobile"] or "", u["place"] or "",
        u["otp_code"], u["otp_expiry"], bool(u["is_verified"]),
        u["language"] or "en", u["theme"] or "light",
        bool(u["consent_given"]), u["consent_timestamp"], u["consent_withdrawn_at"]
    ))

# ── Migrate analysts ──────────────────────────────────────────────────────────
sc.execute("SELECT * FROM analyst")
analysts = sc.fetchall()
print(f"Migrating {len(analysts)} analysts...")
for a in analysts:
    pc.execute("""
        INSERT INTO analyst (id, name, email, password, created_at)
        VALUES (%s,%s,%s,%s,%s)
        ON CONFLICT (email) DO NOTHING
    """, (a["id"], a["name"], a["email"], a["password"], a["created_at"]))

# ── Migrate trips ─────────────────────────────────────────────────────────────
sc.execute("SELECT * FROM trip")
trips = sc.fetchall()
print(f"Migrating {len(trips)} trips...")
for t in trips:
    pc.execute("""
        INSERT INTO trip (id, trip_no, user_id, start_lat, start_lng, end_lat, end_lng,
            start_time, end_time, trip_date, created_at, distance, duration,
            mode, purpose, cost, companions, frequency, ml_mode, confidence_score,
            chain_id, is_incomplete, has_gps_gap, data_quality_flag, route, map_image)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (trip_no) DO NOTHING
    """, (
        t["id"], t["trip_no"], t["user_id"],
        t["start_lat"], t["start_lng"], t["end_lat"], t["end_lng"],
        t["start_time"], t["end_time"], t["trip_date"], t["created_at"],
        t["distance"], t["duration"], t["mode"], t["purpose"],
        t["cost"], t["companions"], t["frequency"] or 1,
        t["ml_mode"], t["confidence_score"], t["chain_id"],
        bool(t["is_incomplete"]), bool(t["has_gps_gap"]), bool(t["data_quality_flag"]),
        t["route"], t["map_image"]
    ))

# ── Reset sequences so new inserts don't conflict ─────────────────────────────
seq_map = {
    '"user"': 'user_id_seq',
    'analyst': 'analyst_id_seq',
    'trip': 'trip_id_seq',
    'audit_log': 'audit_log_id_seq',
    'consent_record': 'consent_record_id_seq',
}
for table, seq in seq_map.items():
    try:
        pc.execute(f"SELECT setval('{seq}', COALESCE((SELECT MAX(id) FROM {table}), 1))")
    except Exception as e:
        print(f"  Sequence reset skipped for {table}: {e}")
        pg_conn.rollback()

pg_conn.commit()
sqlite_conn.close()
pg_conn.close()

print("\n✅ Migration complete!")
print(f"   Users:    {len(users)}")
print(f"   Analysts: {len(analysts)}")
print(f"   Trips:    {len(trips)}")
