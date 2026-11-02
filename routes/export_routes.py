import io

from flask import Blueprint, jsonify, send_file

from decorators import any_authenticated
from extensions import get_db
from utils.serialize import oid, str_id
from routes.project_permissions import get_accessible_project
from utils.export_pdf import build_page_pdf
from utils.export_excel import build_page_excel, build_project_excel

bp = Blueprint("export", __name__, url_prefix="/api")


@bp.get("/pages/<page_id>/export/pdf")
@any_authenticated
def export_page_pdf(page_id):
    db = get_db()

    pgid = oid(page_id)
    if not pgid:
        return jsonify({"error": "Invalid page id"}), 400

    # Fetch the page, then verify access to its parent project.
    page = db.pages.find_one({"_id": pgid})
    if not page:
        return jsonify({"error": "Page not found"}), 404

    project_id = page.get("project_id")
    if not project_id:
        return jsonify({"error": "Page project not found"}), 404

    _, project = get_accessible_project(str(project_id))
    if not project:
        # Do not reveal whether an inaccessible project exists.
        return jsonify({"error": "Page not found"}), 404

    pdf_bytes = build_page_pdf(
        str_id(page),
        project.get("name", ""),
    )

    filename = f"{page.get('name', 'page')}-parity-review.pdf".replace(" ", "_")

    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=filename,
    )


@bp.get("/pages/<page_id>/export/excel")
@any_authenticated
def export_page_excel(page_id):
    db = get_db()

    pgid = oid(page_id)
    if not pgid:
        return jsonify({"error": "Invalid page id"}), 400

    # Fetch the page, then verify access to its parent project.
    page = db.pages.find_one({"_id": pgid})
    if not page:
        return jsonify({"error": "Page not found"}), 404

    project_id = page.get("project_id")
    if not project_id:
        return jsonify({"error": "Page project not found"}), 404

    _, project = get_accessible_project(str(project_id))
    if not project:
        return jsonify({"error": "Page not found"}), 404

    xlsx_bytes = build_page_excel(str_id(page))

    filename = f"{page.get('name', 'page')}-parity-review.xlsx".replace(" ", "_")

    return send_file(
        io.BytesIO(xlsx_bytes),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=filename,
    )


@bp.get("/projects/<project_id>/export/excel")
@any_authenticated
def export_project_excel(project_id):
    db = get_db()

    pid = oid(project_id)
    if not pid:
        return jsonify({"error": "Invalid project id"}), 400

    # Verify project access before retrieving any of its pages.
    _, project = get_accessible_project(project_id)
    if not project:
        return jsonify({"error": "Project not found"}), 404

    pages = [
        str_id(page)
        for page in db.pages.find({"project_id": pid}).sort("name", 1)
    ]

    xlsx_bytes = build_project_excel(project["name"], pages)
    filename = f"{project['name']}-parity-summary.xlsx".replace(" ", "_")

    return send_file(
        io.BytesIO(xlsx_bytes),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=filename,
    )
