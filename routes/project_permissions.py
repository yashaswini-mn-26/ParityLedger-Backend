
from flask_jwt_extended import get_jwt
from extensions import get_db
from utils.serialize import oid


def is_demo_user():
    """Check whether the authenticated user is a demo visitor."""
    claims = get_jwt()
    return claims.get("is_demo", False) is True


def get_demo_visitor_id():
    """Get the persistent demo visitor ID from the JWT."""
    claims = get_jwt()

    if not claims.get("is_demo", False):
        return None

    return claims.get("demo_visitor_id")


def get_project_access_filter():
    """
    Demo users:
        Access only projects belonging to their persistent visitor ID.

    Real users:
        Never access demo projects.
        Preserve existing real-project access behavior.
    """
    if is_demo_user():
        visitor_id = get_demo_visitor_id()

        if not visitor_id:
            return {"_id": None}

        return {
            "demo_visitor_id": visitor_id,
            "is_demo_visible": True,
        }

    # Real users cannot access demo projects.
    return {
        "is_demo_visible": {"$ne": True}
    }


def get_accessible_project(project_id):
    """Return a project only if it is accessible to the current user."""
    pid = oid(project_id)

    if not pid:
        return None, None

    query = {"_id": pid}
    query.update(get_project_access_filter())

    project = get_db().projects.find_one(query)

    return pid, project
