import logging
import os
from pathlib import Path
from typing import Any, Dict
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Search root .env first, then backend/.env
_root_env = Path(__file__).resolve().parent.parent / ".env"
_backend_env = Path(__file__).resolve().parent / ".env"

if _root_env.exists():
    load_dotenv(_root_env)
if _backend_env.exists():
    load_dotenv(_backend_env)
load_dotenv()  # Fallback to standard process directory


class Config:
    FLASK_ENV = os.getenv("FLASK_ENV", "development")
    SECRET_KEY = os.getenv("SECRET_KEY") or os.getenv("FLASK_SECRET_KEY", "dev-only-change-me")
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
    MONGODB_URI = os.getenv("MONGODB_URI", "")
    DATABASE_NAME = os.getenv("DATABASE_NAME", "orbit_ai")

    # Frontend CORS origins
    # In development: allows localhost:3000, localhost:5173, etc.
    # In production: uses exact configured Vercel production origin(s), with optional project-scoped wildcard support
    _is_prod = FLASK_ENV == "production"
    _default_dev_origins = "http://localhost:3000,http://localhost:5173,http://127.0.0.1:3000,http://127.0.0.1:5173"
    _frontend_env = os.getenv(
        "FRONTEND_URL",
        "http://localhost:3000" if _is_prod else _default_dev_origins,
    )
    _raw_origins = [origin.strip() for origin in _frontend_env.split(",") if origin.strip()]

    # Preserve local development origins in non-production environments
    if not _is_prod:
        for _local_dev in ["http://localhost:3000", "http://localhost:5173", "http://127.0.0.1:3000", "http://127.0.0.1:5173"]:
            if _local_dev not in _raw_origins:
                _raw_origins.append(_local_dev)

    @classmethod
    def get_allowed_origins(cls):
        """Parse and compile allowed CORS origins dynamically based on current configuration."""
        raw_val = getattr(cls, "FRONTEND_URL", None) or os.getenv("FRONTEND_URL", "http://localhost:3000")
        if isinstance(raw_val, str):
            raw_list = [origin.strip() for origin in raw_val.split(",") if origin.strip()]
        elif isinstance(raw_val, (list, tuple)):
            raw_list = [str(origin).strip() for origin in raw_val if str(origin).strip()]
        else:
            raw_list = ["http://localhost:3000"]

        is_prod = getattr(cls, "FLASK_ENV", "development") == "production"
        if not is_prod:
            for local_dev in ["http://localhost:3000", "http://localhost:5173", "http://127.0.0.1:3000", "http://127.0.0.1:5173"]:
                if local_dev not in raw_list:
                    raw_list.append(local_dev)

        compiled_origins = []
        for origin in raw_list:
            if "*" in origin:
                import re
                escaped = re.escape(origin).replace(r"\*", r"[-a-zA-Z0-9_.]*")
                compiled_origins.append(re.compile(f"^{escaped}$"))
            else:
                compiled_origins.append(origin)
        return compiled_origins

    FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")

    MAX_CONTEXT_MESSAGES = int(os.getenv("MAX_CONTEXT_MESSAGES", "16"))
    MAX_MESSAGE_LENGTH = int(os.getenv("MAX_MESSAGE_LENGTH", "8000"))
    MAX_ATTACHMENT_SIZE_BYTES = int(os.getenv("MAX_ATTACHMENT_SIZE_BYTES", "102400"))  # 100 KB text

    RATE_LIMIT_REQUESTS = int(os.getenv("RATE_LIMIT_REQUESTS", "60"))
    RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))

    SYSTEM_PROMPT = os.getenv(
        "SYSTEM_PROMPT",
        "You are Orbit, an intelligent, helpful, and concise AI assistant. "
        "Provide direct, high-quality answers formatted in clean Markdown. "
        "Use GitHub Flavored Markdown (tables, task lists, code fences with language tags) when relevant. "
        "Maintain clarity, acknowledge assumptions when requirements are ambiguous, and be objective and polite.",
    )

    @classmethod
    def is_production_mode(cls) -> bool:
        """Robust, fail-closed detection of production environments with strict precedence.

        Render indicators, production environment variables, and Atlas database
        configuration take absolute precedence over development defaults. A production
        deployment NEVER becomes development merely because FLASK_ENV is set incorrectly.
        """
        # 1. Render cloud hosting indicators (highest precedence)
        if bool(os.getenv("RENDER") or os.getenv("RENDER_SERVICE_ID")):
            return True

        # 2. Production environment variables
        flask_val = getattr(cls, "FLASK_ENV", None)
        flask_env = str(flask_val if flask_val is not None else os.getenv("FLASK_ENV", "")).strip().lower()
        env = str(os.getenv("ENV", "") or os.getenv("ENVIRONMENT", "") or os.getenv("NODE_ENV", "")).strip().lower()
        if flask_env == "production" or env == "production":
            return True

        # 3. Atlas database configuration (takes absolute precedence over development settings)
        uri_val = getattr(cls, "MONGODB_URI", None)
        mongo_uri = str(uri_val if uri_val is not None else os.getenv("MONGODB_URI", "")).lower()
        if "mongodb+srv://" in mongo_uri or ".mongodb.net" in mongo_uri:
            return True

        return False

    @classmethod
    def validate_configuration(cls) -> Dict[str, Any]:
        """Validate startup configuration and return safety diagnostics."""
        diagnostics = {
            "flask_env": cls.FLASK_ENV,
            "database_name": cls.DATABASE_NAME,
            "gemini_configured": bool(cls.GEMINI_API_KEY),
            "mongodb_configured": bool(cls.MONGODB_URI),
            "is_atlas": cls.MONGODB_URI.startswith("mongodb+srv://") or ".mongodb.net" in cls.MONGODB_URI.lower(),
            "warnings": [],
        }

        if cls.FLASK_ENV == "production":
            if not cls.SECRET_KEY or cls.SECRET_KEY == "dev-only-change-me" or len(cls.SECRET_KEY) < 32:
                diagnostics["warnings"].append(
                    "Insecure or short SECRET_KEY in production. Set a random 32+ character key."
                )
            if not cls.GEMINI_API_KEY:
                diagnostics["warnings"].append(
                    "GEMINI_API_KEY is not configured in production environment."
                )
            if not cls.MONGODB_URI:
                diagnostics["warnings"].append(
                    "MONGODB_URI is not set in production. Application will use local in-memory fallback."
                )
            if "localhost" in str(cls.FRONTEND_URL).lower():
                diagnostics["warnings"].append(
                    "FRONTEND_URL is pointing to localhost in production. Configure your exact Vercel production domain."
                )

        for w in diagnostics["warnings"]:
            logger.warning(f"[Config] {w}")

        return diagnostics


# Initialize default parsed origins on module import
Config.FRONTEND_URLS = Config.get_allowed_origins()
