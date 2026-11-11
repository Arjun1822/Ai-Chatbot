import concurrent.futures
import json
import time
from unittest.mock import MagicMock, patch
import pytest
from google.genai.errors import APIError

from app import create_app, RateLimiter
from services.conversation_store import ConversationStore
from services.llm_service import LLMService


class AdvancedTestConfig:
    SECRET_KEY = "test-advanced-secret"
    FRONTEND_URLS = ["http://localhost:3000"]
    FRONTEND_URL = "http://localhost:3000"
    MAX_CONTEXT_MESSAGES = 10
    MAX_MESSAGE_LENGTH = 1000
    MAX_ATTACHMENT_SIZE_BYTES = 500
    RATE_LIMIT_REQUESTS = 10
    RATE_LIMIT_WINDOW_SECONDS = 3
    MONGODB_URI = ""
    DATABASE_NAME = "test_adv_db"
    GEMINI_API_KEY = "dummy-key"
    GEMINI_MODEL = "gemini-3.5-flash-lite"
    SYSTEM_PROMPT = "You are Orbit test."


class MockLLM:
    configured = True
    model = "gemini-3.5-flash-lite"

    def __init__(self, delay=0.0):
        self.delay = delay
        self.call_count = 0

    def generate(self, messages):
        self.call_count += 1
        if self.delay > 0:
            time.sleep(self.delay)
        return f"Response to: {messages[-1]['content'][:20]}", {"latency_ms": int(self.delay * 1000)}

    def generate_stream(self, messages):
        self.call_count += 1
        yield {"type": "chunk", "text": "Part 1 "}
        if self.delay > 0:
            time.sleep(self.delay)
        yield {"type": "chunk", "text": "Part 2"}
        yield {"type": "done", "meta": {"latency_ms": 15}}


@pytest.fixture
def app_and_store():
    store = ConversationStore(AdvancedTestConfig)
    llm = MockLLM()
    app = create_app(AdvancedTestConfig, store=store, llm=llm)
    app.config["TESTING"] = True
    return app, store, llm


def test_tc_back_01_concurrent_chat_requests(app_and_store):
    """Verify concurrent chat requests to the same and different conversations."""
    app, store, llm = app_and_store
    client = app.test_client()

    from services.auth_service import auth_service
    user_id = "concurrent_chat_user"
    token = auth_service.generate_guest_token(guest_id=user_id)

    # Create a conversation
    conv = store.create(title="Concurrency Test", user_id=user_id)
    conv_id = conv["_id"]

    def send_chat(idx):
        with app.test_client() as c:
            return c.post(
                "/api/chat",
                json={"conversation_id": conv_id, "message": f"Message {idx}"},
                headers={
                    "X-Forwarded-For": f"10.0.0.{idx}",
                    "Authorization": f"Bearer {token}",
                },
            )

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(send_chat, i) for i in range(5)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    # All 5 requests must succeed
    for res in results:
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.data}"

    # Conversation messages must be appended safely
    updated = store.get(conv_id, user_id=user_id)
    assert len(updated["messages"]) == 10  # 5 user + 5 assistant messages


def test_tc_back_02_concurrent_conversation_updates(app_and_store):
    """Verify concurrent PATCH requests on the same conversation thread without race conditions."""
    app, store, _ = app_and_store
    from services.auth_service import auth_service
    user_id = "concurrent_update_user"
    token = auth_service.generate_guest_token(guest_id=user_id)

    conv = store.create(title="Initial Title", user_id=user_id)
    conv_id = conv["_id"]

    def update_title(idx):
        with app.test_client() as c:
            return c.patch(
                f"/api/conversations/{conv_id}",
                json={"title": f"Title {idx}"},
                headers={
                    "X-Forwarded-For": f"10.0.1.{idx}",
                    "Authorization": f"Bearer {token}",
                },
            )

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(update_title, i) for i in range(5)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    for res in results:
        assert res.status_code == 200

    updated = store.get(conv_id, user_id=user_id)
    assert updated["title"].startswith("Title ")


def test_tc_back_03_malformed_json_and_headers(app_and_store):
    """Verify handling of syntactically invalid JSON, truncated payloads, and wrong Content-Types."""
    app, _, _ = app_and_store
    client = app.test_client()

    # Broken JSON syntax
    res = client.post("/api/chat", data='{"message": "incomplete...', content_type="application/json")
    assert res.status_code == 400
    assert "Invalid JSON" in res.json["error"]

    # Wrong content type (plain text)
    res = client.post("/api/chat", data="message=hello", content_type="text/plain")
    assert res.status_code == 400

    # Empty payload body
    res = client.post("/api/chat", data="", content_type="application/json")
    assert res.status_code == 400


