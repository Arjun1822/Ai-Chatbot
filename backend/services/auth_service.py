import base64
from functools import wraps
import hashlib
import hmac
import json
import logging
import os
import time
from typing import Any, Dict, Optional
from flask import g, jsonify, request

logger = logging.getLogger(__name__)


class AuthService:
    """Authentication service providing secure signed JWT-like tokens and middleware."""

    DEFAULT_EXPIRY_SECONDS = 7 * 24 * 3600  # 7 days

    def __init__(self, secret_key: Optional[str] = None):
        self.secret_key = (
            secret_key
            or os.getenv("SECRET_KEY")
            or os.getenv("JWT_SECRET")
            or "orbit-ai-default-dev-secret-key-change-in-prod"
        ).encode("utf-8")

    def generate_token(self, user: Dict[str, Any], expiry_seconds: Optional[int] = None) -> str:
        """Create a signed URL-safe token containing user payload and expiration timestamp."""
        now_ts = int(time.time())
        exp_ts = now_ts + (expiry_seconds or self.DEFAULT_EXPIRY_SECONDS)

        header = {"alg": "HS256", "typ": "JWT"}
        payload = {
            "sub": user.get("id") or user.get("_id"),
            "email": user.get("email"),
            "name": user.get("name"),
            "iat": now_ts,
            "exp": exp_ts,
        }

        header_b64 = self._b64url_encode(json.dumps(header).encode("utf-8"))
        payload_b64 = self._b64url_encode(json.dumps(payload).encode("utf-8"))

        signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
        signature = hmac.new(self.secret_key, signing_input, hashlib.sha256).digest()
        sig_b64 = self._b64url_encode(signature)

        return f"{header_b64}.{payload_b64}.{sig_b64}"

    def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Verify token signature and expiration, returning user payload or None."""
        if not token or not isinstance(token, str):
            return None

        parts = token.strip().split(".")
        if len(parts) != 3:
            return None

        header_b64, payload_b64, sig_b64 = parts

        try:
            signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
            expected_sig = hmac.new(self.secret_key, signing_input, hashlib.sha256).digest()
            actual_sig = self._b64url_decode(sig_b64)

            if not hmac.compare_digest(expected_sig, actual_sig):
                return None

            payload_bytes = self._b64url_decode(payload_b64)
            payload = json.loads(payload_bytes.decode("utf-8"))

            if payload.get("exp") and time.time() > payload["exp"]:
                return None  # Expired

            return {
                "id": payload.get("sub"),
                "email": payload.get("email"),
                "name": payload.get("name"),
            }
        except Exception as e:
            logger.debug(f"Token verification failed: {e}")
            return None

    @staticmethod
    def _b64url_encode(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    @staticmethod
    def _b64url_decode(data: str) -> bytes:
        padding = 4 - (len(data) % 4)
        if padding != 4:
            data += "=" * padding
        return base64.urlsafe_b64decode(data.encode("ascii"))


# Singleton auth service
auth_service = AuthService()


def get_current_user_from_request() -> Optional[Dict[str, Any]]:
    """Extract authenticated user from request header or fallback to local user."""
    auth_header = request.headers.get("Authorization", "")
    token = None
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
    elif "X-Auth-Token" in request.headers:
        token = request.headers["X-Auth-Token"].strip()

    if token:
        user = auth_service.verify_token(token)
        if user:
            return user
        return None  # Invalid token passed explicitly

    # Optional local fallback header for dev/tests
    if "X-User-Id" in request.headers:
        uid = request.headers["X-User-Id"].strip()
        return {"id": uid, "email": f"{uid}@orbit.ai", "name": uid, "is_guest": True}

    # Default guest user for backward compatibility
    return {"id": "local_user", "email": "local@orbit.ai", "name": "Local User", "is_guest": True}


def require_auth(strict: bool = False):
    """Decorator ensuring request has user context. In non-strict mode, falls back to guest user."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            auth_header = request.headers.get("Authorization", "")
            if auth_header and not auth_header.startswith("Bearer "):
                return jsonify({"error": "Invalid Authorization header format. Must be Bearer <token>"}), 401

            user = get_current_user_from_request()
            if strict and (not user or user.get("is_guest")):
                return jsonify({"error": "Authentication required. Please log in."}), 401

            if user is None:
                return jsonify({"error": "Invalid or expired token."}), 401

            g.current_user = user
            request.user_id = user["id"]
            return fn(*args, **kwargs)
        return wrapper
    return decorator

