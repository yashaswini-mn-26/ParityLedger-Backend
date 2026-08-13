import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()


def _required(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            f"Copy .env.example to .env and fill it in."
        )
    return val


class Config:
    MONGO_URI = _required("MONGO_URI")
    MONGO_DB_NAME = os.environ.get("MONGO_DB_NAME", "parity_ledger")

    JWT_SECRET_KEY = _required("JWT_SECRET_KEY")
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(
        minutes=int(os.environ.get("JWT_ACCESS_TOKEN_EXPIRES_MIN", "480"))
    )
    JWT_TOKEN_LOCATION = ["headers"]

    CORS_ORIGINS = [
        o.strip() for o in os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()
    ]

    PORT = int(os.environ.get("PORT", "5000"))
    DEBUG = os.environ.get("FLASK_ENV", "production") != "production"

    # Max size (bytes) for base64 image payloads (comments / comparison screenshots)
    MAX_IMAGE_BYTES = 4 * 1024 * 1024
    MAX_CONTENT_LENGTH = 12 * 1024 * 1024  # overall request body cap
