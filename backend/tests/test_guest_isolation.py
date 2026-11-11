import io
import time
import pytest
from app import create_app
from config import Config
from rag.chunker import DocumentChunk
from rag.vector_store import LocalVectorStore
from services.auth_service import AuthService, auth_service
from services.user_store import UserStore


class IsolationTestConfig(Config):
    TESTING = True
    MONGODB_URI = ""
    GEMINI_API_KEY = "mock_key_for_testing"


@pytest.fixture
def isolation_client():
    test_user_store = UserStore()
    app = create_app(config_class=IsolationTestConfig, user_st=test_user_store)
    client = app.test_client()
    return client, test_user_store


def test_guest_session_generation_and_continuity(isolation_client):
    """Verify /api/auth/guest-session issues cryptographically signed guest tokens with continuity."""
    client, _ = isolation_client

    # 1. Fetch new guest session
    resp1 = client.get("/api/auth/guest-session")
    assert resp1.status_code == 200
    data1 = resp1.json
    assert data1["is_guest"] is True
    assert data1["guest_id"].startswith("guest_")
    token1 = data1["token"]
    assert token1 is not None

    # Verify signature of issued token
    verified = auth_service.verify_token(token1)
    assert verified is not None
    assert verified["id"] == data1["guest_id"]
    assert verified["is_guest"] is True

    # 2. Second request supplying X-Guest-Token preserves the exact same guest identity
    resp2 = client.get("/api/auth/guest-session", headers={"X-Guest-Token": token1})
    assert resp2.status_code == 200
    assert resp2.json["guest_id"] == data1["guest_id"]

    # 3. Supplying Bearer token also preserves the exact same guest identity
    resp3 = client.get("/api/auth/guest-session", headers={"Authorization": f"Bearer {token1}"})
    assert resp3.status_code == 200
    assert resp3.json["guest_id"] == data1["guest_id"]

    # 4. Another visitor without token gets a unique, independent guest ID
    other_client = create_app(config_class=IsolationTestConfig).test_client()
    resp_other = other_client.get("/api/auth/guest-session")
    assert resp_other.status_code == 200
    assert resp_other.json["guest_id"] != data1["guest_id"]


