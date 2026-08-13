from datetime import datetime, timezone

from flask import Blueprint, request, jsonify
from flask_jwt_extended import get_jwt_identity

from decorators import roles_required, any_authenticated
from extensions import get_db
from utils.serialize import oid, str_id

bp = Blueprint("projects", __name__, url_prefix="/api/projects")


@bp.get("")
@any_authenticated
def list_projects():
    db = get_db()
    projects = list(db.projects.find().sort("created_at", -1))
    result = []
    for p in projects:
        page_count = db.pages.count_documents({"project_id": p["_id"]})
        folder_count = db.folders.count_documents({"project_id": p["_id"]})
        item = str_id(p)
        item["page_count"] = page_count
        item["folder_count"] = folder_count
        result.append(item)
    return jsonify(result)


@bp.post("")
@roles_required("admin")
def create_project():
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    description = (body.get("description") or "").strip()
    if not name:
        return jsonify({"error": "Project name is required"}), 400

    db = get_db()
    if db.projects.find_one({"name": name}):
        return jsonify({"error": "A project with this name already exists"}), 409

    doc = {
        "name": name,
        "description": description,
        "created_by": get_jwt_identity(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    result = db.projects.insert_one(doc)
    doc["_id"] = result.inserted_id
    return jsonify(str_id(doc)), 201


@bp.get("/<project_id>")
@any_authenticated
def get_project(project_id):
    db = get_db()
    pid = oid(project_id)
    if not pid:
        return jsonify({"error": "Invalid project id"}), 400
    project = db.projects.find_one({"_id": pid})
    if not project:
        return jsonify({"error": "Project not found"}), 404
    return jsonify(str_id(project))


@bp.delete("/<project_id>")
@roles_required("admin")
def delete_project(project_id):
    db = get_db()
    pid = oid(project_id)
    if not pid:
        return jsonify({"error": "Invalid project id"}), 400
    db.pages.delete_many({"project_id": pid})
    db.folders.delete_many({"project_id": pid})
    result = db.projects.delete_one({"_id": pid})
    if result.deleted_count == 0:
        return jsonify({"error": "Project not found"}), 404
    return jsonify({"ok": True})


@bp.get("/<project_id>/tree")
@any_authenticated
def project_tree(project_id):
    """Nested folder/page tree for the sidebar."""
    db = get_db()
    pid = oid(project_id)
    if not pid:
        return jsonify({"error": "Invalid project id"}), 400

    folders = list(db.folders.find({"project_id": pid}))
    pages = list(
        db.pages.find(
            {"project_id": pid},
            {"name": 1, "folder_id": 1, "status": 1},
        )
    )

    def build(parent_id):
        nodes = []
        for f in folders:
            if f.get("parent_id") == parent_id:
                nodes.append(
                    {
                        "id": str(f["_id"]),
                        "type": "folder",
                        "name": f["name"],
                        "children": build(f["_id"]),
                    }
                )
        for p in pages:
            if p.get("folder_id") == parent_id:
                nodes.append(
                    {
                        "id": str(p["_id"]),
                        "type": "page",
                        "name": p["name"],
                        "status": p.get("status", "pending"),
                    }
                )
        return nodes

    return jsonify(build(None))
