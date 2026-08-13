from flask import Blueprint, request, jsonify

from decorators import any_authenticated
from extensions import get_db
from utils.serialize import oid, str_id
from routes.page_routes import _page_summary

bp = Blueprint("search", __name__, url_prefix="/api")


@bp.get("/projects/<project_id>/search")
@any_authenticated
def search_pages(project_id):
    q = (request.args.get("q") or "").strip()
    status = request.args.get("status")

    db = get_db()
    pid = oid(project_id)
    if not pid:
        return jsonify({"error": "Invalid project id"}), 400

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

    pages = list(db.pages.find(query).sort("name", 1))
    return jsonify([_page_summary(p) for p in pages])