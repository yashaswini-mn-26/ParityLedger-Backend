from flask import Blueprint, jsonify, send_file
import io

from decorators import any_authenticated
from extensions import get_db
from utils.serialize import oid, str_id
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
    page = db.pages.find_one({"_id": pgid})
    if not page:
        return jsonify({"error": "Page not found"}), 404
    project = db.projects.find_one({"_id": page["project_id"]})

    pdf_bytes = build_page_pdf(str_id(page), project.get("name", "") if project else "")
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
    page = db.pages.find_one({"_id": pgid})
    if not page:
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
    project = db.projects.find_one({"_id": pid})
    if not project:
        return jsonify({"error": "Project not found"}), 404

    pages = [str_id(p) for p in db.pages.find({"project_id": pid}).sort("name", 1)]
    xlsx_bytes = build_project_excel(project["name"], pages)
    filename = f"{project['name']}-parity-summary.xlsx".replace(" ", "_")
    return send_file(
        io.BytesIO(xlsx_bytes),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=filename,
    )