def test_tc_back_04_missing_and_invalid_fields(app_and_store):
    """Verify schema boundary validations."""
    app, _, _ = app_and_store
    client = app.test_client()

    # Empty string
    assert client.post("/api/chat", json={"message": "   "}).status_code == 400
    # Non-string message (array, dict, number)
    assert client.post("/api/chat", json={"message": 12345}).status_code == 400
    assert client.post("/api/chat", json={"message": ["hello"]}).status_code == 400
    # Non-existent conversation ID
    res = client.post("/api/chat", json={"conversation_id": "non-existent-uuid-9999", "message": "Hi"})
    assert res.status_code == 404
    assert "Conversation not found" in res.json["error"]


def test_tc_back_05_payload_size_limits(app_and_store):
    """Verify 512 KB request limit and message length limits."""
    app, _, _ = app_and_store
    client = app.test_client()

    # Message exceeds MAX_MESSAGE_LENGTH (1000 in config)
    long_msg = "A" * 1001
    res = client.post("/api/chat", json={"message": long_msg})
    assert res.status_code == 400
    assert "1000 characters or fewer" in res.json["error"]

    # Request exceeds MAX_CONTENT_LENGTH (512 KB)
    oversized_data = "X" * (520 * 1024)
    res = client.post("/api/chat", data=json.dumps({"message": oversized_data}), content_type="application/json")
    assert res.status_code == 413
    assert "too large" in res.json["error"].lower()


def test_tc_back_06_rate_limiter_boundaries_and_recovery():
    """Verify rate limiter triggers at exact limit, rejects further, and recovers after window."""
    limiter = RateLimiter(limit=3, window=1)
    ip = "192.168.1.50"

    assert not limiter.is_limited(ip)  # Req 1
    assert not limiter.is_limited(ip)  # Req 2
    assert not limiter.is_limited(ip)  # Req 3
    assert limiter.is_limited(ip)      # Req 4 -> BLOCKED (429)

    # Wait for window expiration
    time.sleep(1.1)
    assert not limiter.is_limited(ip)  # Recovered -> ALLOWED


def test_tc_back_07_gemini_error_handling_and_retry(app_and_store):
    """Verify handling when Gemini API returns 429 or 503 errors."""
    config = AdvancedTestConfig()
    service = LLMService(config)

    # Mock client generate_content throwing APIError 429
    mock_client = MagicMock()
    err_429 = APIError(429, {"message": "Resource exhausted"})
    mock_client.models.generate_content.side_effect = err_429
    service.client = mock_client

    with pytest.raises(APIError):
        service.generate([{"role": "user", "content": "hi"}], max_retries=1)

    # Verify generate_content was called twice (attempt 0 + retry 1)
    assert mock_client.models.generate_content.call_count == 2


def test_tc_back_08_streaming_connection_closure(app_and_store):
    """Verify streaming generators complete cleanly and close resources."""
    app, _, _ = app_and_store
    client = app.test_client()

    response = client.post("/api/chat/stream", json={"message": "Stream closure test"})
    assert response.status_code == 200

    chunks = []
    for line in response.response:
        decoded = line.decode("utf-8")
        if decoded.startswith("data: "):
            payload = json.loads(decoded[6:])
            chunks.append(payload)

    # Must contain chunks and final done event
    assert any(c.get("type") == "chunk" for c in chunks)
    done_events = [c for c in chunks if c.get("type") == "done"]
    assert len(done_events) == 1
    assert "conversation" in done_events[0]
    assert "meta" in done_events[0]


def test_tc_back_09_database_persistence_vs_in_memory_behavior():
    """Verify data lifecycle under in-memory store and verify bounded eviction."""
    config = AdvancedTestConfig()
    store1 = ConversationStore(config)
    c1 = store1.create(title="Persist Test")

    # In-memory store does not persist across new store instances without MongoDB
    store2 = ConversationStore(config)
    assert store2.get(c1["_id"]) is None  # Independent in-memory store

    # Test bounded capacity eviction
    store1.MAX_IN_MEMORY_CONVERSATIONS = 5
    for i in range(10):
        store1.create(title=f"Conv {i}")

    # Must not exceed max capacity
    assert len(store1.list()) <= 5
