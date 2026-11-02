
from flask import Blueprint, request, jsonify

from decorators import any_authenticated
from extensions import get_db
from utils.serialize import oid
from routes.project_permissions import get_accessible_project
from routes.page_routes import _page_summary

bp = Blueprint("search", __name__, url_prefix="/api")

# Exclude images and heavy history from search results — only counts/metadata
# are shown in the results table, same as the dashboard.
_SEARCH_PROJECTION = {
    "comparison.vbImages": 0,
    "comparison.migImages": 0,
    "comments": 0,
    "reviews": 0,
    "approvals": 0,
}


@bp.get("/projects/<project_id>/search")
@any_authenticated
def search_pages(project_id):
    q = (request.args.get("q") or "").strip()
    status = request.args.get("status")

    db = get_db()

    pid = oid(project_id)
    if not pid:
        return jsonify({"error": "Invalid project id"}), 400

    # Verify that the current user can access this project.
    _, project = get_accessible_project(project_id)

    if not project:
        return jsonify({"error": "Project not found"}), 404

    query = {"project_id": pid}

    if status and status != "all":
        query["status"] = status

    if q:
        # Regex search across name/path plus nested api/query fields.
        rx = {"$regex": q, "$options": "i"}
        query["$or"] = [
            {"name": rx},
            {"path": rx},
            {"verdict": rx},
            {"apis.name": rx},
            {"apis.queries.sql": rx},
            {"apis.queries.tables": rx},
            {"apis.queries.notes": rx},
        ]

    pages = list(
        db.pages.find(query, _SEARCH_PROJECTION).sort("name", 1)
    )

    return jsonify([_page_summary(p) for p in pages])
