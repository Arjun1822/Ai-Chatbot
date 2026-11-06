from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
import re
import secrets
from threading import RLock
from typing import Any, Dict, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)


def hash_password(password: str, salt: bytes, iterations: int = 100_000) -> str:
    """Hash password using PBKDF2-HMAC-SHA256 with 100,000 iterations."""
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return key.hex()


def verify_password(password: str, salt_hex: str, password_hash: str) -> bool:
    """Verify password against salt and hash using constant time comparison."""
    salt = bytes.fromhex(salt_hex)
    computed_hash = hash_password(password, salt)
    return secrets.compare_digest(computed_hash, password_hash)


class UserStore:
    """User store supporting secure PBKDF2 password hashing, JSON persistence, and MongoDB."""

    def __init__(self, persistence_path: Optional[str] = None, mongo_client=None, db_name="orbit_db"):
        self._lock = RLock()
        self.persistence_path = persistence_path
        self.mongo_client = mongo_client
        self.db_name = db_name
        self._users: Dict[str, Dict[str, Any]] = {}  # user_id -> user_dict
        self._email_index: Dict[str, str] = {}  # lower_email -> user_id

        if persistence_path and os.path.exists(persistence_path):
            self._load()

        if self.mongo_client:
            try:
                col = self.mongo_client[self.db_name]["users"]
                col.create_index("email", unique=True)
            except Exception as e:
                logger.warning(f"Could not initialize MongoDB users index: {e}")

    def create_user(self, email: str, password: str, name: Optional[str] = None) -> Dict[str, Any]:
        clean_email = email.strip().lower()
        if not self._is_valid_email(clean_email):
            raise ValueError("Invalid email format.")

        if not password or len(password) < 8:
            raise ValueError("Password must be at least 8 characters long.")

        with self._lock:
            if clean_email in self._email_index:
                raise ValueError("User with this email already exists.")

            salt = secrets.token_bytes(32)
            pwd_hash = hash_password(password, salt)
            user_id = str(uuid4())
            now_iso = datetime.now(timezone.utc).isoformat()

            user_doc = {
                "_id": user_id,
                "id": user_id,
                "email": clean_email,
                "name": (name or clean_email.split("@")[0]).strip()[:50],
                "salt": salt.hex(),
                "password_hash": pwd_hash,
                "created_at": now_iso,
                "updated_at": now_iso,
            }

            self._users[user_id] = user_doc
            self._email_index[clean_email] = user_id
            self._save()

        if self.mongo_client:
            try:
                col = self.mongo_client[self.db_name]["users"]
                col.insert_one(user_doc)
            except Exception as e:
                logger.warning(f"MongoDB create_user failed: {e}")

        return self._sanitize(user_doc)

    def authenticate(self, email: str, password: str) -> Optional[Dict[str, Any]]:
        clean_email = email.strip().lower()
        user_doc = None

        if self.mongo_client:
            try:
                col = self.mongo_client[self.db_name]["users"]
                user_doc = col.find_one({"email": clean_email})
            except Exception:
                user_doc = None

        if not user_doc:
            with self._lock:
                uid = self._email_index.get(clean_email)
                if uid:
                    user_doc = self._users.get(uid)

        if not user_doc:
            return None

        if verify_password(password, user_doc["salt"], user_doc["password_hash"]):
            return self._sanitize(user_doc)
        return None

    def get_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        if self.mongo_client:
            try:
                col = self.mongo_client[self.db_name]["users"]
                user_doc = col.find_one({"_id": user_id})
                if user_doc:
                    return self._sanitize(user_doc)
            except Exception:
                pass

        with self._lock:
            user_doc = self._users.get(user_id)
            return self._sanitize(user_doc) if user_doc else None

    def get_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        clean_email = email.strip().lower()
        with self._lock:
            uid = self._email_index.get(clean_email)
            if uid:
                return self.get_by_id(uid)
        return None

    @staticmethod
    def _sanitize(user_doc: Dict[str, Any]) -> Dict[str, Any]:
        clean = deepcopy(user_doc)
        clean.pop("password_hash", None)
        clean.pop("salt", None)
        if "_id" in clean and "id" not in clean:
            clean["id"] = clean["_id"]
        return clean

    @staticmethod
    def _is_valid_email(email: str) -> bool:
        return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email))

    def _save(self) -> None:
        if not self.persistence_path:
            return
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.persistence_path)), exist_ok=True)
            with open(self.persistence_path, "w", encoding="utf-8") as f:
                json.dump(self._users, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to persist users: {e}")

    def _load(self) -> None:
        try:
            with open(self.persistence_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self._users = data
                self._email_index = {u["email"].lower(): uid for uid, u in data.items() if "email" in u}
        except Exception as e:
            logger.warning(f"Failed to load users: {e}")
