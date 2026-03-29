"""
Run this once on Render to seed default demo accounts.
Usage: python seed_default_users.py
"""
from app import app, db
from models import User
from flask_bcrypt import Bcrypt

bcrypt = Bcrypt(app)

DEFAULT_USERS = [
    {"name": "Chandana", "email": "pschandana2924@gmail.com", "place": "Hyderabad", "password": "123456"},
    {"name": "Bhavana",  "email": "bhavana2k5sistla@gmail.com", "place": "Hyderabad", "password": "123456"},
    {"name": "Khamidha", "email": "skhamidha08@gmail.com",      "place": "Hyderabad", "password": "123456"},
    {"name": "Srihana",  "email": "skrihana628@gmail.com",      "place": "Hyderabad", "password": "123456"},
]

with app.app_context():
    for u in DEFAULT_USERS:
        existing = User.query.filter_by(email=u["email"]).first()
        if existing:
            # Update password in case it changed
            existing.password = bcrypt.generate_password_hash(u["password"]).decode("utf-8")
            print(f"Updated: {u['email']}")
        else:
            user = User(
                name=u["name"],
                email=u["email"],
                mobile="",
                place=u["place"],
                password=bcrypt.generate_password_hash(u["password"]).decode("utf-8"),
            )
            db.session.add(user)
            print(f"Created: {u['email']}")
    db.session.commit()
    print("✅ Default users seeded successfully")
