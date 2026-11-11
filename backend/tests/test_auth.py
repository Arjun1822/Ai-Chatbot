import io
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


def test_document_user_isolation(auth_client):
    client, store = auth_client

    # Register User 1
    r1 = client.post("/api/auth/register", json={"email": "doc1@example.com", "password": "Password123!", "name": "Doc1"})
    t1 = r1.json["token"]

    # Register User 2
    r2 = client.post("/api/auth/register", json={"email": "doc2@example.com", "password": "Password123!", "name": "Doc2"})
    t2 = r2.json["token"]

    # User 1 uploads a private document
    data1 = {"file": (io.BytesIO(b"Confidential financial statement for Doc1."), "doc1_private.txt")}
    up_resp = client.post("/api/documents", data=data1, content_type="multipart/form-data", headers={"Authorization": f"Bearer {t1}"})
    assert up_resp.status_code == 201
    doc_id = up_resp.json["document"]["document_id"]

    # User 1 lists documents -> sees doc1_private.txt
    list1 = client.get("/api/documents", headers={"Authorization": f"Bearer {t1}"})
    assert list1.status_code == 200
    doc_ids_u1 = [d["document_id"] for d in list1.json["documents"]]
    assert doc_id in doc_ids_u1

    # User 2 lists documents -> does NOT see User 1's document
    list2 = client.get("/api/documents", headers={"Authorization": f"Bearer {t2}"})
    assert list2.status_code == 200
    doc_ids_u2 = [d["document_id"] for d in list2.json["documents"]]
    assert doc_id not in doc_ids_u2

    # User 2 attempts IDOR deletion of User 1's document -> 404
    idor_del = client.delete(f"/api/documents/{doc_id}", headers={"Authorization": f"Bearer {t2}"})
    assert idor_del.status_code == 404

    # User 1 can successfully delete their own document -> 200
    owner_del = client.delete(f"/api/documents/{doc_id}", headers={"Authorization": f"Bearer {t1}"})
    assert owner_del.status_code == 200


def test_admin_authorization_metrics(auth_client):
    """Verify GET /api/admin/metrics requires an authenticated administrator and rejects guests / ordinary users."""
    client, store = auth_client
    from services.auth_service import auth_service

    # 1. Unauthenticated request -> 401
    unauth = client.get("/api/admin/metrics")
    assert unauth.status_code == 401
    assert "Admin access only" in unauth.json["error"]

    # 2. Guest user token -> 401
    guest_token = auth_service.generate_guest_token(guest_id="guest_curious")
    guest_resp = client.get("/api/admin/metrics", headers={"Authorization": f"Bearer {guest_token}"})
    assert guest_resp.status_code == 401
    assert "Admin access only" in guest_resp.json["error"]

    # 3. Standard registered user -> 403
    reg = client.post(
        "/api/auth/register",
        json={"email": "standard@example.com", "password": "UserPassword123!", "name": "Standard User"},
    )
    user_token = reg.json["token"]
    user_resp = client.get("/api/admin/metrics", headers={"Authorization": f"Bearer {user_token}"})
    assert user_resp.status_code == 403
    assert "Administrator privileges required" in user_resp.json["error"]

    # 4. Administrator user -> 200
    admin_user = store.create_user("admin@orbit.ai", "AdminPassword123!", name="Admin", role="admin")
    admin_token = auth_service.generate_token(admin_user)
    admin_resp = client.get("/api/admin/metrics", headers={"Authorization": f"Bearer {admin_token}"})
    assert admin_resp.status_code == 200
    assert "metrics" in admin_resp.json
    metrics = admin_resp.json["metrics"]
    assert "conversations_count" in metrics
    assert "documents_count" in metrics


def test_registration_privilege_escalation_blocked(auth_client):
    """Verify that public registration strictly forces role='user' regardless of client input."""
    client, store = auth_client
    from services.auth_service import auth_service

    # Attempt to register with role='admin' in payload
    payload = {
        "email": "attacker@evil.com",
        "password": "AttackerPass123!",
        "name": "Attacker",
        "role": "admin",
        "is_admin": True,
        "is_guest": False,
    }
    reg_resp = client.post("/api/auth/register", json=payload)
    assert reg_resp.status_code == 201
    created_user = reg_resp.json["user"]
    token = reg_resp.json["token"]

    # Role in response must be 'user'
    assert created_user["role"] == "user"

    # Role in database/store must be 'user'
    db_user = store.get_by_email("attacker@evil.com")
    assert db_user is not None
    assert db_user["role"] == "user"

    # Verified token payload must contain role='user'
    token_claims = auth_service.verify_token(token)
    assert token_claims["role"] == "user"

    # Attacker token must fail admin metrics endpoint -> 403
    admin_attempt = client.get("/api/admin/metrics", headers={"Authorization": f"Bearer {token}"})
    assert admin_attempt.status_code == 403
    assert "Administrator privileges required" in admin_attempt.json["error"]