def test_guest_to_guest_document_isolation(isolation_client):
    """Guest A uploads document. Guest B cannot list, retrieve, or delete Guest A's document."""
    client, _ = isolation_client

    token_a = auth_service.generate_guest_token(guest_id="guest_alpha_111")
    token_b = auth_service.generate_guest_token(guest_id="guest_bravo_222")

    # 1. Guest A uploads a document
    doc_data = {"file": (io.BytesIO(b"Guest A proprietary document content."), "guest_a_notes.txt")}
    up_resp = client.post(
        "/api/documents",
        data=doc_data,
        content_type="multipart/form-data",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert up_resp.status_code == 201
    doc_id_a = up_resp.json["document"]["document_id"]
    assert up_resp.json["document"]["user_id"] == "guest_alpha_111"

    # 2. Guest B lists documents -> receives empty list or does not contain Guest A's doc
    list_b = client.get("/api/documents", headers={"Authorization": f"Bearer {token_b}"})
    assert list_b.status_code == 200
    docs_b_ids = [d["document_id"] for d in list_b.json["documents"]]
    assert doc_id_a not in docs_b_ids

    # 3. Guest B attempts to delete Guest A's document -> rejected with 404
    del_b = client.delete(f"/api/documents/{doc_id_a}", headers={"Authorization": f"Bearer {token_b}"})
    assert del_b.status_code == 404

    # 4. Guest A lists documents -> sees their document
    list_a = client.get("/api/documents", headers={"Authorization": f"Bearer {token_a}"})
    assert list_a.status_code == 200
    docs_a_ids = [d["document_id"] for d in list_a.json["documents"]]
    assert doc_id_a in docs_a_ids

    # 5. Guest A can delete their own document -> 200
    del_a = client.delete(f"/api/documents/{doc_id_a}", headers={"Authorization": f"Bearer {token_a}"})
    assert del_a.status_code == 200


def test_guests_cannot_access_authenticated_user_documents(isolation_client):
    """Unauthenticated guests cannot access or delete authenticated user documents."""
    client, _ = isolation_client

    # Register authenticated user
    reg = client.post(
        "/api/auth/register",
        json={"email": "corporate@example.com", "password": "SecretPassword123!", "name": "Corp User"},
    )
    auth_token = reg.json["token"]
    user_id = reg.json["user"]["id"]

    # Authenticated user uploads document
    doc_data = {"file": (io.BytesIO(b"Quarterly corporate financial audit report."), "q3_audit.txt")}
    up = client.post(
        "/api/documents",
        data=doc_data,
        content_type="multipart/form-data",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert up.status_code == 201
    auth_doc_id = up.json["document"]["document_id"]
    assert up.json["document"]["user_id"] == user_id

    # Anonymous guest attempts to list documents
    guest_token = auth_service.generate_guest_token()
    guest_list = client.get("/api/documents", headers={"Authorization": f"Bearer {guest_token}"})
    assert guest_list.status_code == 200
    guest_doc_ids = [d["document_id"] for d in guest_list.json["documents"]]
    assert auth_doc_id not in guest_doc_ids

    # Anonymous guest attempts to delete authenticated user document -> 404
    guest_del = client.delete(f"/api/documents/{auth_doc_id}", headers={"Authorization": f"Bearer {guest_token}"})
    assert guest_del.status_code == 404


def test_vector_search_strict_multi_tenant_isolation():
    """Verify vector store search fails closed on missing user_id and strictly scopes by tenant."""
    store = LocalVectorStore()

    # Ingest chunks for tenant_alpha
    chunk_a = DocumentChunk(
        chunk_id="chk_a1",
        document_id="doc_a1",
        text="Alpha secret: the blueprint password is Phoenix42",
        chunk_index=0,
        char_start=0,
        char_end=45,
        metadata={"filename": "alpha.txt"},
    )
    store.add_chunks(
        chunks=[chunk_a],
        embeddings=[[1.0, 0.0, 0.0]],
        user_id="tenant_alpha",
    )

    # Ingest chunks for tenant_bravo
    chunk_b = DocumentChunk(
        chunk_id="chk_b1",
        document_id="doc_b1",
        text="Bravo secret: the nuclear launch code is Orion99",
        chunk_index=0,
        char_start=0,
        char_end=44,
        metadata={"filename": "bravo.txt"},
    )
    store.add_chunks(
        chunks=[chunk_b],
        embeddings=[[1.0, 0.0, 0.0]],
        user_id="tenant_bravo",
    )

    # 1. Search with tenant_alpha returns ONLY alpha chunk
    res_a = store.search(query_embedding=[1.0, 0.0, 0.0], user_id="tenant_alpha")
    assert len(res_a) == 1
    assert res_a[0].chunk_id == "chk_a1"
    assert res_a[0].user_id == "tenant_alpha"

    # 2. Search with tenant_bravo returns ONLY bravo chunk
    res_b = store.search(query_embedding=[1.0, 0.0, 0.0], user_id="tenant_bravo")
    assert len(res_b) == 1
    assert res_b[0].chunk_id == "chk_b1"
    assert res_b[0].user_id == "tenant_bravo"

    # 3. Search without user_id fails closed (returns empty list)
    res_none = store.search(query_embedding=[1.0, 0.0, 0.0], user_id=None)
    assert res_none == []

    res_empty = store.search(query_embedding=[1.0, 0.0, 0.0], user_id="")
    assert res_empty == []


def test_conversation_isolation_between_guests(isolation_client):
    """Guest A conversation cannot be read, patched, chatted in, or deleted by Guest B."""
    client, _ = isolation_client

    token_a = auth_service.generate_guest_token(guest_id="guest_convo_a")
    token_b = auth_service.generate_guest_token(guest_id="guest_convo_b")

    # Guest A creates conversation
    create_resp = client.post(
        "/api/conversations",
        json={"title": "Guest A Secret Research"},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert create_resp.status_code == 201
    conv_id = create_resp.json["conversation"]["_id"]
    assert create_resp.json["conversation"]["user_id"] == "guest_convo_a"

    # Guest B cannot read Guest A conversation -> 404
    get_b = client.get(f"/api/conversations/{conv_id}", headers={"Authorization": f"Bearer {token_b}"})
    assert get_b.status_code == 404

    # Guest B cannot update Guest A conversation -> 404
    patch_b = client.patch(
        f"/api/conversations/{conv_id}",
        json={"title": "Hacked Title"},
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert patch_b.status_code == 404

    # Guest B cannot chat in Guest A conversation -> 404
    chat_b = client.post(
        "/api/chat",
        json={"conversation_id": conv_id, "message": "Injected message from Guest B"},
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert chat_b.status_code == 404

    # Guest B cannot delete Guest A conversation -> 404
    del_b = client.delete(f"/api/conversations/{conv_id}", headers={"Authorization": f"Bearer {token_b}"})
    assert del_b.status_code == 404

    # Guest A can read their conversation
    get_a = client.get(f"/api/conversations/{conv_id}", headers={"Authorization": f"Bearer {token_a}"})
    assert get_a.status_code == 200
    assert get_a.json["conversation"]["title"] == "Guest A Secret Research"

    # Guest A can delete their conversation -> 200
    del_a = client.delete(f"/api/conversations/{conv_id}", headers={"Authorization": f"Bearer {token_a}"})
    assert del_a.status_code == 200


def test_memory_isolation_between_guests(isolation_client):
    """Guest A memory preferences are completely invisible to Guest B."""
    client, _ = isolation_client

    token_a = auth_service.generate_guest_token(guest_id="guest_mem_a")
    token_b = auth_service.generate_guest_token(guest_id="guest_mem_b")

    # Guest A adds a memory
    mem_resp = client.post(
        "/api/memories",
        json={"content": "Guest A prefers responses in bullet points.", "category": "preference", "importance": 4},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert mem_resp.status_code == 201
    mem_id = mem_resp.json["memory"]["id"]

    # Guest B lists memories -> does not see Guest A's memory
    list_b = client.get("/api/memories", headers={"Authorization": f"Bearer {token_b}"})
    assert list_b.status_code == 200
    mem_ids_b = [m["id"] for m in list_b.json["memories"]]
    assert mem_id not in mem_ids_b

    # Guest B attempts to delete Guest A's memory -> 404
    del_b = client.delete(f"/api/memories/{mem_id}", headers={"Authorization": f"Bearer {token_b}"})
    assert del_b.status_code == 404

    # Guest A can list and delete their memory
    list_a = client.get("/api/memories", headers={"Authorization": f"Bearer {token_a}"})
    assert list_a.status_code == 200
    mem_ids_a = [m["id"] for m in list_a.json["memories"]]
    assert mem_id in mem_ids_a

    del_a = client.delete(f"/api/memories/{mem_id}", headers={"Authorization": f"Bearer {token_a}"})
    assert del_a.status_code == 200


def test_invalid_and_expired_tokens_rejected_with_401(isolation_client):
    """Requests with tampered, malformed, or expired JWT tokens are rejected with HTTP 401."""
    client, _ = isolation_client

    # 1. Tampered token
    tampered = "eyJhbGciOiAiSFMyNTYiLCAidHlwIjogIkpXVCJ9.eyJzdWIiOiAiYWRtaW4ifQ.invalid_sig"
    resp1 = client.get("/api/documents", headers={"Authorization": f"Bearer {tampered}"})
    assert resp1.status_code == 401
    assert "Invalid or expired token." in resp1.json["error"]

    # 2. Expired token
    expired_token = auth_service.generate_guest_token(guest_id="guest_exp", expiry_seconds=-10)
    resp2 = client.get("/api/documents", headers={"Authorization": f"Bearer {expired_token}"})
    assert resp2.status_code == 401
    assert "Invalid or expired token." in resp2.json["error"]

    # 3. Malformed Authorization header format (missing Bearer prefix)
    resp3 = client.get("/api/documents", headers={"Authorization": "Basic 12345"})
    assert resp3.status_code == 401
    assert "Invalid Authorization header format" in resp3.json["error"]

    # 4. Invalid X-Guest-Token
    resp4 = client.get("/api/documents", headers={"X-Guest-Token": "bogus_guest_token"})
    assert resp4.status_code == 401
    assert "Invalid or expired token." in resp4.json["error"]

    # 5. Invalid token on chat endpoint
    resp5 = client.post(
        "/api/chat",
        json={"message": "Hello"},
        headers={"Authorization": "Bearer bad.token.value"},
    )
    assert resp5.status_code == 401
    assert "Invalid or expired token." in resp5.json["error"]

