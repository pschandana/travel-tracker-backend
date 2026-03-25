import os
from datetime import timedelta

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "supersecret")
    db_url = os.environ.get("DATABASE_URL", "sqlite:///app.db")
    # Render gives postgres:// but SQLAlchemy needs postgresql://
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    SQLALCHEMY_DATABASE_URI = db_url
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "jwtsecretkey")
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=24)

    # EMAIL CONFIG (GMAIL SMTP)
    MAIL_SERVER = "smtp.gmail.com"
    MAIL_PORT = 587
    MAIL_USE_TLS = True
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME", "mraviteja.2807@gmail.com")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD", "wtug hqgr imbj okce")
