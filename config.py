"""
config.py — Central configuration for Arogo
"""
import os

class Config:
    # ── Database ──────────────────────────────────────────────
    DB_PATH = os.environ.get('MEDEASY_DB', 'medeasy.db')

    # ── File upload ───────────────────────────────────────────
    UPLOAD_FOLDER    = 'uploads'
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024          # 16 MB
    ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'txt', 'csv'}

    # ── OAuth credentials (set via .env) ─────────────────────
    STRAVA_CLIENT_ID     = os.environ.get('STRAVA_CLIENT_ID', '')
    STRAVA_CLIENT_SECRET = os.environ.get('STRAVA_CLIENT_SECRET', '')
    GARMIN_EMAIL         = os.environ.get('GARMIN_EMAIL', '')
    GARMIN_PASSWORD      = os.environ.get('GARMIN_PASSWORD', '')
    GOOGLE_CLIENT_ID     = os.environ.get('GOOGLE_CLIENT_ID', '')
    GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET', '')

    # ── App behaviour ─────────────────────────────────────────
    MAX_THOUGHTS_PER_DAY = 10
    SECRET_KEY           = os.environ.get('SECRET_KEY', 'dev-secret-change-in-production')
    DEBUG                = os.environ.get('FLASK_DEBUG', '1') == '1'


class ProductionConfig(Config):
    DEBUG = False
    DB_PATH = os.environ.get('MEDEASY_DB', '/data/medeasy.db')