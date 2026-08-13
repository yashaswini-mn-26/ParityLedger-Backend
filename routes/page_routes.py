import uuid
from datetime import datetime, timezone

from flask import Blueprint, request, jsonify
from flask_jwt_extended import get_jwt_identity, get_jwt

from decorators import roles_required, any_authenticated
from extensions import get_db
from utils.serialize import oid, str_id
from auth import find_user_by_id

bp = Blueprint("pages", __name__, url_prefix="/api")

VALID_STATUS = {"verified", "mismatch", "pending"}
VALID_QUERY_TYPES = {"SELECT", "INSERT", "UPDATE", "DELETE"}
MAX_IMAGE_BYTES = 4 * 1024 * 1024


def _now():
    return datetime.now(timezone.utc).isoformat()


def _check_image(data_url: str | None, field_name: str):
    if not data_url:
        return None
    if not data_url.startswith("data:image/"):
        raise ValueError(f"{field_name} must be a base64 image data URL")
    b64 = data_url.split(",", 1)[-1]
    approx_bytes = len(b64) * 3 / 4
    if approx_bytes > MAX_IMAGE_BYTES:
        raise ValueError(f"{field_name} exceeds the 4MB size limit")
    return data_url


def _sanitize_query(q: dict) -> dict:
    qtype = (q.get("type") or "SELECT").upper()
    if qtype not in VALID_QUERY_TYPES:
        qtype = "SELECT"
    return {
        "id": q.get("id") or str(uuid.uuid4())[:8],
        "type": qtype,
        "sql": (q.get("sql") or "").strip(),
        "vbSql": (q.get("vbSql") or "").strip(),
        "tables": [t.strip() for t in (q.get("tables") or []) if t and t.strip()],
        "columns": [c.strip() for c in (q.get("columns") or []) if c and c.strip()],
        "whereConditions": (q.get("whereConditions") or "").strip(),
        "maxRows": (q.get("maxRows") or "").strip(),
        "notes": (q.get("notes") or "").strip(),
    }


def _sanitize_api(a: dict) -> dict:
    return {
        "id": a.get("id") or str(uuid.uuid4())[:8],
        "name": (a.get("name") or "").strip(),
        "queries": [_sanitize_query(q) for q in (a.get("queries") or []) if (q.get("sql") or "").strip()],
    }


def _build_page_doc(body: dict, project_id, folder_id, existing: dict | None = None) -> dict:
    name = (body.get("name") or "").strip()
    if not name:
        raise ValueError("Page name is required")

    comparison = body.get("comparison") or {}
    vb_image = _check_image(comparison.get("vbImage"), "VB screenshot")
    mig_image = _check_image(comparison.get("migImage"), "Migrated screenshot")

    apis = [_sanitize_api(a) for a in (body.get("apis") or []) if (a.get("name") or "").strip()]
    workflow = [w.strip() for w in (body.get("workflow") or []) if w and w.strip()]

    doc = {
        "project_id": project_id,
        "folder_id": folder_id,
        "name": name,
        "path": (body.get("path") or "").strip(),
        "workflow": workflow,
        "comparison": {
            "vbNotes": (comparison.get("vbNotes") or "").strip(),
            "migNotes": (comparison.get("migNotes") or "").strip(),
            "vbImage": vb_image or (existing or {}).get("comparison", {}).get("vbImage", ""),
            "migImage": mig_image or (existing or {}).get("comparison", {}).get("migImage", ""),
        },
        "apis": apis,
        "updated_at": _now(),
    }
    if existing is None:
        doc.update(
            {
                "status": "pending",
                "verdict": "",
                "reviewed_by": None,
                "reviewed_by_name": "",
                "reviewed_date": None,
                "approved_by": None,
                "approved_by_name": "",
                "approved_date": None,
                "assigned_to": None,
                "assigned_to_name": "",
                "reviews": [],
                "approvals": [],
                "comments": [],
                "created_at": _now(),
            }
        )
    return doc


def _page_summary(p: dict) -> dict:
    """Lightweight shape for dashboard/table listing."""
    apis = p.get("apis") or []
    total = sum(len(a.get("queries") or []) for a in apis)
    tables = set()
    for a in apis:
        for q in a.get("queries") or []:
            tables.update(q.get("tables") or [])
    out = str_id(p)
    out.pop("comparison", None)
    out.pop("comments", None)
    out["api_count"] = len(apis)
    out["query_count"] = total
    out["table_count"] = len(tables)
    out.pop("apis", None)
    return out


@bp.get("/projects/<project_id>/pages")
@any_authenticated
def list_pages(project_id):
    db = get_db()
    pid = oid(project_id)
    if not pid:
        return jsonify({"error": "Invalid project id"}), 400
    pages = list(db.pages.find({"project_id": pid}).sort("name", 1))
    return jsonify([_page_summary(p) for p in pages])


