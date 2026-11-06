import pytest
from app import create_app
from config import Config
from services.auth_service import AuthService
from services.user_store import UserStore, hash_password, verify_password


class TestAuthConfig(Config):
    TESTING = True
    MONGODB_URI = ""
    GEMINI_API_KEY = "test_key"


@pytest.fixture
def auth_client():
    test_user_store = UserStore()
    app = create_app(config_class=TestAuthConfig, user_st=test_user_store)
    client = app.test_client()
    return client, test_user_store


def test_password_hashing():
    salt = b"random_salt_bytes_1234567890123"
    pwd = "SecurePassword123!"
    h = hash_password(pwd, salt)
    assert len(h) == 64  # sha256 hex string
    assert verify_password(pwd, salt.hex(), h) is True
    assert verify_password("WrongPassword!", salt.hex(), h) is False


def test_user_store_operations():
    store = UserStore()
    user = store.create_user("alice@example.com", "Password123!", "Alice")
    assert user["email"] == "alice@example.com"
    assert "password_hash" not in user
    assert "salt" not in user

    # Duplicate check
    with pytest.raises(ValueError, match="already exists"):
        store.create_user("alice@example.com", "Password123!")

    # Authentication
    auth_success = store.authenticate("alice@example.com", "Password123!")
    assert auth_success is not None
    assert auth_success["email"] == "alice@example.com"

    auth_fail = store.authenticate("alice@example.com", "WrongPassword")
    assert auth_fail is None


def test_token_generation_and_tampering():
    auth = AuthService(secret_key="unit-test-secret")
    user = {"id": "usr_123", "email": "test@orbit.ai", "name": "Tester"}
    token = auth.generate_token(user, expiry_seconds=3600)
    assert token.count(".") == 2

    # Verification
    payload = auth.verify_token(token)
    assert payload is not None
    assert payload["id"] == "usr_123"

    # Tampering test
    parts = token.split(".")
    tampered_token = f"{parts[0]}.{parts[1]}x.{parts[2]}"
    assert auth.verify_token(tampered_token) is None


def test_auth_endpoints(auth_client):
    client, store = auth_client

    # 1. Register
    reg_resp = client.post(
        "/api/auth/register",
        json={"email": "bob@example.com", "password": "StrongPassword99!", "name": "Bob"},
    )
    assert reg_resp.status_code == 201
    assert "token" in reg_resp.json
    token = reg_resp.json["token"]

    # 2. Login
    login_resp = client.post(
        "/api/auth/login",
        json={"email": "bob@example.com", "password": "StrongPassword99!"},
    )
    assert login_resp.status_code == 200
    assert "token" in login_resp.json

    # 3. Auth Me with token
    me_resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_resp.status_code == 200
    assert me_resp.json["user"]["email"] == "bob@example.com"

    # 4. Auth Me without token -> 401
    unauth_resp = client.get("/api/auth/me")
    assert unauth_resp.status_code == 401


def test_idor_protection(auth_client):
    client, store = auth_client

    # Register User 1
    r1 = client.post("/api/auth/register", json={"email": "u1@example.com", "password": "PassWord123!", "name": "U1"})
    t1 = r1.json["token"]

    # Register User 2
    r2 = client.post("/api/auth/register", json={"email": "u2@example.com", "password": "PassWord123!", "name": "U2"})
    t2 = r2.json["token"]

    # User 1 creates conversation
    conv_resp = client.post(
        "/api/conversations",
        json={"title": "User 1 Private Notes"},
        headers={"Authorization": f"Bearer {t1}"},
    )
    assert conv_resp.status_code == 201
    c1_id = conv_resp.json["conversation"]["_id"]

    # User 2 attempts IDOR read of User 1's conversation -> 404
    idor_read = client.get(f"/api/conversations/{c1_id}", headers={"Authorization": f"Bearer {t2}"})
    assert idor_read.status_code == 404

    # User 2 attempts IDOR delete -> 404
    idor_del = client.delete(f"/api/conversations/{c1_id}", headers={"Authorization": f"Bearer {t2}"})
    assert idor_del.status_code == 404

    # User 1 can read and delete their own conversation
    valid_read = client.get(f"/api/conversations/{c1_id}", headers={"Authorization": f"Bearer {t1}"})
    assert valid_read.status_code == 200
