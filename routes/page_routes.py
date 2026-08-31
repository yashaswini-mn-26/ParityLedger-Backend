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
MAX_IMAGES_PER_FIELD = 6


def _now():
    return datetime.now(timezone.utc).isoformat()


def _check_image(data_url, field_name: str):
    if not data_url:
        return None
    if not data_url.startswith("data:image/"):
        raise ValueError(f"{field_name} must be a base64 image data URL")
    b64 = data_url.split(",", 1)[-1]
    approx_bytes = len(b64) * 3 / 4
    if approx_bytes > MAX_IMAGE_BYTES:
        raise ValueError(f"{field_name} exceeds the 4MB size limit")
    return data_url


def _check_images(data_urls, field_name: str):
    """Validates a list of base64 image data URLs. Returns the sanitized list."""
    if not data_urls:
        return []
    if not isinstance(data_urls, list):
        raise ValueError(f"{field_name} must be a list of images")
    if len(data_urls) > MAX_IMAGES_PER_FIELD:
        raise ValueError(f"{field_name} allows a maximum of {MAX_IMAGES_PER_FIELD} images")
    return [_check_image(u, field_name) for u in data_urls if u]


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
    vb_images = _check_images(comparison.get("vbImages"), "VB screenshots")
    mig_images = _check_images(comparison.get("migImages"), "Migrated screenshots")

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
            "vbImages": vb_images if vb_images else (existing or {}).get("comparison", {}).get("vbImages", []),
            "migImages": mig_images if mig_images else (existing or {}).get("comparison", {}).get("migImages", []),
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


# ---------------------------------------------------------------------------
# Dashboard listing — aggregation-only, NEVER pulls comparison/comment images,
# raw SQL text, or full review/approval history over the wire.
# ---------------------------------------------------------------------------
_LIST_PIPELINE_TAIL = [
    {
        "$project": {
            "project_id": 1,
            "folder_id": 1,
            "name": 1,
            "path": 1,
            "status": 1,
            "verdict": 1,
            "reviewed_by": 1,
            "reviewed_by_name": 1,
            "reviewed_date": 1,
            "approved_by": 1,
            "approved_by_name": 1,
            "approved_date": 1,
            "assigned_to": 1,
            "assigned_to_name": 1,
            "created_at": 1,
            "updated_at": 1,
            "api_count": {"$size": {"$ifNull": ["$apis", []]}},
            "query_count": {
                "$sum": {
                    "$map": {
                        "input": {"$ifNull": ["$apis", []]},
                        "as": "a",
                        "in": {"$size": {"$ifNull": ["$$a.queries", []]}},
                    }
                }
            },
            "_tables": {
                "$reduce": {
                    "input": {"$ifNull": ["$apis", []]},
                    "initialValue": [],
                    "in": {
                        "$setUnion": [
                            "$$value",
                            {
                                "$reduce": {
                                    "input": {"$ifNull": ["$$this.queries", []]},
                                    "initialValue": [],
                                    "in": {"$setUnion": ["$$value", {"$ifNull": ["$$this.tables", []]}]},
                                }
                            },
                        ]
                    },
                }
            },
        }
    },
    {"$addFields": {"table_count": {"$size": "$_tables"}}},
    {"$project": {"_tables": 0}},
    {"$sort": {"name": 1}},
]


def _serialize_summary(p: dict) -> dict:
    p["id"] = str(p.pop("_id"))
    if p.get("project_id") is not None:
        p["project_id"] = str(p["project_id"])
    if p.get("folder_id") is not None:
        p["folder_id"] = str(p["folder_id"])
    return p


@bp.get("/projects/<project_id>/pages")
@any_authenticated
def list_pages(project_id):
    db = get_db()
    pid = oid(project_id)
    if not pid:
        return jsonify({"error": "Invalid project id"}), 400
    pipeline = [{"$match": {"project_id": pid}}] + _LIST_PIPELINE_TAIL
    pages = list(db.pages.aggregate(pipeline))
    return jsonify([_serialize_summary(p) for p in pages])


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


# ---------------------------------------------------------------------------
# Single page — comparison/comment images are stripped out (replaced with
# counts) so the page loads instantly. Actual image bytes are fetched lazily
# via /pages/<id>/comparison-images and /pages/<id>/comments/<id>/images,
# only when the user actually opens the gallery.
# ---------------------------------------------------------------------------
_LIGHT_PAGE_PIPELINE_TAIL = [
    {
        "$addFields": {
            "comparison": {
                "vbNotes": {"$ifNull": ["$comparison.vbNotes", ""]},
                "migNotes": {"$ifNull": ["$comparison.migNotes", ""]},
                "vbImageCount": {"$size": {"$ifNull": ["$comparison.vbImages", []]}},
                "migImageCount": {"$size": {"$ifNull": ["$comparison.migImages", []]}},
            },
            "comments": {
                "$map": {
                    "input": {"$ifNull": ["$comments", []]},
                    "as": "c",
                    "in": {
                        "id": "$$c.id",
                        "parent_id": "$$c.parent_id",
                        "author_id": "$$c.author_id",
                        "author_name": "$$c.author_name",
                        "author_role": "$$c.author_role",
                        "text": "$$c.text",
                        "image_count": {"$size": {"$ifNull": ["$$c.images", []]}},
                        "created_at": "$$c.created_at",
                    },
                }
            },
        }
    },
]