@bp.post("/projects/<project_id>/pages")
@roles_required("admin")
def create_page(project_id):
    db = get_db()
    pid = oid(project_id)
    if not pid or not db.projects.find_one({"_id": pid}):
        return jsonify({"error": "Project not found"}), 404

    body = request.get_json(silent=True) or {}
    folder_id = None
    if body.get("folder_id"):
        folder_id = oid(body["folder_id"])
        if not folder_id or not db.folders.find_one({"_id": folder_id, "project_id": pid}):
            return jsonify({"error": "Folder not found in this project"}), 400

    try:
        doc = _build_page_doc(body, pid, folder_id)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    result = db.pages.insert_one(doc)
    doc["_id"] = result.inserted_id
    return jsonify(str_id(doc)), 201


@bp.get("/pages/<page_id>")
@any_authenticated
def get_page(page_id):
    db = get_db()
    pgid = oid(page_id)
    if not pgid:
        return jsonify({"error": "Invalid page id"}), 400
    page = db.pages.find_one({"_id": pgid})
    if not page:
        return jsonify({"error": "Page not found"}), 404
    return jsonify(str_id(page))


@bp.put("/pages/<page_id>")
@roles_required("admin")
def update_page(page_id):
    db = get_db()
    pgid = oid(page_id)
    if not pgid:
        return jsonify({"error": "Invalid page id"}), 400
    existing = db.pages.find_one({"_id": pgid})
    if not existing:
        return jsonify({"error": "Page not found"}), 404

    body = request.get_json(silent=True) or {}
    folder_id = existing.get("folder_id")
    if "folder_id" in body:
        folder_id = oid(body["folder_id"]) if body.get("folder_id") else None
        if body.get("folder_id") and not db.folders.find_one(
            {"_id": folder_id, "project_id": existing["project_id"]}
        ):
            return jsonify({"error": "Folder not found in this project"}), 400

    try:
        doc = _build_page_doc(body, existing["project_id"], folder_id, existing=existing)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    db.pages.update_one({"_id": pgid}, {"$set": doc})
    updated = db.pages.find_one({"_id": pgid})
    return jsonify(str_id(updated))


@bp.delete("/pages/<page_id>")
@roles_required("admin")
def delete_page(page_id):
    db = get_db()
    pgid = oid(page_id)
    if not pgid:
        return jsonify({"error": "Invalid page id"}), 400
    result = db.pages.delete_one({"_id": pgid})
    if result.deleted_count == 0:
        return jsonify({"error": "Page not found"}), 404
    return jsonify({"ok": True})


@bp.post("/pages/<page_id>/review")
@roles_required("user", "admin", "developer")
def review_page(page_id):
    """Any authenticated reviewer role can submit a review — all are kept in history.
    Admin/user reviews are official (drive page.status/verdict, reset approvals).
    Developer reviews are feedback: tracked and visible, but don't overwrite the verdict."""
    db = get_db()
    pgid = oid(page_id)
    if not pgid:
        return jsonify({"error": "Invalid page id"}), 400
    page = db.pages.find_one({"_id": pgid})
    if not page:
        return jsonify({"error": "Page not found"}), 404

    body = request.get_json(silent=True) or {}
    status = body.get("status")
    if status not in VALID_STATUS:
        return jsonify({"error": f"status must be one of {sorted(VALID_STATUS)}"}), 400
    verdict = (body.get("verdict") or "").strip()

    reviewer_id = get_jwt_identity()
    reviewer = find_user_by_id(reviewer_id)
    reviewer_name = reviewer.get("name") if reviewer else "Unknown"
    claims = get_jwt()
    reviewer_role = claims.get("role") or "user"
    now = _now()

    review = {
        "id": str(uuid.uuid4())[:8],
        "status": status,
        "verdict": verdict,
        "reviewed_by": reviewer_id,
        "reviewed_by_name": reviewer_name,
        "reviewed_by_role": reviewer_role,
        "reviewed_date": now,
    }

    update = {"updated_at": now}
    if reviewer_role in ("admin", "user"):
        update.update({
            "status": status,
            "verdict": verdict,
            "reviewed_by": reviewer_id,
            "reviewed_by_name": reviewer_name,
            "reviewed_date": now,
            # Official verdict changed — prior sign-offs must be re-issued
            "approved_by": None,
            "approved_by_name": "",
            "approved_date": None,
            "approvals": [],
        })

    db.pages.update_one({"_id": pgid}, {"$push": {"reviews": review}, "$set": update})
    updated = db.pages.find_one({"_id": pgid})
    return jsonify(str_id(updated))


