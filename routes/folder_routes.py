
from flask import Blueprint, request, jsonify

from decorators import roles_required, any_authenticated
from extensions import get_db
from utils.serialize import oid, str_id
from routes.project_permissions import get_accessible_project

bp = Blueprint("folders", __name__, url_prefix="/api")


@bp.post("/projects/<project_id>/folders")
@roles_required("admin", "demo")
def create_folder(project_id):
    body = request.get_json(silent=True) or {}

    name = (body.get("name") or "").strip()
    parent_id_raw = body.get("parent_id")

    if not name:
        return jsonify({
            "error": "Folder name is required"
        }), 400

    db = get_db()

    # Verify that the current user can access this project.
    pid, project = get_accessible_project(project_id)

    if not pid:
        return jsonify({
            "error": "Invalid project id"
        }), 400

    if not project:
        return jsonify({
            "error": "Project not found"
        }), 404

    parent_id = None

    if parent_id_raw:
        parent_id = oid(parent_id_raw)

        if not parent_id:
            return jsonify({
                "error": "Invalid parent folder id"
            }), 400

        parent_folder = db.folders.find_one({
            "_id": parent_id,
            "project_id": pid,
        })

        if not parent_folder:
            return jsonify({
                "error": "Parent folder not found in this project"
            }), 400

    doc = {
        "project_id": pid,
        "parent_id": parent_id,
        "name": name,
    }

    result = db.folders.insert_one(doc)
    doc["_id"] = result.inserted_id

    return jsonify(str_id(doc)), 201


@bp.delete("/folders/<folder_id>")
@roles_required("admin", "demo")
def delete_folder(folder_id):
    db = get_db()

    fid = oid(folder_id)

    if not fid:
        return jsonify({
            "error": "Invalid folder id"
        }), 400

    # Find the folder first to identify its project.
    folder = db.folders.find_one({
        "_id": fid
    })

    if not folder:
        return jsonify({
            "error": "Folder not found"
        }), 404

    project_id = folder.get("project_id")

    # Verify access to the folder's project.
    pid, project = get_accessible_project(str(project_id))

    if not pid:
        return jsonify({
            "error": "Invalid project id"
        }), 400

    if not project:
        return jsonify({
            "error": "Folder not found"
        }), 404

    # Recursively collect descendant folders,
    # restricting every query to this project.
    to_delete = [fid]
    frontier = [fid]

    while frontier:
        children = list(
            db.folders.find(
                {
                    "project_id": pid,
                    "parent_id": {
                        "$in": frontier
                    },
                },
                {
                    "_id": 1
                },
            )
        )

        child_ids = [
            child["_id"]
            for child in children
        ]

        to_delete.extend(child_ids)
        frontier = child_ids

    # Delete pages inside the selected folder tree.
    db.pages.delete_many({
        "project_id": pid,
        "folder_id": {
            "$in": to_delete
        },
    })

    # Delete only folders belonging to this project.
    result = db.folders.delete_many({
        "project_id": pid,
        "_id": {
            "$in": to_delete
        },
    })

    if result.deleted_count == 0:
        return jsonify({
            "error": "Folder not found"
        }), 404

    return jsonify({
        "ok": True,
        "deleted_folders": result.deleted_count,
    })


@bp.get("/projects/<project_id>/folders")
@any_authenticated
def list_folders_flat(project_id):
    """
    Flat list with computed breadcrumb label.
    Used to populate the folder select in modals.
    """

    db = get_db()

    # Verify project access before returning its folders.
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

    by_id = {
        folder["_id"]: folder
        for folder in folders
    }

    def label(folder):
        parts = [folder["name"]]
        current = folder

        while current.get("parent_id"):
            current = by_id.get(current["parent_id"])

            if not current:
                break

            parts.append(current["name"])

        return " / ".join(reversed(parts))

    return jsonify([
        {
            "id": str(folder["_id"]),
            "label": label(folder),
        }
        for folder in folders
    ])
