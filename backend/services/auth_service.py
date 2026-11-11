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

    def __init__(self, secret_key: Optional[str] = None, user_store: Optional[Any] = None):
        self.secret_key = (
            secret_key
            or os.getenv("SECRET_KEY")
            or os.getenv("JWT_SECRET")
            or "orbit-ai-default-dev-secret-key-change-in-prod"
        ).encode("utf-8")
        self.user_store = user_store

    def set_user_store(self, user_store: Any) -> None:
        """Attach an authoritative user store for live role and account state checks."""
        self.user_store = user_store

    def generate_token(self, user: Dict[str, Any], expiry_seconds: Optional[int] = None) -> str:
        """Create a signed URL-safe token containing user payload and expiration timestamp."""
        now_ts = int(time.time())
        exp_ts = now_ts + (expiry_seconds or self.DEFAULT_EXPIRY_SECONDS)

        header = {"alg": "HS256", "typ": "JWT"}
        payload = {
            "sub": user.get("id") or user.get("_id"),
            "email": user.get("email"),
            "name": user.get("name"),
            "role": user.get("role", "user"),
            "is_guest": bool(user.get("is_guest", False)),
            "iat": now_ts,
            "exp": exp_ts,
        }

        header_b64 = self._b64url_encode(json.dumps(header).encode("utf-8"))
        payload_b64 = self._b64url_encode(json.dumps(payload).encode("utf-8"))

        signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
        signature = hmac.new(self.secret_key, signing_input, hashlib.sha256).digest()
        sig_b64 = self._b64url_encode(signature)

        return f"{header_b64}.{payload_b64}.{sig_b64}"

    def generate_guest_token(self, guest_id: Optional[str] = None, expiry_seconds: Optional[int] = None) -> str:
        """Create a cryptographically signed guest session token with isolated unique guest UUID."""
        import uuid
        gid = guest_id or f"guest_{uuid.uuid4().hex[:12]}"
        now_ts = int(time.time())
        exp_ts = now_ts + (expiry_seconds or (30 * 24 * 3600))  # 30 days session

        header = {"alg": "HS256", "typ": "JWT"}
        payload = {
            "sub": gid,
            "is_guest": True,
            "name": "Guest User",
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
                "role": payload.get("role", "user"),
                "is_guest": bool(payload.get("is_guest", False)),
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
    """Extract authenticated user or signed guest from request headers or session."""
    from flask import session
    import uuid

    auth_header = request.headers.get("Authorization", "")
    token = None
    if auth_header:
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()
        else:
            return None  # Malformed Authorization header format
    elif "X-Auth-Token" in request.headers:
        token = request.headers["X-Auth-Token"].strip()
    elif "X-Guest-Token" in request.headers:
        token = request.headers["X-Guest-Token"].strip()

    if token:
        user = auth_service.verify_token(token)
        if user:
            return user
        return None  # Invalid or expired token passed explicitly

    # Cryptographically signed cookie session fallback
    try:
        session_guest_id = session.get("guest_id")
    except RuntimeError:
        session_guest_id = None

    if session_guest_id and isinstance(session_guest_id, str) and session_guest_id.startswith("guest_"):
        return {
            "id": session_guest_id,
            "name": "Guest User",
            "is_guest": True,
        }

    # Generate an isolated, non-shared guest identity with random UUID
    new_guest_id = f"guest_{uuid.uuid4().hex[:12]}"
    try:
        session["guest_id"] = new_guest_id
    except RuntimeError:
        pass

    guest_token = auth_service.generate_guest_token(guest_id=new_guest_id)
    g.new_guest_token = guest_token

    return {
        "id": new_guest_id,
        "name": "Guest User",
        "is_guest": True,
        "guest_token": guest_token,
    }


def require_auth(strict: bool = False):
    """Decorator ensuring request has user context. In non-strict mode, allows signed guest user."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            auth_header = request.headers.get("Authorization", "")
            if auth_header and not auth_header.startswith("Bearer "):
                return jsonify({"error": "Invalid Authorization header format. Must be Bearer <token>"}), 401

            user = get_current_user_from_request()
            if user is None:
                return jsonify({"error": "Invalid or expired token."}), 401

            if strict and (not user or user.get("is_guest")):
                return jsonify({"error": "Authentication required. Please log in."}), 401

            g.current_user = user
            request.user_id = user["id"]
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def require_admin(user_store: Optional[Any] = None):
    """Decorator ensuring request has authenticated administrator context with live role verification.

    Fails closed: If user_store is unconfigured, unavailable, or encounters an exception,
    access is strictly denied. Admin privileges NEVER rely solely on stateless JWT claims.
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            auth_header = request.headers.get("Authorization", "")
            if not auth_header:
                return jsonify({"error": "Authentication required. Admin access only."}), 401
            if not auth_header.startswith("Bearer "):
                return jsonify({"error": "Invalid Authorization header format. Must be Bearer <token>"}), 401

            user = get_current_user_from_request()
            if not user or user.get("is_guest"):
                return jsonify({"error": "Authentication required. Admin access only."}), 401

            if user.get("role") != "admin":
                return jsonify({"error": "Forbidden: Administrator privileges required."}), 403

            # Authoritative live role verification against user store to prevent
            # stale JWT abuse if administrator privileges have been revoked.
            # MUST fail closed: Never trust only JWT role claim if store is unavailable.
            store = user_store or getattr(auth_service, "user_store", None)
            if not store:
                logger.error("Admin access denied (fail-closed): Authoritative user store is missing or unavailable.")
                return jsonify({"error": "Forbidden: Administrator verification unavailable."}), 403

            try:
                live_user = store.get_by_id(user["id"])
            except Exception as e:
                logger.error(f"Admin access denied (fail-closed): User store lookup raised exception: {e}")
                return jsonify({"error": "Forbidden: Administrator verification error."}), 403

            if not live_user or live_user.get("role") != "admin":
                return jsonify({"error": "Forbidden: Administrator privileges required or revoked."}), 403

            g.current_user = user
            request.user_id = user["id"]
            return fn(*args, **kwargs)
        return wrapper
    return decorator