@bp.post("/pages/<page_id>/approve")
@roles_required("admin")
def approve_page(page_id):
    """Admin sign-off. Multiple admins can each approve independently — all are kept in history."""
    db = get_db()
    pgid = oid(page_id)
    if not pgid:
        return jsonify({"error": "Invalid page id"}), 400
    page = db.pages.find_one({"_id": pgid})
    if not page:
        return jsonify({"error": "Page not found"}), 404

    has_official_review = any(
        r.get("reviewed_by_role") in ("admin", "user") for r in page.get("reviews", [])
    )
    if not has_official_review:
        return jsonify({"error": "Page must be reviewed by an admin or viewer before it can be approved"}), 400

    approver_id = get_jwt_identity()
    approver = find_user_by_id(approver_id)
    approver_name = approver.get("name") if approver else "Unknown"
    now = _now()

    if any(ap.get("approved_by") == approver_id for ap in page.get("approvals", [])):
        return jsonify({"error": "You have already approved this page"}), 400

    approval = {
        "id": str(uuid.uuid4())[:8],
        "approved_by": approver_id,
        "approved_by_name": approver_name,
        "approved_date": now,
    }

    update = {
        "approved_by": approver_id,
        "approved_by_name": approver_name,
        "approved_date": now,
        "updated_at": now,
    }
    db.pages.update_one({"_id": pgid}, {"$push": {"approvals": approval}, "$set": update})
    updated = db.pages.find_one({"_id": pgid})
    return jsonify(str_id(updated))


@bp.post("/pages/<page_id>/assign")
@roles_required("admin")
def assign_page(page_id):
    """Assign the page to a developer for fixing."""
    db = get_db()
    pgid = oid(page_id)
    if not pgid:
        return jsonify({"error": "Invalid page id"}), 400
    page = db.pages.find_one({"_id": pgid})
    if not page:
        return jsonify({"error": "Page not found"}), 404

    body = request.get_json(silent=True) or {}
    dev_id_raw = body.get("assigned_to")

    if not dev_id_raw:
        db.pages.update_one(
            {"_id": pgid},
            {"$set": {"assigned_to": None, "assigned_to_name": "", "updated_at": _now()}},
        )
    else:
        dev = find_user_by_id(dev_id_raw)
        if not dev:
            return jsonify({"error": "Developer not found"}), 404
        db.pages.update_one(
            {"_id": pgid},
            {
                "$set": {
                    "assigned_to": dev_id_raw,
                    "assigned_to_name": dev.get("name"),
                    "updated_at": _now(),
                }
            },
        )

    updated = db.pages.find_one({"_id": pgid})
    return jsonify(str_id(updated))


@bp.post("/pages/<page_id>/comments")
@any_authenticated
def add_comment(page_id):
    db = get_db()
    pgid = oid(page_id)
    if not pgid:
        return jsonify({"error": "Invalid page id"}), 400
    page = db.pages.find_one({"_id": pgid})
    if not page:
        return jsonify({"error": "Page not found"}), 404

    body = request.get_json(silent=True) or {}
    text = (body.get("text") or "").strip()
    image = body.get("image")
    parent_id = body.get("parent_id") or None

    if not text and not image:
        return jsonify({"error": "Comment must include text or an image"}), 400

    if parent_id and not any(c["id"] == parent_id for c in page.get("comments", [])):
        return jsonify({"error": "Parent comment not found"}), 400

    try:
        image = _check_image(image, "Comment image")
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    author_id = get_jwt_identity()
    author = find_user_by_id(author_id)
    claims = get_jwt()

    comment = {
        "id": str(uuid.uuid4())[:8],
        "parent_id": parent_id,
        "author_id": author_id,
        "author_name": author.get("name") if author else "Unknown",
        "author_role": claims.get("role"),
        "text": text,
        "image": image or "",
        "created_at": _now(),
    }
    db.pages.update_one({"_id": pgid}, {"$push": {"comments": comment}, "$set": {"updated_at": _now()}})
    updated = db.pages.find_one({"_id": pgid})
    return jsonify(str_id(updated)), 201


@bp.delete("/pages/<page_id>/comments/<comment_id>")
@any_authenticated
def delete_comment(page_id, comment_id):
    db = get_db()
    pgid = oid(page_id)
    if not pgid:
        return jsonify({"error": "Invalid page id"}), 400
    page = db.pages.find_one({"_id": pgid})
    if not page:
        return jsonify({"error": "Page not found"}), 404

    claims = get_jwt()
    user_id = get_jwt_identity()
    comment = next((c for c in page.get("comments", []) if c["id"] == comment_id), None)
    if not comment:
        return jsonify({"error": "Comment not found"}), 404
    if claims.get("role") != "admin" and comment.get("author_id") != user_id:
        return jsonify({"error": "You can only delete your own comments"}), 403

    db.pages.update_one({"_id": pgid}, {"$pull": {"comments": {"id": comment_id}}})
    updated = db.pages.find_one({"_id": pgid})
    return jsonify(str_id(updated))