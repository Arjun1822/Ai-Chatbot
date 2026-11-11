import io
import json
from unittest.mock import MagicMock, patch
import pytest
from app import create_app, RateLimiter, create_title_from_text
from services.conversation_store import ConversationStore
from services.llm_service import LLMService


class TestConfig:
    SECRET_KEY = "test"
    FRONTEND_URLS = ["http://localhost:3000", "http://localhost:5173"]
    FRONTEND_URL = "http://localhost:3000"
    MAX_CONTEXT_MESSAGES = 4
    MAX_MESSAGE_LENGTH = 100
    MAX_ATTACHMENT_SIZE_BYTES = 200
    RATE_LIMIT_REQUESTS = 5
    RATE_LIMIT_WINDOW_SECONDS = 2
    MONGODB_URI = ""
    DATABASE_NAME = "test"
    GEMINI_API_KEY = ""
    GEMINI_MODEL = "test-model"
    SYSTEM_PROMPT = "test-prompt"


class FakeStreamingLLM:
    configured = True
    model = "test-model"

    def __init__(self):
        self.calls = []

    def generate(self, messages):
        self.calls.append(messages)
        return "A mocked answer.", {"latency_ms": 42, "model": "test-model"}

    def generate_stream(self, messages):
        self.calls.append(messages)
        yield {"type": "chunk", "text": "A mocked "}
        yield {"type": "chunk", "text": "streaming answer."}
        yield {"type": "done", "meta": {"latency_ms": 25, "model": "test-model"}}


@pytest.fixture
def client():
    llm = FakeStreamingLLM()
    app = create_app(TestConfig, store=ConversationStore(TestConfig), llm=llm)
    app.config["TESTING"] = True
    with app.test_client() as test_client:
        yield test_client, llm


def test_health_check(client):
    test_client, _ = client
    health = test_client.get("/api/health")
    assert health.status_code == 200
    data = health.json
    assert data["status"] == "ok"
    assert data["database"] == "in-memory"
    assert data["llm_configured"] is True
    assert data["model"] == "test-model"


def test_create_and_list_conversations(client):
    test_client, _ = client
    created = test_client.post("/api/conversations", json={"title": "Custom Title"})
    assert created.status_code == 201
    conv_id = created.json["conversation"]["_id"]
    assert created.json["conversation"]["title"] == "Custom Title"

    listing = test_client.get("/api/conversations")
    assert listing.status_code == 200
    ids = [c["_id"] for c in listing.json["conversations"]]
    assert conv_id in ids


def test_chat_and_context(client):
    test_client, llm = client
    first = test_client.post("/api/chat", json={"message": "Hello AI world"})
    assert first.status_code == 200
    conv = first.json["conversation"]
    conv_id = conv["_id"]
    assert conv["title"] == "Hello AI world"
    assert len(conv["messages"]) == 2

    second = test_client.post(
        "/api/chat", json={"conversation_id": conv_id, "message": "Follow up question"}
    )
    assert second.status_code == 200
    assert len(second.json["conversation"]["messages"]) == 4
    assert len(llm.calls[1]) == 3


def test_chat_streaming(client):
    test_client, _ = client
    response = test_client.post("/api/chat/stream", json={"message": "Stream this"})
    assert response.status_code == 200
    assert "text/event-stream" in response.headers["Content-Type"]
    content = response.data.decode("utf-8")
    assert "data: " in content
    assert "streaming answer." in content


def test_chat_validation(client):
    test_client, _ = client
    # Empty message
    assert test_client.post("/api/chat", json={"message": ""}).status_code == 400
    # Missing message
    assert test_client.post("/api/chat", json={}).status_code == 400
    # Invalid JSON
    assert test_client.post(
        "/api/chat", data="not json", content_type="application/json"
    ).status_code == 400
    # Exceeding MAX_MESSAGE_LENGTH (100 in TestConfig)
    long_msg = "x" * 101
    assert test_client.post("/api/chat", json={"message": long_msg}).status_code == 400


