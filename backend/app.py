import json
from collections import defaultdict
from datetime import datetime, timezone
from threading import Lock
from time import monotonic

from flask import Flask, Response, jsonify, request, stream_with_context
from flask_cors import CORS

from config import Config
from services.conversation_store import ConversationStore
from services.llm_service import LLMService


class RateLimiter:
    """Thread-safe sliding-window rate limiter with memory eviction."""

    def __init__(self, limit=60, window=60):
        self.limit = limit
        self.window = window
        self._history = defaultdict(list)
        self._lock = Lock()
        self._last_cleanup = monotonic()

    def is_limited(self, key: str) -> bool:
        now = monotonic()
        with self._lock:
            # Periodic cleanup every 60 seconds to prevent unbounded memory growth
            if now - self._last_cleanup > 60:
                stale_keys = [k for k, stamps in self._history.items() if not stamps or now - stamps[-1] > self.window]
                for k in stale_keys:
                    self._history.pop(k, None)
                self._last_cleanup = now

            timestamps = [s for s in self._history[key] if now - s < self.window]
            if len(timestamps) >= self.limit:
                self._history[key] = timestamps
                return True
            timestamps.append(now)
            self._history[key] = timestamps
            return False


def create_title_from_text(text: str, max_length: int = 48) -> str:
    """Generate a clean, word-boundary preserved conversation title."""
    cleaned = " ".join(text.strip().split())
    if len(cleaned) <= max_length:
        return cleaned
    truncated = cleaned[:max_length]
    if " " in truncated:
        truncated = truncated.rsplit(" ", 1)[0]
    return truncated + "..."


