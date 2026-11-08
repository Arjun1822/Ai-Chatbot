"""
Production Verification Script: CORS and Startup Failure Safety
Tests CORS preflight headers and production startup rejection of insecure settings.
"""

import sys
import os
from pathlib import Path

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

import unittest
from unittest.mock import MagicMock, patch
from config import Config
from app import create_app
from database import DatabaseManager


def run_tests():
    print("=" * 70)
    print("ORBIT AI - CORS & PRODUCTION STARTUP SAFETY VERIFICATION")
    print("=" * 70)

    # ---------------------------------------------------------
    # TEST SUITE 1: CORS PREFLIGHT & HEADERS VERIFICATION
    # ---------------------------------------------------------
    print("\n[1/2] Verifying CORS Configuration...")

    class ProductionCORSConfig(Config):
        FLASK_ENV = "production"
        SECRET_KEY = "a" * 32
        FRONTEND_URL = "https://orbit-ai.vercel.app"
        MONGODB_URI = "mongodb://localhost:27017/orbit_ai"
        ALLOW_EPHEMERAL_STORAGE = True

    # Mock DatabaseManager connection to avoid network dependency in unit CORS test
    with patch.object(DatabaseManager, "is_connected", True), \
         patch.object(DatabaseManager, "client", MagicMock()):
        app = create_app(ProductionCORSConfig)
        client = app.test_client()

        # Test preflight OPTIONS request from exact production Vercel origin
        headers = {
            "Origin": "https://orbit-ai.vercel.app",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization, Content-Type",
        }
        res = client.options("/api/chat", headers=headers)
        allow_origin = res.headers.get("Access-Control-Allow-Origin")
        allow_headers = res.headers.get("Access-Control-Allow-Headers", "")
        allow_methods = res.headers.get("Access-Control-Allow-Methods", "")

        print(f"  -> OPTIONS /api/chat from 'https://orbit-ai.vercel.app'")
        print(f"     Status: {res.status_code}")
        print(f"     Access-Control-Allow-Origin: {allow_origin}")
        print(f"     Access-Control-Allow-Headers: {allow_headers}")
        print(f"     Access-Control-Allow-Methods: {allow_methods}")

        assert res.status_code == 200, f"Expected status 200, got {res.status_code}"
        assert allow_origin == "https://orbit-ai.vercel.app", f"Incorrect Allow-Origin: {allow_origin}"
        assert "authorization" in allow_headers.lower(), f"Authorization not allowed: {allow_headers}"
        assert "content-type" in allow_headers.lower(), f"Content-Type not allowed: {allow_headers}"
        assert "POST" in allow_methods, f"POST not in methods: {allow_methods}"
        print("  [PASS] Exact production Vercel origin and Authorization headers accepted!")

        # Test preflight OPTIONS request from unauthorized origin
        bad_headers = {
            "Origin": "https://malicious-attacker.com",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization, Content-Type",
        }
        res_bad = client.options("/api/chat", headers=bad_headers)
        bad_origin = res_bad.headers.get("Access-Control-Allow-Origin")
        print(f"  -> OPTIONS /api/chat from unauthorized 'https://malicious-attacker.com'")
        print(f"     Access-Control-Allow-Origin: {bad_origin}")
        assert bad_origin is None or bad_origin != "https://malicious-attacker.com", \
            f"Unauthorized origin was erroneously accepted: {bad_origin}"
        print("  [PASS] Unauthorized origin rejected cleanly!")

    # ---------------------------------------------------------
    # TEST SUITE 2: PRODUCTION STARTUP FAILURE SAFETY
    # ---------------------------------------------------------
    print("\n[2/2] Verifying Production Startup Failure Safety...")

    # Case A: Missing SECRET_KEY
    class MissingSecretConfig(Config):
        FLASK_ENV = "production"
        SECRET_KEY = ""
        MONGODB_URI = "mongodb+srv://user:pass@cluster.mongodb.net/orbit_ai"

    try:
        create_app(MissingSecretConfig)
        assert False, "Failed: Startup succeeded despite empty SECRET_KEY!"
    except RuntimeError as e:
        print(f"  [PASS] Missing SECRET_KEY rejected: {e}")

    # Case B: Default 'dev-only-change-me' SECRET_KEY
    class DefaultSecretConfig(Config):
        FLASK_ENV = "production"
        SECRET_KEY = "dev-only-change-me"
        MONGODB_URI = "mongodb+srv://user:pass@cluster.mongodb.net/orbit_ai"

    try:
        create_app(DefaultSecretConfig)
        assert False, "Failed: Startup succeeded with default SECRET_KEY!"
    except RuntimeError as e:
        print(f"  [PASS] Default SECRET_KEY rejected: {e}")

    # Case C: Short (< 32 chars) SECRET_KEY
    class ShortSecretConfig(Config):
        FLASK_ENV = "production"
        SECRET_KEY = "too-short-key"
        MONGODB_URI = "mongodb+srv://user:pass@cluster.mongodb.net/orbit_ai"

    try:
        create_app(ShortSecretConfig)
        assert False, "Failed: Startup succeeded with short SECRET_KEY!"
    except RuntimeError as e:
        print(f"  [PASS] Short SECRET_KEY rejected: {e}")

    # Case D: Missing MONGODB_URI in production
    class MissingMongoConfig(Config):
        FLASK_ENV = "production"
        SECRET_KEY = "a" * 32
        MONGODB_URI = ""

    try:
        create_app(MissingMongoConfig)
        assert False, "Failed: Startup succeeded with empty MONGODB_URI!"
    except RuntimeError as e:
        print(f"  [PASS] Missing MONGODB_URI rejected: {e}")

    # Case E: Unreachable MongoDB Atlas cluster in production
    class UnreachableAtlasConfig(Config):
        FLASK_ENV = "production"
        SECRET_KEY = "a" * 32
        MONGODB_URI = "mongodb+srv://orbit_app:pass@unreachable-cluster-fail.mongodb.net/orbit_ai"

    try:
        create_app(UnreachableAtlasConfig)
        assert False, "Failed: Startup succeeded with unreachable MongoDB Atlas!"
    except RuntimeError as e:
        print(f"  [PASS] Unreachable Atlas cluster rejected: {e}")

    print("\n" + "=" * 70)
    print("ALL PRODUCTION CORS & STARTUP SAFETY CHECKS PASSED SUCCESSFULLY!")
    print("=" * 70)


if __name__ == "__main__":
    run_tests()
