import atexit
import logging
import re
import time
from typing import Any, Dict, Optional
from urllib.parse import urlsplit, urlunsplit

logger = logging.getLogger(__name__)


def mask_mongodb_uri(uri: Optional[str]) -> str:
    """Safely mask username and password credentials in a MongoDB URI."""
    if not uri:
        return "<unconfigured>"
    try:
        parts = urlsplit(uri)
        if parts.password:
            # Mask the password
            netloc = parts.netloc.replace(f":{parts.password}@", ":******@")
            return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
        elif "@" in parts.netloc:
            # User with no password or masked password
            netloc_parts = parts.netloc.split("@")
            return urlunsplit((parts.scheme, f"******@{netloc_parts[1]}", parts.path, parts.query, parts.fragment))
        return uri
    except Exception:
        # Fallback regex masking
        return re.sub(r":([^@]+)@", ":******@", uri)


class DatabaseManager:
    """Centralized MongoDB client manager for local and MongoDB Atlas cloud connections.

    Provides connection pooling, ping diagnostics, credential masking,
    graceful degradation, and clean resource teardown.
    """

    _instance: Optional["DatabaseManager"] = None

    def __init__(self, uri: Optional[str] = None, db_name: Optional[str] = None):
        import os
        if uri is not None:
            self.raw_uri = uri.strip()
        else:
            self.raw_uri = (os.getenv("MONGODB_URI") or "").strip()

        if db_name is not None:
            self.db_name = db_name.strip()
        else:
            self.db_name = (os.getenv("DATABASE_NAME") or "orbit_ai").strip()

        self.masked_uri = mask_mongodb_uri(self.raw_uri)
        self.is_atlas = self._detect_atlas(self.raw_uri)

        self._client = None
        self._db = None
        self._connected = False
        self._last_error = None

        if self.raw_uri:
            self._initialize_client()

        # Register clean process exit handler
        atexit.register(self.close)

    @classmethod
    def get_instance(cls, uri: Optional[str] = None, db_name: Optional[str] = None) -> "DatabaseManager":
        """Get or create singleton DatabaseManager instance."""
        import os
        if uri is not None:
            effective_uri = uri.strip()
        else:
            effective_uri = (os.getenv("MONGODB_URI") or "").strip()

        if db_name is not None:
            effective_db = db_name.strip()
        else:
            effective_db = (os.getenv("DATABASE_NAME") or "orbit_ai").strip()

        if cls._instance is None or (effective_uri and effective_uri != cls._instance.raw_uri):
            cls._instance = cls(uri=effective_uri, db_name=effective_db)
        return cls._instance

    @staticmethod
    def _detect_atlas(uri: str) -> bool:
        if not uri:
            return False
        return uri.startswith("mongodb+srv://") or ".mongodb.net" in uri.lower()

    def _initialize_client(self) -> None:
        """Create MongoClient with production-grade Atlas timeouts and pool settings."""
        try:
            from pymongo import MongoClient

            client_kwargs: Dict[str, Any] = {
                "serverSelectionTimeoutMS": 5000,
                "connectTimeoutMS": 5000,
                "socketTimeoutMS": 30000,
                "maxPoolSize": 50,
                "minPoolSize": 2,
            }

            if self.is_atlas:
                client_kwargs.update({
                    "retryWrites": True,
                    "w": "majority",
                })

            self._client = MongoClient(self.raw_uri, **client_kwargs)
            self._db = self._client[self.db_name]
            # Verify immediate ping on application database (least privilege)
            start_t = time.monotonic()
            self._db.command("ping")
            elapsed_ms = int((time.monotonic() - start_t) * 1000)

            self._connected = True
            self._last_error = None

            cluster_type = "MongoDB Atlas Cluster" if self.is_atlas else "Local/Standalone MongoDB"
            logger.info(
                f"[Database] Successfully connected to {cluster_type} "
                f"(database: {self.db_name}, target: {self.masked_uri}, latency: {elapsed_ms}ms)"
            )
        except Exception as e:
            self._connected = False
            self._last_error = str(e)
            logger.warning(
                f"[Database] Connection to {self.masked_uri} failed: {e}. "
                f"Application will operate in fallback mode if permissible."
            )

    @property
    def client(self):
        return self._client if self._connected else None

    @property
    def database(self):
        return self._db if self._connected else None

    @property
    def is_connected(self) -> bool:
        return self._connected and self._client is not None

    def ping(self) -> Dict[str, Any]:
        """Perform a live ping check against the MongoDB database."""
        if not self.raw_uri:
            return {
                "status": "unconfigured",
                "connected": False,
                "is_atlas": False,
                "database": self.db_name,
                "masked_uri": "<none>",
                "error": "MONGODB_URI is not set in environment.",
            }

        if not self._client:
            return {
                "status": "disconnected",
                "connected": False,
                "is_atlas": self.is_atlas,
                "database": self.db_name,
                "masked_uri": self.masked_uri,
                "error": self._last_error or "MongoClient not initialized.",
            }

        try:
            start_t = time.monotonic()
            target_db = self._db if self._db is not None else self._client[self.db_name]
            target_db.command("ping")
            elapsed_ms = int((time.monotonic() - start_t) * 1000)
            self._connected = True
            return {
                "status": "connected",
                "connected": True,
                "is_atlas": self.is_atlas,
                "database": self.db_name,
                "masked_uri": self.masked_uri,
                "latency_ms": elapsed_ms,
                "error": None,
            }
        except Exception as e:
            self._connected = False
            self._last_error = str(e)
            return {
                "status": "failed",
                "connected": False,
                "is_atlas": self.is_atlas,
                "database": self.db_name,
                "masked_uri": self.masked_uri,
                "error": str(e),
            }

    def close(self) -> None:
        """Close MongoClient connection cleanly."""
        if self._client:
            try:
                self._client.close()
                logger.info("[Database] MongoClient connection closed cleanly.")
            except Exception as e:
                logger.debug(f"[Database] Error closing MongoClient: {e}")
            finally:
                self._client = None
                self._db = None
                self._connected = False
