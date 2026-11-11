import base64
from collections import defaultdict
from datetime import datetime, timezone
import json
import logging
import os
from threading import Lock
from time import monotonic
import uuid

from flask import Flask, Response, g, jsonify, request, stream_with_context
from flask_cors import CORS

from agent.orchestrator import AgentOrchestrator
from config import Config
from database import DatabaseManager
from memory.memory_manager import MemoryManager
from rag.rag_service import RAGService
from rag.vector_store import MongoAtlasVectorStore
from services.auth_service import auth_service, get_current_user_from_request, require_auth, require_admin
from services.conversation_store import ConversationStore
from services.llm_service import LLMService
from services.user_store import UserStore

logger = logging.getLogger(__name__)


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


def create_app(config_class=Config, store=None, llm=None, user_st=None, rag_svc=None, mem_mgr=None):
    app = Flask(__name__)
    app.config.from_object(config_class)
    app.config["MAX_CONTENT_LENGTH"] = getattr(config_class, "MAX_CONTENT_LENGTH", 512 * 1024)

    if hasattr(config_class, "get_allowed_origins"):
        allowed_origins = config_class.get_allowed_origins()
    else:
        allowed_origins = getattr(config_class, "FRONTEND_URLS", [app.config.get("FRONTEND_URL", "http://localhost:3000")])
    CORS(
        app,
        resources={
            r"/api/*": {
                "origins": allowed_origins,
                "methods": ["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
                "allow_headers": ["Content-Type", "Authorization", "X-Requested-With", "Accept", "X-Guest-Token", "X-Auth-Token"],
                "expose_headers": ["Content-Type", "Authorization", "X-Guest-Token"],
            }
        },
        supports_credentials=False,
    )

    data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    os.makedirs(data_dir, exist_ok=True)

    # Centralized MongoDB / Atlas connection
    mongodb_uri = getattr(config_class, "MONGODB_URI", "")
    database_name = getattr(config_class, "DATABASE_NAME", "orbit_ai")
    flask_env = getattr(config_class, "FLASK_ENV", "development")
    db_manager = DatabaseManager.get_instance(uri=mongodb_uri, db_name=database_name)
    db_client = db_manager.client

    # Validate startup configuration
    if hasattr(config_class, "validate_configuration"):
        config_class.validate_configuration()

    # Production Failure Safety: Never silently fall back to volatile storage in production
    allow_fallback = os.getenv("ALLOW_EPHEMERAL_STORAGE", "false").lower() == "true"
    if flask_env == "production" and not allow_fallback:
        secret_key = app.config.get("SECRET_KEY", "")
        if not secret_key or secret_key == "dev-only-change-me" or len(secret_key) < 32:
            raise RuntimeError(
                "CRITICAL: Insecure, default, or weak SECRET_KEY detected in production. "
                "Set a secure, random 32+ character SECRET_KEY environment variable to protect JWT tokens."
            )
        if not mongodb_uri:
            raise RuntimeError(
                "CRITICAL: MONGODB_URI is not configured in production environment. "
                "Halting startup to prevent data loss. Supply a valid MongoDB Atlas connection string."
            )
        if not db_manager.is_connected:
            raise RuntimeError(
                f"CRITICAL: Production startup failed to connect to MongoDB cluster ({db_manager.masked_uri}). "
                f"Reason: {db_manager._last_error}. Halting startup to prevent silent fallback to volatile storage."
            )

    conversation_store = store or ConversationStore(config_class, mongo_client=db_client, db_name=database_name)
    llm_service = llm or LLMService(config_class)
    user_store = user_st or UserStore(
        persistence_path=os.path.join(data_dir, "users.json"),
        mongo_client=db_client,
        db_name=database_name,
    )
    auth_service.set_user_store(user_store)
    vector_store = (
        MongoAtlasVectorStore(mongo_client=db_client, db_name=database_name)
        if db_client is not None
        else None
    )
    rag_service = rag_svc or RAGService(vector_store=vector_store, data_dir=data_dir)
    memory_manager = mem_mgr or MemoryManager(
        data_dir=data_dir,
        mongo_client=db_client,
        db_name=database_name,
    )

    orchestrator = AgentOrchestrator(
        llm_service=llm_service,
        rag_service=rag_service,
        memory_manager=memory_manager,
    )

    rate_limiter = RateLimiter(
        limit=app.config.get("RATE_LIMIT_REQUESTS", 60),
        window=app.config.get("RATE_LIMIT_WINDOW_SECONDS", 60),
    )

    def get_client_ip():
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.remote_addr or "127.0.0.1"

    def get_user_id():
        user = get_current_user_from_request()
        if not user:
            return None
        return user.get("id")

    @app.before_request
    def validate_auth_header():
        auth_header = request.headers.get("Authorization", "")
        if auth_header and not auth_header.startswith("Bearer "):
            return jsonify(error="Invalid Authorization header format. Must be Bearer <token>"), 401
        token = None
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()
        elif "X-Auth-Token" in request.headers:
            token = request.headers["X-Auth-Token"].strip()
        elif "X-Guest-Token" in request.headers:
            token = request.headers["X-Guest-Token"].strip()

        if token is not None:
            user = auth_service.verify_token(token)
            if not user:
                return jsonify(error="Invalid or expired token."), 401

    @app.after_request
    def set_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        new_guest_token = getattr(g, "new_guest_token", None)
        if new_guest_token:
            response.headers["X-Guest-Token"] = new_guest_token
        return response

    @app.errorhandler(400)
    def bad_request(error):
        return jsonify(error=getattr(error, "description", "Bad Request")), 400

    @app.errorhandler(401)
    def unauthorized(_error):
        return jsonify(error="Unauthorized. Please authenticate."), 401

    @app.errorhandler(404)
    def not_found(_error):
        return jsonify(error="Resource not found."), 404

    @app.errorhandler(413)
    def request_too_large(_error):
        return jsonify(error="Request payload is too large. Max size is 10 MB."), 413

    @app.errorhandler(429)
    def rate_limit_exceeded(_error):
        return jsonify(error="Too many requests. Please slow down and try again shortly."), 429

    @app.errorhandler(500)
    def internal_server_error(_error):
        return jsonify(error="Internal server error. Please try again later."), 500

    # =========================================================================
    # HEALTH & OBSERVABILITY
    # =========================================================================
    @app.get("/api/health")
    def health():
        db_ping = db_manager.ping()
        db_connected = db_ping.get("connected", False)
        return jsonify(
            status="ok",
            database="connected" if db_connected else ("unconfigured" if db_ping.get("status") == "unconfigured" else "in-memory"),
            database_type="atlas" if db_ping.get("is_atlas") else ("mongodb" if db_connected else "in-memory"),
            database_name=database_name,
            llm_configured=llm_service.configured,
            model=getattr(llm_service, "model", "default"),
            tools_registered=len(orchestrator.tool_registry.list_tools()),
        )

    @app.get("/api/health/db")
    def health_db():
        """Dedicated database diagnostics endpoint."""
        ping_res = db_manager.ping()
        status_code = 200 if ping_res.get("connected") or ping_res.get("status") == "unconfigured" else 503
        return jsonify(ping_res), status_code

    @app.get("/api/admin/metrics")
    @require_admin()
    def get_metrics():
        uid = get_user_id()
        return jsonify(
            metrics={
                "conversations_count": len(conversation_store.list(all_users=True)),
                "documents_count": len(rag_service.list_documents(all_users=True)),
                "memories_count": len(memory_manager.get_user_memories(user_id=uid)) if uid else 0,
                "database_mode": "mongodb" if conversation_store.using_mongodb else "in-memory",
                "tools_available": [t.name for t in orchestrator.tool_registry.list_tools()],
            }
        )

    # =========================================================================
    # AUTHENTICATION
    # =========================================================================
    @app.route("/api/auth/guest-session", methods=["GET", "POST"])
    def get_or_create_guest_session():
        user = get_current_user_from_request()
        if not user:
            return jsonify(error="Failed to initialize session."), 500
        token = getattr(g, "new_guest_token", None) or auth_service.generate_guest_token(guest_id=user["id"])
        return jsonify(
            guest_id=user["id"],
            token=token,
            is_guest=bool(user.get("is_guest", True)),
        ), 200

    @app.post("/api/auth/register")
    def register():
        payload = request.get_json(silent=True) or {}
        email = payload.get("email")
        password = payload.get("password")
        name = payload.get("name")

        if not email or not password:
            return jsonify(error="Email and password are required."), 400

        try:
            # Public registration strictly forces role="user"; client input cannot escalate role
            user = user_store.create_user(email=email, password=password, name=name, role="user")
            token = auth_service.generate_token(user)
            return jsonify(user=user, token=token), 201
        except ValueError as e:
            return jsonify(error=str(e)), 400

    @app.post("/api/auth/login")
    def login():
        payload = request.get_json(silent=True) or {}
        email = payload.get("email")
        password = payload.get("password")

        if not email or not password:
            return jsonify(error="Email and password are required."), 400

        user = user_store.authenticate(email=email, password=password)
        if not user:
            return jsonify(error="Invalid email or password."), 401

        token = auth_service.generate_token(user)
        return jsonify(user=user, token=token), 200

    @app.get("/api/auth/me")
    @require_auth(strict=True)
    def get_me():
        uid = g.current_user.get("id")
        live_user = user_store.get_by_id(uid) if uid else None
        return jsonify(user=live_user or g.current_user)

    @app.post("/api/auth/logout")
    def logout():
        return jsonify(message="Logged out successfully.")

    # =========================================================================
    # CONVERSATIONS
    # =========================================================================
    @app.get("/api/conversations")
    def list_conversations():
        uid = get_user_id()
        if not uid:
            return jsonify(conversations=[])
        return jsonify(conversations=conversation_store.list(user_id=uid))

    @app.post("/api/conversations")
    def create_conversation():
        client_ip = get_client_ip()
        if rate_limiter.is_limited(client_ip):
            return jsonify(error="Rate limit exceeded. Please wait a moment."), 429
        payload = request.get_json(silent=True) or {}
        title = payload.get("title", "New conversation")
        uid = get_user_id()
        if not uid:
            return jsonify(error="Authentication required or invalid session."), 401
        return jsonify(conversation=conversation_store.create(title=title, user_id=uid)), 201

    @app.get("/api/conversations/<conversation_id>")
    def get_conversation(conversation_id):
        uid = get_user_id()
        if not uid:
            return jsonify(error="Conversation not found."), 404
        conversation = conversation_store.get(conversation_id, user_id=uid)
        if not conversation:
            return jsonify(error="Conversation not found."), 404
        return jsonify(conversation=conversation)

    @app.delete("/api/conversations/<conversation_id>")
    def delete_conversation(conversation_id):
        uid = get_user_id()
        if not uid or not conversation_store.delete(conversation_id, user_id=uid):
            return jsonify(error="Conversation not found."), 404
        return jsonify(message="Conversation deleted.")

    @app.patch("/api/conversations/<conversation_id>")
    def update_conversation(conversation_id):
        payload = request.get_json(silent=True) or {}
        title = payload.get("title")
        if not isinstance(title, str) or not title.strip():
            return jsonify(error="A non-empty title string is required."), 400
        uid = get_user_id()
        if not uid:
            return jsonify(error="Conversation not found."), 404
        conversation = conversation_store.update_metadata(
            conversation_id, {"title": title.strip()}, user_id=uid
        )
        if not conversation:
            return jsonify(error="Conversation not found."), 404
        return jsonify(conversation=conversation)

    # =========================================================================
    # RAG DOCUMENTS
    # =========================================================================
    @app.post("/api/documents")
    def upload_document():
        client_ip = get_client_ip()
        if rate_limiter.is_limited(client_ip):
            return jsonify(error="Rate limit exceeded. Please wait a moment."), 429

        auth_header = request.headers.get("Authorization", "")
        if auth_header:
            if not auth_header.startswith("Bearer "):
                return jsonify(error="Invalid Authorization header format. Must be Bearer <token>"), 401
            user = get_current_user_from_request()
            if not user:
                return jsonify(error="Invalid or expired token."), 401

        uid = get_user_id()

        uploaded = None
        if request.files:
            uploaded = (
                request.files.get("file")
                or request.files.get("document")
                or next(iter(request.files.values()), None)
            )

        file_bytes = None
        filename = None

        if uploaded is not None:
            if not uploaded.filename:
                return jsonify(error="No file selected."), 400
            file_bytes = uploaded.read()
            filename = uploaded.filename
        else:
            payload = request.get_json(silent=True) or {}
            filename = payload.get("filename") or request.form.get("filename")
            content = payload.get("content") or request.form.get("content")
            if not filename or content is None:
                return jsonify(error="File or filename and content is required."), 400
            if isinstance(content, str):
                file_bytes = content.encode("utf-8")
            elif isinstance(content, bytes):
                file_bytes = content
            else:
                return jsonify(error="Invalid document content payload."), 400

        if not file_bytes:
            return jsonify(error="File is empty (0 bytes)."), 400

        if not uid:
            return jsonify(error="Authentication required or invalid session."), 401

        try:
            doc_record = rag_service.ingest_document(filename=filename, file_bytes=file_bytes, user_id=uid)
            return jsonify(document=doc_record), 201
        except Exception as e:
            logger.error(f"Document ingestion failed: {e}")
            return jsonify(error=f"Document ingestion failed: {str(e)}"), 400

    @app.get("/api/documents")
    def list_documents():
        uid = get_user_id()
        if not uid:
            return jsonify(documents=[])
        docs = rag_service.list_documents(user_id=uid)
        return jsonify(documents=docs)

    @app.delete("/api/documents/<document_id>")
    def delete_document(document_id):
        uid = get_user_id()
        if not uid:
            return jsonify(error="Authentication required or invalid session."), 401
        deleted = rag_service.delete_document(document_id, user_id=uid)
        if not deleted:
            return jsonify(error="Document not found or could not be deleted."), 404
        return jsonify(message="Document deleted successfully.", deleted_chunks=deleted)

    # =========================================================================
    # PERSISTENT USER MEMORIES
    # =========================================================================
    @app.get("/api/memories")
    def list_memories():
        uid = get_user_id()
        if not uid:
            return jsonify(memories=[])
        cat = request.args.get("category")
        memories = memory_manager.get_user_memories(user_id=uid, category=cat)
        return jsonify(memories=[m.to_dict() for m in memories])

    @app.post("/api/memories")
    def create_memory():
        payload = request.get_json(silent=True) or {}
        content = payload.get("content")
        category = payload.get("category", "fact")
        importance = payload.get("importance", 3)

        if not content or not isinstance(content, str) or not content.strip():
            return jsonify(error="Content must be a non-empty string."), 400

        uid = get_user_id()
        if not uid:
            return jsonify(error="Authentication required or invalid session."), 401
        item = memory_manager.add_memory(user_id=uid, category=category, content=content, importance=importance)
        return jsonify(memory=item.to_dict()), 201

    @app.patch("/api/memories/<memory_id>")
    def update_memory(memory_id):
        payload = request.get_json(silent=True) or {}
        uid = get_user_id()
        if not uid:
            return jsonify(error="Memory not found."), 404
        updated = memory_manager.update_memory(
            memory_id=memory_id,
            user_id=uid,
            content=payload.get("content"),
            category=payload.get("category"),
            importance=payload.get("importance"),
        )
        if not updated:
            return jsonify(error="Memory not found."), 404
        return jsonify(memory=updated.to_dict())

    @app.delete("/api/memories/<memory_id>")
    def delete_memory(memory_id):
        uid = get_user_id()
        if not uid:
            return jsonify(error="Memory not found."), 404
        deleted = memory_manager.delete_memory(memory_id=memory_id, user_id=uid)
        if not deleted:
            return jsonify(error="Memory not found."), 404
        return jsonify(message="Memory deleted.")

    # =========================================================================
    # CHAT (SYNC & STREAMING)
    # =========================================================================
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
        mode = payload.get("mode", "chat")
        uid = get_user_id()
        if not uid:
            return jsonify(error="Authentication required or invalid session."), 401

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
            conversation = conversation_store.get(conversation_id, user_id=uid)
            if not conversation:
                return jsonify(error="Conversation not found."), 404
        else:
            conversation = conversation_store.create(user_id=uid)
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

        title = None
        if not conversation.get("messages"):
            title = create_title_from_text(message.strip())

        updated = conversation_store.append_messages(
            conversation_id, [user_message, assistant_message], title=title, user_id=uid
        )
        return jsonify(conversation=updated, message=assistant_message, meta=meta)

    @app.post("/api/chat/stream")
    def chat_stream():
        """SSE endpoint for streaming real-time AI responses with agent & document modes."""
        client_ip = get_client_ip()
        if rate_limiter.is_limited(client_ip):
            return jsonify(error="Too many requests. Please wait a moment."), 429

        payload = request.get_json(silent=True)
        if payload is None:
            return jsonify(error="Invalid JSON request body."), 400

        message = payload.get("message")
        conversation_id = payload.get("conversation_id")
        attachment = payload.get("attachment")
        mode = payload.get("mode", "chat")
        uid = get_user_id()
        if not uid:
            return jsonify(error="Authentication required or invalid session."), 401

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
            conversation = conversation_store.get(conversation_id, user_id=uid)
            if not conversation:
                return jsonify(error="Conversation not found."), 404
        else:
            conversation = conversation_store.create(user_id=uid)
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
            tool_calls_history = []
            citations = []
            try:
                # If agent mode or document mode requested, use orchestrator
                if mode in ("agent", "document"):
                    for evt in orchestrator.execute_stream(
                        context, mode=mode, user_id=uid, conversation_id=conversation_id
                    ):
                        evt_type = evt.get("type")
                        if evt_type == "chunk":
                            chunk_text = evt.get("content", "")
                            accumulated_chunks.append(chunk_text)
                            yield f"data: {json.dumps({'type': 'chunk', 'text': chunk_text, 'content': chunk_text})}\n\n"
                        elif evt_type in ("tool_call", "tool_result"):
                            if evt_type == "tool_call":
                                tool_calls_history.append(evt)
                            yield f"data: {json.dumps(evt)}\n\n"
                        elif evt_type == "done":
                            final_meta = {
                                "mode": mode,
                                "steps_taken": evt.get("steps_taken", 1),
                                "latency_ms": evt.get("latency_ms", 0),
                                "usage": evt.get("usage", {}),
                            }
                            citations = evt.get("citations", [])
                        elif evt_type == "error":
                            yield f"data: {json.dumps(evt)}\n\n"
                            return
                # Default/Chat mode: preserve compatibility with llm_service.generate_stream
                elif hasattr(llm_service, "generate_stream"):
                    for event in llm_service.generate_stream(context):
                        if event["type"] == "chunk":
                            accumulated_chunks.append(event["text"])
                            yield f"data: {json.dumps({'type': 'chunk', 'text': event['text'], 'content': event['text']})}\n\n"
                        elif event["type"] == "done":
                            final_meta = event.get("meta", {})
                else:
                    gen_result = llm_service.generate(context)
                    text = gen_result[0] if isinstance(gen_result, tuple) else gen_result
                    accumulated_chunks.append(text)
                    yield f"data: {json.dumps({'type': 'chunk', 'text': text, 'content': text})}\n\n"

                full_text = "".join(accumulated_chunks)
                assistant_message = {
                    "role": "assistant",
                    "content": full_text,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "meta": final_meta,
                    "tool_calls": tool_calls_history,
                    "citations": citations,
                }
                title = None
                if not conversation.get("messages"):
                    title = create_title_from_text(message.strip())

                updated_conv = conversation_store.append_messages(
                    conversation_id, [user_message, assistant_message], title=title, user_id=uid
                )
                yield f"data: {json.dumps({'type': 'done', 'conversation': updated_conv, 'message': assistant_message, 'meta': final_meta, 'citations': citations})}\n\n"

            except Exception as e:
                app.logger.exception("Streaming failed")
                yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"

        response = Response(stream_with_context(event_stream()), mimetype="text/event-stream")
        response.headers["Cache-Control"] = "no-cache, no-transform"
        response.headers["X-Accel-Buffering"] = "no"
        response.headers["Connection"] = "keep-alive"
        return response

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
