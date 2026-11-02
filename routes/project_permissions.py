
from flask_jwt_extended import get_jwt
from extensions import get_db
from utils.serialize import oid


def is_demo_user():
    """
    Check whether the current authenticated user is a demo visitor.
    Demo identification comes from the JWT, not the username.
    """
    claims = get_jwt()
    return claims.get("is_demo", False) is True


def get_demo_session_id():
    """
    Every demo login must have its own unique session ID.
    This ID is generated during login and stored in the JWT.
    """
    claims = get_jwt()

    if not claims.get("is_demo", False):
        return None

    return claims.get("demo_session_id")


def get_project_access_filter():
    """
    Return the MongoDB filter for projects accessible to the
    currently authenticated user.

    Real users:
        Access projects according to their existing permissions.

    Demo visitors:
        Access only projects created in their own demo session.
    """
    if is_demo_user():
        session_id = get_demo_session_id()

        # Fail closed if the token has no session ID.
        if not session_id:
            return {"_id": None}

        return {
            "demo_session_id": session_id,
            "is_demo_visible": True,
        }

    return {}


def get_accessible_project(project_id):
    """
    Return a project only if the current user is allowed to access it.

    Demo visitors can access only projects belonging to their
    individual demo session.
    """
    pid = oid(project_id)

    if not pid:
        return None, None

    query = {"_id": pid}
    query.update(get_project_access_filter())

    project = get_db().projects.find_one(query)

    return pid, project