def create_app(config_class=Config, store=None, llm=None):
    app = Flask(__name__)
    app.config.from_object(config_class)
    app.config["MAX_CONTENT_LENGTH"] = 512 * 1024  # 512 KB to allow text attachments

    allowed_origins = getattr(config_class, "FRONTEND_URLS", [app.config.get("FRONTEND_URL", "http://localhost:3000")])
    CORS(
        app,
        resources={r"/api/*": {"origins": allowed_origins}},
        supports_credentials=True,
        expose_headers=["Content-Type", "Authorization"],
    )

    conversation_store = store or ConversationStore(config_class)
    llm_service = llm or LLMService(config_class)
    rate_limiter = RateLimiter(
        limit=app.config.get("RATE_LIMIT_REQUESTS", 60),
        window=app.config.get("RATE_LIMIT_WINDOW_SECONDS", 60),
    )

    def get_client_ip():
        # Prefer X-Forwarded-For if behind a reverse proxy, falling back to remote_addr
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.remote_addr or "127.0.0.1"

    @app.after_request
    def set_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        return response

    @app.errorhandler(400)
    def bad_request(error):
        return jsonify(error=getattr(error, "description", "Bad Request")), 400

    @app.errorhandler(404)
    def not_found(_error):
        return jsonify(error="Resource not found."), 404

    @app.errorhandler(413)
    def request_too_large(_error):
        return jsonify(error="Request payload is too large. Max size is 512 KB."), 413

    @app.errorhandler(429)
    def rate_limit_exceeded(_error):
        return jsonify(error="Too many requests. Please slow down and try again shortly."), 429

    @app.errorhandler(500)
    def internal_server_error(_error):
        return jsonify(error="Internal server error. Please try again later."), 500

    @app.get("/api/health")
    def health():
        return jsonify(
            status="ok",
            database="connected" if conversation_store.health() else "in-memory",
            llm_configured=llm_service.configured,
            model=getattr(llm_service, "model", "default"),
        )

    @app.get("/api/conversations")
    def list_conversations():
        return jsonify(conversations=conversation_store.list())

    @app.post("/api/conversations")
    def create_conversation():
        client_ip = get_client_ip()
        if rate_limiter.is_limited(client_ip):
            return jsonify(error="Rate limit exceeded. Please wait a moment."), 429
        payload = request.get_json(silent=True) or {}
        title = payload.get("title", "New conversation")
        return jsonify(conversation=conversation_store.create(title=title)), 201

    @app.get("/api/conversations/<conversation_id>")
    def get_conversation(conversation_id):
        conversation = conversation_store.get(conversation_id)
        if not conversation:
            return jsonify(error="Conversation not found."), 404
        return jsonify(conversation=conversation)

    @app.delete("/api/conversations/<conversation_id>")
    def delete_conversation(conversation_id):
        if not conversation_store.delete(conversation_id):
            return jsonify(error="Conversation not found."), 404
        return jsonify(message="Conversation deleted.")

    @app.patch("/api/conversations/<conversation_id>")
    def update_conversation(conversation_id):
        payload = request.get_json(silent=True) or {}
        title = payload.get("title")
        if not isinstance(title, str) or not title.strip():
            return jsonify(error="A non-empty title string is required."), 400
        conversation = conversation_store.update_metadata(conversation_id, {"title": title.strip()})
        if not conversation:
            return jsonify(error="Conversation not found."), 404
        return jsonify(conversation=conversation)

    @app.post("/api/chat")
    def chat():
        client_ip = get_client_ip()
        if rate_limiter.is_limited(client_ip):
            return jsonify(error="Too many requests. Please wait a moment."), 429

        payload = request.get_json(silent=True)
        if payload is None:
            return jsonify(error="Invalid JSON request body."), 400

        message = payload.get("message")
        conversation_id = payload.get("conversation_id")
        attachment = payload.get("attachment")

        if not isinstance(message, str) or not message.strip():
            return jsonify(error="message must be a non-empty string."), 400
        if len(message) > app.config["MAX_MESSAGE_LENGTH"]:
            return jsonify(error=f"message must be {app.config['MAX_MESSAGE_LENGTH']} characters or fewer."), 400

        # Handle optional text attachment
        formatted_message = message.strip()
        if attachment and isinstance(attachment, dict):
            att_name = str(attachment.get("name", "attachment.txt")).strip()
            att_content = str(attachment.get("content", ""))
            if len(att_content.encode("utf-8")) > app.config.get("MAX_ATTACHMENT_SIZE_BYTES", 102400):
                return jsonify(error="Attachment exceeds maximum allowed size (100 KB)."), 400
            if att_content:
                formatted_message = f"{formatted_message}\n\n[Attached File: {att_name}]\n```\n{att_content}\n```"

        if conversation_id:
            conversation = conversation_store.get(conversation_id)
            if not conversation:
                return jsonify(error="Conversation not found."), 404
        else:
            conversation = conversation_store.create()
            conversation_id = conversation["_id"]

        timestamp = datetime.now(timezone.utc).isoformat()
        user_message = {"role": "user", "content": formatted_message, "created_at": timestamp}
        if attachment and isinstance(attachment, dict):
            user_message["attachment_name"] = str(attachment.get("name", "attachment.txt"))

        context = [item for item in conversation.get("messages", []) if item.get("role") in {"user", "assistant"}]
        context = (context + [user_message])[-app.config["MAX_CONTEXT_MESSAGES"]:]

        meta = {}
        try:
            gen_result = llm_service.generate(context)
            if isinstance(gen_result, tuple):
                response_text, meta = gen_result
            else:
                response_text = gen_result
        except RuntimeError as error:
            return jsonify(error=str(error)), 503
        except Exception:
            app.logger.exception("LLM generation failed")
            return jsonify(error="The AI service is temporarily unavailable. Please try again."), 502

        assistant_message = {
            "role": "assistant",
            "content": response_text,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "meta": meta,
        }

        # Auto-generate title for the first message
        title = None
        if not conversation.get("messages"):
            title = create_title_from_text(message.strip())

        updated = conversation_store.append_messages(
            conversation_id, [user_message, assistant_message], title=title
        )
        return jsonify(conversation=updated, message=assistant_message, meta=meta)

    @app.post("/api/chat/stream")
    def chat_stream():
        """SSE endpoint for streaming real-time AI responses."""
        client_ip = get_client_ip()
        if rate_limiter.is_limited(client_ip):
            return jsonify(error="Too many requests. Please wait a moment."), 429

        payload = request.get_json(silent=True)
        if payload is None:
            return jsonify(error="Invalid JSON request body."), 400

        message = payload.get("message")
        conversation_id = payload.get("conversation_id")
        attachment = payload.get("attachment")

        if not isinstance(message, str) or not message.strip():
            return jsonify(error="message must be a non-empty string."), 400
        if len(message) > app.config["MAX_MESSAGE_LENGTH"]:
            return jsonify(error=f"message must be {app.config['MAX_MESSAGE_LENGTH']} characters or fewer."), 400

        formatted_message = message.strip()
        if attachment and isinstance(attachment, dict):
            att_name = str(attachment.get("name", "attachment.txt")).strip()
            att_content = str(attachment.get("content", ""))
            if len(att_content.encode("utf-8")) > app.config.get("MAX_ATTACHMENT_SIZE_BYTES", 102400):
                return jsonify(error="Attachment exceeds maximum allowed size (100 KB)."), 400
            if att_content:
                formatted_message = f"{formatted_message}\n\n[Attached File: {att_name}]\n```\n{att_content}\n```"

        if conversation_id:
            conversation = conversation_store.get(conversation_id)
            if not conversation:
                return jsonify(error="Conversation not found."), 404
        else:
            conversation = conversation_store.create()
            conversation_id = conversation["_id"]

        timestamp = datetime.now(timezone.utc).isoformat()
        user_message = {"role": "user", "content": formatted_message, "created_at": timestamp}
        if attachment and isinstance(attachment, dict):
            user_message["attachment_name"] = str(attachment.get("name", "attachment.txt"))

        context = [item for item in conversation.get("messages", []) if item.get("role") in {"user", "assistant"}]
        context = (context + [user_message])[-app.config["MAX_CONTEXT_MESSAGES"]:]

        def event_stream():
            accumulated_chunks = []
            final_meta = {}
            try:
                if hasattr(llm_service, "generate_stream"):
                    for event in llm_service.generate_stream(context):
                        if event["type"] == "chunk":
                            accumulated_chunks.append(event["text"])
                            yield f"data: {json.dumps({'type': 'chunk', 'text': event['text']})}\n\n"
                        elif event["type"] == "done":
                            final_meta = event.get("meta", {})
                else:
                    gen_result = llm_service.generate(context)
                    text = gen_result[0] if isinstance(gen_result, tuple) else gen_result
                    accumulated_chunks.append(text)
                    yield f"data: {json.dumps({'type': 'chunk', 'text': text})}\n\n"

                full_text = "".join(accumulated_chunks)
                assistant_message = {
                    "role": "assistant",
                    "content": full_text,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "meta": final_meta,
                }
                title = None
                if not conversation.get("messages"):
                    title = create_title_from_text(message.strip())

                updated_conv = conversation_store.append_messages(
                    conversation_id, [user_message, assistant_message], title=title
                )
                yield f"data: {json.dumps({'type': 'done', 'conversation': updated_conv, 'message': assistant_message, 'meta': final_meta})}\n\n"

            except Exception as e:
                app.logger.exception("Streaming failed")
                yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"

        return Response(stream_with_context(event_stream()), mimetype="text/event-stream")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
