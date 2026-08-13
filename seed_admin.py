"""
One-time bootstrap script: creates the first admin account from environment
variables so you're never forced to hardcode credentials in source.

Usage:
    cd backend
    python seed_admin.py
"""
import os
from dotenv import load_dotenv

load_dotenv()

from extensions import init_db  # noqa: E402
from auth import create_user  # noqa: E402


def main():
    username = os.environ.get("SEED_ADMIN_USERNAME")
    password = os.environ.get("SEED_ADMIN_PASSWORD")
    name = os.environ.get("SEED_ADMIN_NAME", username)

    if not username or not password:
        raise SystemExit(
            "Set SEED_ADMIN_USERNAME and SEED_ADMIN_PASSWORD in your .env before running this script."
        )
    if len(password) < 6:
        raise SystemExit("SEED_ADMIN_PASSWORD must be at least 6 characters.")

    init_db()
    try:
        user = create_user(username, password, name, role="admin")
        print(f"Admin user created: {user['username']} (id={user['_id']})")
    except ValueError as e:
        print(f"Skipped: {e}")


if __name__ == "__main__":
    main()
