from flask import Blueprint, request, jsonify
from flask_jwt_extended import create_access_token, get_jwt_identity, get_jwt

from auth import (
    find_user_by_username,
    find_user_by_id,
    create_user,
    verify_password,
    serialize_user,
    VALID_ROLES,
)
from decorators import roles_required, any_authenticated
from extensions import get_db

bp = Blueprint("auth", __name__, url_prefix="/api/auth")


@bp.post("/login")
def login():
    body = request.get_json(silent=True) or {}
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    if not username or not password:
        return jsonify({"error": "username and password are required"}), 400

    user = find_user_by_username(username)
    if not user or not verify_password(password, user["password_hash"]):
        return jsonify({"error": "Invalid username or password"}), 401

    token = create_access_token(
        identity=str(user["_id"]),
        additional_claims={"role": user.get("role", "user"), "name": user.get("name")},
    )
    return jsonify({"token": token, "user": serialize_user(user)})


@bp.get("/me")
@any_authenticated
def me():
    user_id = get_jwt_identity()
    user = find_user_by_id(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404
    return jsonify(serialize_user(user))


@bp.post("/users")
@roles_required("admin")
def create_user_route():
    """Admin-only: create a login for a user/developer/admin."""
    body = request.get_json(silent=True) or {}
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    name = body.get("name") or username
    role = body.get("role") or "user"

    if not username or not password:
        return jsonify({"error": "username and password are required"}), 400
    if len(password) < 6:
        return jsonify({"error": "password must be at least 6 characters"}), 400
    if role not in VALID_ROLES:
        return jsonify({"error": f"role must be one of {sorted(VALID_ROLES)}"}), 400

    try:
        user = create_user(username, password, name, role)
    except ValueError as e:
        return jsonify({"error": str(e)}), 409

    return jsonify(serialize_user(user)), 201


@bp.get("/users")
@roles_required("admin")
def list_users():
    db = get_db()
    users = [serialize_user(u) for u in db.users.find().sort("name", 1)]
    return jsonify(users)


@bp.get("/developers")
@any_authenticated
def list_developers():
    """Any authenticated user can fetch the developer list to populate an 'assign to' dropdown."""
    db = get_db()
    devs = [serialize_user(u) for u in db.users.find({"role": "developer"}).sort("name", 1)]
    return jsonify(devs)
