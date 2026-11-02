
from pymongo import MongoClient, ASCENDING
from pymongo.database import Database

from config import Config

_client: MongoClient | None = None
_db: Database | None = None


def init_db() -> Database:
    """Initialise the Mongo client/db once and ensure indexes exist."""
    global _client, _db

    if _db is not None:
        return _db

    _client = MongoClient(
        Config.MONGO_URI,
        uuidRepresentation="standard"
    )

    _db = _client[Config.MONGO_DB_NAME]

    # Users
    _db.users.create_index(
        [("username", ASCENDING)],
        unique=True
    )

    # Projects
    _db.projects.create_index(
        [("name", ASCENDING)]
    )

    # Supports demo workspace filtering and project-name lookups.
    _db.projects.create_index([
        ("demo_session_id", ASCENDING),
        ("is_demo_visible", ASCENDING),
        ("name", ASCENDING),
    ])

    # Folders
    _db.folders.create_index([
        ("project_id", ASCENDING),
        ("parent_id", ASCENDING)
    ])

    # Pages
    _db.pages.create_index([
        ("project_id", ASCENDING),
        ("folder_id", ASCENDING)
    ])

    # Text search
    _db.pages.create_index(
        [
            ("name", "text"),
            ("path", "text"),
            ("verdict", "text")
        ],
        name="page_search_index",
    )

    return _db


def get_db() -> Database:
    if _db is None:
        return init_db()

    return _db
