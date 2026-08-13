from flask import Blueprint, request, jsonify

from decorators import roles_required, any_authenticated
from extensions import get_db
from utils.serialize import oid, str_id

bp = Blueprint("folders", __name__, url_prefix="/api")


@bp.post("/projects/<project_id>/folders")
@roles_required("admin")
def create_folder(project_id):
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    parent_id_raw = body.get("parent_id")

    if not name:
        return jsonify({"error": "Folder name is required"}), 400

    db = get_db()
    pid = oid(project_id)
    if not pid or not db.projects.find_one({"_id": pid}):
        return jsonify({"error": "Project not found"}), 404

    parent_id = None
    if parent_id_raw:
        parent_id = oid(parent_id_raw)
        if not parent_id or not db.folders.find_one({"_id": parent_id, "project_id": pid}):
            return jsonify({"error": "Parent folder not found in this project"}), 400

    doc = {"project_id": pid, "parent_id": parent_id, "name": name}
    result = db.folders.insert_one(doc)
    doc["_id"] = result.inserted_id
    return jsonify(str_id(doc)), 201


@bp.delete("/folders/<folder_id>")
@roles_required("admin")
def delete_folder(folder_id):
    db = get_db()
    fid = oid(folder_id)
    if not fid:
        return jsonify({"error": "Invalid folder id"}), 400

    # Recursively collect all descendant folder ids
    to_delete = [fid]
    frontier = [fid]
    while frontier:
        children = list(db.folders.find({"parent_id": {"$in": frontier}}, {"_id": 1}))
        child_ids = [c["_id"] for c in children]
        to_delete.extend(child_ids)
        frontier = child_ids

    db.pages.delete_many({"folder_id": {"$in": to_delete}})
    result = db.folders.delete_many({"_id": {"$in": to_delete}})
    if result.deleted_count == 0:
        return jsonify({"error": "Folder not found"}), 404
    return jsonify({"ok": True, "deleted_folders": result.deleted_count})


@bp.get("/projects/<project_id>/folders")
@any_authenticated
def list_folders_flat(project_id):
    """Flat list with computed breadcrumb label - used to populate the 'folder' <select> in modals."""
    db = get_db()
    pid = oid(project_id)
    if not pid:
        return jsonify({"error": "Invalid project id"}), 400

    folders = list(db.folders.find({"project_id": pid}))
    by_id = {f["_id"]: f for f in folders}

    def label(f):
        parts = [f["name"]]
        cur = f
        while cur.get("parent_id"):
            cur = by_id.get(cur["parent_id"])
            if not cur:
                break
            parts.append(cur["name"])
        return " / ".join(reversed(parts))

    return jsonify([{"id": str(f["_id"]), "label": label(f)} for f in folders])
