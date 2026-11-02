
from datetime import datetime, timezone
from bson import ObjectId
from werkzeug.security import generate_password_hash, check_password_hash

from extensions import get_db

VALID_ROLES = {"admin", "user", "developer", "demo"}


def hash_password(raw: str) -> str:
    return generate_password_hash(raw)


def verify_password(raw: str, hashed: str) -> bool:
    return check_password_hash(hashed, raw)


def serialize_user(doc: dict) -> dict:
    return {
        "id": str(doc["_id"]),
        "username": doc["username"],
        "name": doc.get("name", doc["username"]),
        "role": doc.get("role", "user"),
        "created_at": doc.get("created_at"),
    }


def find_user_by_username(username: str):
    db = get_db()
    return db.users.find_one({"username": username.strip().lower()})


def find_user_by_id(user_id: str):
    db = get_db()
    try:
        return db.users.find_one({"_id": ObjectId(user_id)})
    except Exception:
        return None


def create_user(username: str, password: str, name: str, role: str = "user") -> dict:
    if role not in VALID_ROLES:
        raise ValueError(f"Invalid role '{role}'. Must be one of {sorted(VALID_ROLES)}")

    db = get_db()
    username_norm = username.strip().lower()

    if db.users.find_one({"username": username_norm}):
        raise ValueError("Username already exists")

    doc = {
        "username": username_norm,
        "name": name.strip() or username_norm,
        "password_hash": hash_password(password),
        "role": role,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    result = db.users.insert_one(doc)
    doc["_id"] = result.inserted_id

    return doc
