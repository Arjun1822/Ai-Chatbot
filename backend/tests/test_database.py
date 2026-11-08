import pytest
from database import DatabaseManager, mask_mongodb_uri


def test_mask_mongodb_uri_atlas():
    raw_uri = "mongodb+srv://admin_user:SuperSecretPass123!@cluster0.abcde.mongodb.net/orbit_ai?retryWrites=true&w=majority"
    masked = mask_mongodb_uri(raw_uri)
    assert "SuperSecretPass123!" not in masked
    assert "admin_user:******@cluster0.abcde.mongodb.net" in masked
    assert "orbit_ai" in masked


def test_mask_mongodb_uri_standard():
    raw_uri = "mongodb://myuser:mypassword@localhost:27017/orbit_ai"
    masked = mask_mongodb_uri(raw_uri)
    assert "mypassword" not in masked
    assert "******" in masked


def test_mask_mongodb_uri_empty():
    assert mask_mongodb_uri(None) == "<unconfigured>"
    assert mask_mongodb_uri("") == "<unconfigured>"


def test_detect_atlas():
    assert DatabaseManager._detect_atlas("mongodb+srv://user:pass@cluster0.mongodb.net/orbit_ai") is True
    assert DatabaseManager._detect_atlas("mongodb://user:pass@cluster0.mongodb.net:27017/orbit_ai") is True
    assert DatabaseManager._detect_atlas("mongodb://localhost:27017/orbit_ai") is False
    assert DatabaseManager._detect_atlas("") is False


def test_database_manager_unconfigured():
    mgr = DatabaseManager(uri="")
    ping_res = mgr.ping()
    assert ping_res["status"] == "unconfigured"
    assert ping_res["connected"] is False
    assert mgr.client is None
    assert mgr.is_connected is False


def test_database_manager_invalid_host():
    # Use invalid host to test graceful failure without unhandled crash
    mgr = DatabaseManager(uri="mongodb://invalid-host-orbit-test:27017/orbit_ai")
    ping_res = mgr.ping()
    assert ping_res["status"] in ("failed", "disconnected")
    assert ping_res["connected"] is False
    assert mgr.is_connected is False
    assert "invalid-host-orbit-test" in mgr.masked_uri