def test_attachment_handling(client):
    test_client, _ = client
    # Valid attachment
    valid_resp = test_client.post(
        "/api/chat",
        json={
            "message": "Review code",
            "attachment": {"name": "app.py", "content": "print('hello')"},
        },
    )
    assert valid_resp.status_code == 200
    assert "[Attached File: app.py]" in valid_resp.json["conversation"]["messages"][0]["content"]

    # Attachment too large (>200 bytes in TestConfig)
    huge_resp = test_client.post(
        "/api/chat",
        json={
            "message": "Review code",
            "attachment": {"name": "big.txt", "content": "x" * 250},
        },
    )
    assert huge_resp.status_code == 400
    assert "exceeds maximum allowed size" in huge_resp.json["error"]


def test_update_and_delete_conversation(client):
    test_client, _ = client
    created = test_client.post("/api/conversations").json["conversation"]["_id"]

    # Valid rename
    patch = test_client.patch(f"/api/conversations/{created}", json={"title": "Renamed Project"})
    assert patch.status_code == 200
    assert patch.json["conversation"]["title"] == "Renamed Project"

    # Empty title
    assert test_client.patch(f"/api/conversations/{created}", json={"title": "   "}).status_code == 400

    # Delete
    assert test_client.delete(f"/api/conversations/{created}").status_code == 200
    assert test_client.get(f"/api/conversations/{created}").status_code == 404


def test_security_headers(client):
    test_client, _ = client
    resp = test_client.get("/api/health")
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"


def test_rate_limiter_unit():
    limiter = RateLimiter(limit=3, window=1)
    ip = "192.168.1.100"
    assert not limiter.is_limited(ip)
    assert not limiter.is_limited(ip)
    assert not limiter.is_limited(ip)
    assert limiter.is_limited(ip)


def test_create_title_helper():
    short = create_title_from_text("Explain Python decorators")
    assert short == "Explain Python decorators"

    long_text = "This is a very long question that exceeds forty-eight characters easily without doubt"
    title = create_title_from_text(long_text, max_length=30)
    assert len(title) <= 33
    assert title.endswith("...")
    assert not title.endswith(" ...")


def test_llm_service_unconfigured():
    config = TestConfig()
    config.GEMINI_API_KEY = ""
    service = LLMService(config)
    assert service.configured is False
    with pytest.raises(RuntimeError) as exc:
        service.generate([{"role": "user", "content": "hi"}])
    assert "GEMINI_API_KEY is not configured" in str(exc.value)


def test_llm_service_mocked_generation():
    config = TestConfig()
    config.GEMINI_API_KEY = "dummy-key"
    service = LLMService(config)
    assert service.configured is True

    # Mock client generate_content
    mock_candidate = MagicMock()
    mock_part = MagicMock()
    mock_part.text = "Hello there!"
    mock_candidate.content.parts = [mock_part]

    mock_response = MagicMock()
    mock_response.candidates = [mock_candidate]
    mock_response.text = "Hello there!"
    mock_response.usage_metadata.prompt_token_count = 5
    mock_response.usage_metadata.candidates_token_count = 3
    mock_response.usage_metadata.total_token_count = 8

    service.client = MagicMock()
    service.client.models.generate_content.return_value = mock_response

    text, meta = service.generate([{"role": "user", "content": "hello"}])
    assert text == "Hello there!"
    assert meta["prompt_tokens"] == 5
    assert meta["candidates_tokens"] == 3
    assert meta["total_tokens"] == 8


def _sample_pdf_bytes():
    return (
        b"%PDF-1.4\n"
        b"1 0 obj <</Type /Catalog /Pages 2 0 R>> endobj\n"
        b"2 0 obj <</Type /Pages /Kids [3 0 R] /Count 1>> endobj\n"
        b"3 0 obj <</Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources <</Font <</F1 5 0 R>>>>>> endobj\n"
        b"4 0 obj <</Length 44>> stream\n"
        b"BT /F1 12 Tf 100 700 Td (Hello ORBIT AI PDF) Tj ET\n"
        b"endstream\n"
        b"endobj\n"
        b"5 0 obj <</Type /Font /Subtype /Type1 /BaseFont /Helvetica>> endobj\n"
        b"xref\n0 6\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \n0000000244 00000 n \n0000000338 00000 n \n"
        b"trailer <</Size 6 /Root 1 0 R>>\nstartxref\n417\n%%EOF\n"
    )


