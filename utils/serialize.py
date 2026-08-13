from bson import ObjectId


def oid(value):
    """Safely cast a string to ObjectId, returns None if invalid."""
    try:
        return ObjectId(value)
    except Exception:
        return None


def str_id(doc: dict) -> dict:
    """Return a shallow copy of doc with _id -> id (string) for JSON responses."""
    if not doc:
        return doc
    out = dict(doc)
    out["id"] = str(out.pop("_id"))
    for key in ("project_id", "folder_id", "parent_id"):
        if key in out and out[key] is not None:
            out[key] = str(out[key])
    return out
