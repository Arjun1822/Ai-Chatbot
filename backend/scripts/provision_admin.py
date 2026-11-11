"""
ORBIT AI - Server-Side Admin Provisioning Utility
This trusted administrative utility is executed strictly from the server console/CLI.
No external HTTP endpoints expose administrative user creation or role elevation.

Usage:
  python backend/scripts/provision_admin.py --email admin@example.com --password "SecretPass123!" --name "System Admin"
  python backend/scripts/provision_admin.py --promote user@example.com
  python backend/scripts/provision_admin.py --demote former_admin@example.com
"""

import argparse
import getpass
import logging
import os
import sys
from pathlib import Path

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from config import Config
from database import DatabaseManager
from services.user_store import UserStore

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("provision_admin")


def get_configured_store():
    data_dir = os.path.join(backend_dir, "data")
    os.makedirs(data_dir, exist_ok=True)
    users_file = os.path.join(data_dir, "users.json")

    mongo_uri = os.getenv("MONGODB_URI", getattr(Config, "MONGODB_URI", ""))
    db_name = os.getenv("DATABASE_NAME", getattr(Config, "DATABASE_NAME", "orbit_ai"))
    db_client = None

    if mongo_uri:
        db_mgr = DatabaseManager.get_instance(uri=mongo_uri, db_name=db_name)
        if db_mgr.is_connected:
            db_client = db_mgr.client
            logger.info("Connected to MongoDB for user management.")
        else:
            logger.warning("MongoDB not connected. Operating on local file storage.")

    return UserStore(persistence_path=users_file, mongo_client=db_client, db_name=db_name)


def main():
    parser = argparse.ArgumentParser(description="ORBIT AI Server-Side Admin Provisioning")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--create", action="store_true", help="Create a new administrator account")
    group.add_argument("--promote", metavar="EMAIL", help="Promote an existing user to administrator")
    group.add_argument("--demote", metavar="EMAIL", help="Demote an administrator to standard user role")

    parser.add_argument("--email", help="Admin email address for --create")
    parser.add_argument("--name", default="System Administrator", help="Admin display name")

    args = parser.parse_args()
    store = get_configured_store()

    if args.create:
        if not args.email:
            logger.error("--email is required when creating an administrator.")
            sys.exit(1)

        try:
            pwd1 = getpass.getpass("Enter administrator password (min 8 characters): ")
            pwd2 = getpass.getpass("Confirm administrator password: ")
        except (KeyboardInterrupt, EOFError):
            print("\nAborted.")
            sys.exit(1)

        if pwd1 != pwd2:
            logger.error("Password confirmation does not match.")
            sys.exit(1)

        if not pwd1 or len(pwd1) < 8:
            logger.error("Password must be at least 8 characters long.")
            sys.exit(1)

        try:
            admin_user = store.create_user(
                email=args.email,
                password=pwd1,
                name=args.name,
                role="admin",
            )
            logger.info(f"Successfully provisioned administrator: {admin_user['email']} (ID: {admin_user['id']})")
        except ValueError as err:
            logger.error(f"Failed to create administrator: {err}")
            sys.exit(1)

    elif args.promote:
        user = store.get_by_email(args.promote)
        if not user:
            logger.error(f"User with email '{args.promote}' not found.")
            sys.exit(1)
        updated = store.set_user_role(user["id"], "admin")
        logger.info(f"Successfully promoted user '{args.promote}' to administrator role.")

    elif args.demote:
        user = store.get_by_email(args.demote)
        if not user:
            logger.error(f"User with email '{args.demote}' not found.")
            sys.exit(1)
        updated = store.set_user_role(user["id"], "user")
        logger.info(f"Successfully revoked administrator privileges from '{args.demote}'.")


if __name__ == "__main__":
    main()