def _fetch_light_page(db, pgid):
    pipeline = [{"$match": {"_id": pgid}}] + _LIGHT_PAGE_PIPELINE_TAIL
    result = list(db.pages.aggregate(pipeline))
    return result[0] if result else None


@bp.get("/pages/<page_id>")
@any_authenticated
def get_page(page_id):
    db = get_db()
    pgid = oid(page_id)
    if not pgid:
        return jsonify({"error": "Invalid page id"}), 400
    page = _fetch_light_page(db, pgid)
    if not page:
        return jsonify({"error": "Page not found"}), 404
    return jsonify(str_id(page))


@bp.get("/pages/<page_id>/comparison-images")
@any_authenticated
def get_comparison_images(page_id):
    db = get_db()
    pgid = oid(page_id)
    if not pgid:
        return jsonify({"error": "Invalid page id"}), 400
    page = db.pages.find_one({"_id": pgid}, {"comparison.vbImages": 1, "comparison.migImages": 1})
    if not page:
        return jsonify({"error": "Page not found"}), 404
    comp = page.get("comparison") or {}
    return jsonify({"vbImages": comp.get("vbImages") or [], "migImages": comp.get("migImages") or []})


@bp.get("/pages/<page_id>/comments/<comment_id>/images")
@any_authenticated
def get_comment_images(page_id, comment_id):
    db = get_db()
    pgid = oid(page_id)
    if not pgid:
        return jsonify({"error": "Invalid page id"}), 400
    page = db.pages.find_one({"_id": pgid, "comments.id": comment_id}, {"comments.$": 1})
    if not page or not page.get("comments"):
        return jsonify({"error": "Comment not found"}), 404
    return jsonify({"images": page["comments"][0].get("images") or []})


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
    updated = _fetch_light_page(db, pgid)
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
    page = db.pages.find_one({"_id": pgid}, {"reviews": 1})
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
            "approved_by": None,
            "approved_by_name": "",
            "approved_date": None,
            "approvals": [],
        })

    db.pages.update_one({"_id": pgid}, {"$push": {"reviews": review}, "$set": update})
    updated = _fetch_light_page(db, pgid)
    return jsonify(str_id(updated))


@bp.post("/pages/<page_id>/approve")
@roles_required("admin")
def approve_page(page_id):
    """Admin sign-off. Multiple admins can each approve independently — all are kept in history."""
    db = get_db()
    pgid = oid(page_id)
    if not pgid:
        return jsonify({"error": "Invalid page id"}), 400
    page = db.pages.find_one({"_id": pgid}, {"reviews": 1, "approvals": 1})
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
    updated = _fetch_light_page(db, pgid)
    return jsonify(str_id(updated))


@bp.post("/pages/<page_id>/assign")
@roles_required("admin")
def assign_page(page_id):
    """Assign the page to a developer for fixing."""
    db = get_db()
    pgid = oid(page_id)
    if not pgid:
        return jsonify({"error": "Invalid page id"}), 400
    page = db.pages.find_one({"_id": pgid}, {"_id": 1})
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

    updated = _fetch_light_page(db, pgid)
    return jsonify(str_id(updated))


@bp.post("/pages/<page_id>/comments")
@any_authenticated
def add_comment(page_id):
    db = get_db()
    pgid = oid(page_id)
    if not pgid:
        return jsonify({"error": "Invalid page id"}), 400
    page = db.pages.find_one({"_id": pgid}, {"comments.id": 1})
    if not page:
        return jsonify({"error": "Page not found"}), 404

    body = request.get_json(silent=True) or {}
    text = (body.get("text") or "").strip()
    images_in = body.get("images") or []
    parent_id = body.get("parent_id") or None

    if not text and not images_in:
        return jsonify({"error": "Comment must include text or at least one image"}), 400

    if parent_id and not any(c["id"] == parent_id for c in page.get("comments", [])):
        return jsonify({"error": "Parent comment not found"}), 400

    try:
        images = _check_images(images_in, "Comment images")
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
        "images": images,
        "created_at": _now(),
    }
    db.pages.update_one({"_id": pgid}, {"$push": {"comments": comment}, "$set": {"updated_at": _now()}})
    updated = _fetch_light_page(db, pgid)
    return jsonify(str_id(updated)), 201


@bp.delete("/pages/<page_id>/comments/<comment_id>")
@any_authenticated
def delete_comment(page_id, comment_id):
    db = get_db()
    pgid = oid(page_id)
    if not pgid:
        return jsonify({"error": "Invalid page id"}), 400
    page = db.pages.find_one({"_id": pgid}, {"comments": 1})
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
    updated = _fetch_light_page(db, pgid)
    return jsonify(str_id(updated))

def _page_summary(p: dict) -> dict:
    """Lightweight shape for search results — used by routes/search_routes.py."""
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