
from datetime import datetime, timezone

from flask import Blueprint, request, jsonify
from flask_jwt_extended import (
    get_jwt_identity,
    get_jwt,
)

from decorators import roles_required, any_authenticated
from extensions import get_db
from utils.serialize import oid, str_id
from routes.project_permissions import (
    get_project_access_filter,
    get_accessible_project,
)

bp = Blueprint("projects", __name__, url_prefix="/api/projects")


@bp.get("")
@any_authenticated
def list_projects():
    db = get_db()

    # Admins can see all projects.
    # Demo users can see only projects from their own session.
    query = get_project_access_filter()

    projects = list(
        db.projects.find(query).sort("created_at", -1)
    )

    result = []

    for project in projects:
        page_count = db.pages.count_documents({
            "project_id": project["_id"]
        })

        folder_count = db.folders.count_documents({
            "project_id": project["_id"]
        })

        item = str_id(project)
        item["page_count"] = page_count
        item["folder_count"] = folder_count

        result.append(item)

    return jsonify(result)


@bp.post("")
@roles_required("admin", "demo")
def create_project():
    body = request.get_json(silent=True) or {}

    name = (body.get("name") or "").strip()
    description = (body.get("description") or "").strip()

    if not name:
        return jsonify({
            "error": "Project name is required"
        }), 400

    db = get_db()
    claims = get_jwt()

    is_demo = claims.get("is_demo", False) is True

    # Build a name check scoped to the current owner.
    duplicate_query = {"name": name}

    if is_demo:
        session_id = claims.get("demo_session_id")

        if not session_id:
            return jsonify({
                "error": "Demo session is invalid. Please log in again."
            }), 403

        duplicate_query["demo_session_id"] = session_id

    else:
        # Real admin project names are checked globally.
        duplicate_query["demo_session_id"] = {
            "$in": [None, ""]
        }

    if db.projects.find_one(duplicate_query):
        return jsonify({
            "error": "A project with this name already exists"
        }), 409

    doc = {
        "name": name,
        "description": description,
        "created_by": get_jwt_identity(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "is_demo_visible": is_demo,
        "demo_session_id": (
            claims.get("demo_session_id") if is_demo else None
        ),
    }

    result = db.projects.insert_one(doc)
    doc["_id"] = result.inserted_id

    return jsonify(str_id(doc)), 201


@bp.get("/<project_id>")
@any_authenticated
def get_project(project_id):
    pid = oid(project_id)

    if not pid:
        return jsonify({
            "error": "Invalid project id"
        }), 400

    pid, project = get_accessible_project(project_id)

    if not project:
        return jsonify({
            "error": "Project not found"
        }), 404

    return jsonify(str_id(project))


@bp.delete("/<project_id>")
@roles_required("admin", "demo")
def delete_project(project_id):
    db = get_db()

    pid = oid(project_id)

    if not pid:
        return jsonify({
            "error": "Invalid project id"
        }), 400

    # Verify ownership/access before deleting anything.
    accessible_pid, project = get_accessible_project(project_id)

    if not project:
        return jsonify({
            "error": "Project not found"
        }), 404

    # Delete only data belonging to this project.
    db.pages.delete_many({
        "project_id": accessible_pid
    })

    db.folders.delete_many({
        "project_id": accessible_pid
    })

    result = db.projects.delete_one({
        "_id": accessible_pid
    })

    if result.deleted_count == 0:
        return jsonify({
            "error": "Project not found"
        }), 404

    return jsonify({
        "ok": True
    })


@bp.get("/<project_id>/tree")
@any_authenticated
def project_tree(project_id):
    """Nested folder/page tree for the sidebar."""

    db = get_db()

    pid, project = get_accessible_project(project_id)

    if not pid:
        return jsonify({
            "error": "Invalid project id"
        }), 400

    if not project:
        return jsonify({
            "error": "Project not found"
        }), 404

    folders = list(
        db.folders.find({
            "project_id": pid
        })
    )

    pages = list(
        db.pages.find(
            {"project_id": pid},
            {
                "name": 1,
                "folder_id": 1,
                "status": 1,
            },
        )
    )

    def build(parent_id):
        nodes = []

        for folder in folders:
            if folder.get("parent_id") == parent_id:
                nodes.append({
                    "id": str(folder["_id"]),
                    "type": "folder",
                    "name": folder["name"],
                    "children": build(folder["_id"]),
                })

        for page in pages:
            if page.get("folder_id") == parent_id:
                nodes.append({
                    "id": str(page["_id"]),
                    "type": "page",
                    "name": page["name"],
                    "status": page.get("status", "pending"),
                })

        return nodes

    return jsonify(build(None))
