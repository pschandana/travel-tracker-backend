import io
import csv
from datetime import datetime

from flask import Blueprint, request, Response
from flask_jwt_extended import jwt_required, get_jwt_identity

from models import Trip

export_bp = Blueprint("export", __name__)


# ---------------- EXPORT TRIPS ----------------
@export_bp.route("/api/export")
@jwt_required()
def export_trips():
    uid = get_jwt_identity()

    start = request.args.get("start")
    end = request.args.get("end")

    query = Trip.query.filter_by(user_id=uid)

    if start and end:
        start_date = datetime.fromisoformat(start).date()
        end_date = datetime.fromisoformat(end).date()
        query = query.filter(
            Trip.trip_date >= start_date,
            Trip.trip_date <= end_date
        )

    trips = query.all()

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "Trip No", "Mode", "Distance", "Duration",
        "Cost", "Trip Date", "Start Time", "End Time", "Trip Purpose",
    ])

    for t in trips:
        writer.writerow([
            t.trip_no, t.mode, t.distance, t.duration,
            t.cost, t.trip_date, t.start_time, t.end_time, t.purpose,
        ])

    csv_data = output.getvalue()
    output.close()

    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=trips_report.csv"},
    )