def test_profile_role_tampering_blocked(auth_client):
    """Verify existing users cannot modify their role or escalate privileges via profile routes."""
    client, store = auth_client

    # Register standard user
    reg = client.post(
        "/api/auth/register",
        json={"email": "victim@example.com", "password": "UserPass123!", "name": "Victim"},
    )
    assert reg.status_code == 201
    user_token = reg.json["token"]
    user_id = reg.json["user"]["id"]

    headers = {"Authorization": f"Bearer {user_token}"}

    # Attempt PUT /api/auth/me -> 405 Method Not Allowed
    put_me = client.put("/api/auth/me", json={"role": "admin"}, headers=headers)
    assert put_me.status_code == 405

    # Attempt PATCH /api/auth/me -> 405 Method Not Allowed
    patch_me = client.patch("/api/auth/me", json={"role": "admin"}, headers=headers)
    assert patch_me.status_code == 405

    # Attempt PATCH /api/users/<user_id> -> 404 Not Found (endpoint does not exist)
    patch_user = client.patch(f"/api/users/{user_id}", json={"role": "admin"}, headers=headers)
    assert patch_user.status_code == 404

    # Attempt PUT /api/users/<user_id> -> 404 Not Found
    put_user = client.put(f"/api/users/{user_id}", json={"role": "admin"}, headers=headers)
    assert put_user.status_code == 404

    # Verify user role remains strictly 'user'
    me_resp = client.get("/api/auth/me", headers=headers)
    assert me_resp.status_code == 200
    assert me_resp.json["user"]["role"] == "user"


def test_revoked_admin_jwt_cannot_access_admin_metrics(auth_client):
    """Verify that if an administrator's role is revoked, their previously issued JWT is rejected."""
    client, store = auth_client
    from services.auth_service import auth_service

    # 1. Trusted server-side admin provisioning
    admin_user = store.create_user("legit_admin@orbit.ai", "SuperSecret123!", name="Admin Boss", role="admin")
    admin_id = admin_user["id"]
    admin_token = auth_service.generate_token(admin_user)

    # 2. Admin successfully accesses /api/admin/metrics
    valid_resp = client.get("/api/admin/metrics", headers={"Authorization": f"Bearer {admin_token}"})
    assert valid_resp.status_code == 200

    # 3. Server-side revocation / demotion of administrator
    store.set_user_role(admin_id, "user")

    # 4. Attempt to use the previously-issued admin token -> MUST BE REJECTED 403
    revoked_resp = client.get("/api/admin/metrics", headers={"Authorization": f"Bearer {admin_token}"})
    assert revoked_resp.status_code == 403
    assert "Administrator privileges required" in revoked_resp.json["error"]

    # 5. /api/auth/me reflects the demoted status
    me_resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {admin_token}"})
    assert me_resp.status_code == 200
    assert me_resp.json["user"]["role"] == "user"


def test_deleted_admin_cannot_access_admin_metrics(auth_client):
    """Verify that if an administrator account is deleted, their previously issued JWT is rejected."""
    client, store = auth_client
    from services.auth_service import auth_service

    # 1. Provision admin and generate token
    admin_user = store.create_user("temp_admin@orbit.ai", "SuperSecret123!", name="Temp Admin", role="admin")
    admin_id = admin_user["id"]
    admin_token = auth_service.generate_token(admin_user)

    # Access is valid initially
    assert client.get("/api/admin/metrics", headers={"Authorization": f"Bearer {admin_token}"}).status_code == 200

    # 2. Admin account is removed/deleted from user store
    with store._lock:
        store._users.pop(admin_id, None)
        store._email_index.pop("temp_admin@orbit.ai", None)

    # 3. Attempt to use old JWT -> MUST BE REJECTED 403
    deleted_resp = client.get("/api/admin/metrics", headers={"Authorization": f"Bearer {admin_token}"})
    assert deleted_resp.status_code == 403


def test_require_admin_fails_closed_when_store_missing(auth_client):
    """Verify @require_admin() fails closed with 403 if user_store is missing or None."""
    client, store = auth_client
    from services.auth_service import auth_service

    admin_user = store.create_user("orphan_admin@orbit.ai", "SuperSecret123!", role="admin")
    admin_token = auth_service.generate_token(admin_user)

    # Simulate missing/unconfigured store
    auth_service.set_user_store(None)
    try:
        resp = client.get("/api/admin/metrics", headers={"Authorization": f"Bearer {admin_token}"})
        assert resp.status_code == 403
        assert "Administrator verification unavailable" in resp.json["error"]
    finally:
        # Restore store for subsequent tests
        auth_service.set_user_store(store)


def test_require_admin_fails_closed_when_store_raises_exception(auth_client, monkeypatch):
    """Verify @require_admin() fails closed with 403 if user_store lookup raises an unexpected exception."""
    client, store = auth_client
    from services.auth_service import auth_service

    admin_user = store.create_user("crash_admin@orbit.ai", "SuperSecret123!", role="admin")
    admin_token = auth_service.generate_token(admin_user)

    def crashing_get_by_id(_uid):
        raise RuntimeError("Database connection suddenly dropped")

    monkeypatch.setattr(store, "get_by_id", crashing_get_by_id)

    resp = client.get("/api/admin/metrics", headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 403
    assert "Administrator verification" in resp.json["error"]
