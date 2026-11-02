
import uuid

from flask import Blueprint, request, jsonify
from flask_jwt_extended import (
    create_access_token,
    get_jwt_identity,
    get_jwt,
)

from auth import (
    find_user_by_username,
    find_user_by_id,
    create_user,
    verify_password,
    serialize_user,
)
from decorators import roles_required, any_authenticated
from extensions import get_db

bp = Blueprint("auth", __name__, url_prefix="/api/auth")


# Public demo credentials
DEMO_USERNAME = "admin"
DEMO_PASSWORD = "admin123"

# Roles that a real admin can assign.
# The demo role is deliberately excluded.
ASSIGNABLE_ROLES = {"admin", "user", "developer"}


@bp.post("/login")
def login():
    body = request.get_json(silent=True) or {}

    username = (body.get("username") or "").strip()
    password = body.get("password") or ""

    if not username or not password:
        return jsonify({
            "error": "username and password are required"
        }), 400

    user = find_user_by_username(username)

    if not user or not verify_password(password, user["password_hash"]):
        return jsonify({
            "error": "Invalid username or password"
        }), 401

    # Only the exact public demo credentials receive demo access.
    is_demo = (
        username.lower() == DEMO_USERNAME
        and password == DEMO_PASSWORD
    )

    # Give every demo login its own isolated workspace.
    demo_session_id = uuid.uuid4().hex if is_demo else None

    token_role = "demo" if is_demo else user.get("role", "user")

    additional_claims = {
        "role": token_role,
        "name": user.get("name"),
        "is_demo": is_demo,
    }

    if is_demo:
        additional_claims["demo_session_id"] = demo_session_id

    token = create_access_token(
        identity=str(user["_id"]),
        additional_claims=additional_claims,
    )

    user_data = serialize_user(user)

    user_data["is_demo"] = is_demo

    if is_demo:
        user_data["role"] = "demo"

    return jsonify({
        "token": token,
        "user": user_data,
    })


@bp.get("/me")
@any_authenticated
def me():
    user_id = get_jwt_identity()
    claims = get_jwt()

    user = find_user_by_id(user_id)

    if not user:
        return jsonify({
            "error": "User not found"
        }), 404

    user_data = serialize_user(user)

    is_demo = claims.get("is_demo", False) is True

    user_data["is_demo"] = is_demo

    if is_demo:
        user_data["role"] = "demo"

    return jsonify(user_data)


@bp.post("/users")
@roles_required("admin")
def create_user_route():
    """Real admin only: create a login for a user/developer/admin."""

    body = request.get_json(silent=True) or {}

    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    name = (body.get("name") or username).strip()
    role = body.get("role") or "user"

    if not username or not password:
        return jsonify({
            "error": "username and password are required"
        }), 400

    if len(password) < 6:
        return jsonify({
            "error": "password must be at least 6 characters"
        }), 400

    if role not in ASSIGNABLE_ROLES:
        return jsonify({
            "error": f"role must be one of {sorted(ASSIGNABLE_ROLES)}"
        }), 400

    try:
        user = create_user(username, password, name, role)
    except ValueError as e:
        return jsonify({
            "error": str(e)
        }), 409

    return jsonify(serialize_user(user)), 201


@bp.get("/users")
@roles_required("admin")
def list_users():
    """Real admin only: list all registered users."""

    db = get_db()

    users = [
        serialize_user(user)
        for user in db.users.find().sort("name", 1)
    ]

    return jsonify(users)


@bp.get("/developers")
@any_authenticated
def list_developers():
    """
    Authenticated non-demo users can fetch developers
    for assignment dropdowns.
    """

    claims = get_jwt()

    # Never expose real developer accounts to public demo visitors.
    if claims.get("is_demo") is True:
        return jsonify([])

    db = get_db()

    developers = [
        serialize_user(user)
        for user in db.users.find({
            "role": "developer"
        }).sort("name", 1)
    ]

    return jsonify(developers)