def test_document_upload_valid_pdf(client):
    test_client, _ = client
    pdf_bytes = _sample_pdf_bytes()
    data = {"file": (io.BytesIO(pdf_bytes), "sample.pdf")}
    resp = test_client.post("/api/documents", data=data, content_type="multipart/form-data")
    assert resp.status_code == 201
    assert "document" in resp.json
    doc = resp.json["document"]
    assert doc["filename"] == "sample.pdf"
    assert doc["total_chunks"] >= 1


def test_document_upload_valid_text(client):
    test_client, _ = client
    # 1. Multipart text upload
    txt_data = {"file": (io.BytesIO(b"Artificial Intelligence in orbit."), "notes.txt")}
    resp = test_client.post("/api/documents", data=txt_data, content_type="multipart/form-data")
    assert resp.status_code == 201
    assert resp.json["document"]["filename"] == "notes.txt"

    # 2. JSON document upload
    json_payload = {"filename": "guide.md", "content": "# ORBIT AI Guide\n\nComprehensive user instructions."}
    resp_json = test_client.post("/api/documents", json=json_payload)
    assert resp_json.status_code == 201
    assert resp_json.json["document"]["filename"] == "guide.md"


def test_document_upload_missing_file_and_content(client):
    test_client, _ = client
    # 1. Missing both file and content (empty body)
    resp = test_client.post("/api/documents", json={})
    assert resp.status_code == 400
    assert "File or filename and content is required." in resp.json["error"]

    # 2. No file selected (empty filename)
    empty_fn_data = {"file": (io.BytesIO(b"content"), "")}
    resp = test_client.post("/api/documents", data=empty_fn_data, content_type="multipart/form-data")
    assert resp.status_code == 400
    assert "No file selected." in resp.json["error"]

    # 3. Empty file (0 bytes)
    empty_bytes_data = {"file": (io.BytesIO(b""), "empty.txt")}
    resp = test_client.post("/api/documents", data=empty_bytes_data, content_type="multipart/form-data")
    assert resp.status_code == 400
    assert "File is empty (0 bytes)." in resp.json["error"]


def test_document_upload_unsupported_file_type(client):
    test_client, _ = client
    bad_data = {"file": (io.BytesIO(b"MZ\x90\x00executable binary"), "virus.exe")}
    resp = test_client.post("/api/documents", data=bad_data, content_type="multipart/form-data")
    assert resp.status_code == 400
    assert "Unsupported file format" in resp.json["error"]


def test_document_upload_unauthenticated(client):
    test_client, _ = client
    # 1. Unauthenticated request without Authorization header succeeds under isolated guest session
    txt_data = {"file": (io.BytesIO(b"Guest knowledge document."), "guest_doc.txt")}
    resp = test_client.post("/api/documents", data=txt_data, content_type="multipart/form-data")
    assert resp.status_code == 201
    assert resp.json["document"]["user_id"].startswith("guest_")
    assert "X-Guest-Token" in resp.headers

    # 2. Invalid or expired token is rejected with 401
    bad_token_data = {"file": (io.BytesIO(b"Unauthorized data."), "secret.txt")}
    resp_bad = test_client.post(
        "/api/documents",
        data=bad_token_data,
        content_type="multipart/form-data",
        headers={"Authorization": "Bearer invalid.jwt.token"},
    )
    assert resp_bad.status_code == 401
    assert "Invalid or expired token." in resp_bad.json["error"]

    # 3. Malformed Authorization header format is rejected with 401
    malformed_data = {"file": (io.BytesIO(b"Malformed auth data."), "secret2.txt")}
    resp_malformed = test_client.post(
        "/api/documents",
        data=malformed_data,
        content_type="multipart/form-data",
        headers={"Authorization": "Basic 12345"},
    )
    assert resp_malformed.status_code == 401
    assert "Invalid Authorization header format" in resp_malformed.json["error"]
