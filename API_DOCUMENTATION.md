# ORBIT AI: REST & Streaming API Documentation

## 1. Authentication & Base URL

- **Base URL**: `/api`
- **Authentication**: JWT Bearer token passed in the `Authorization` header:
  ```http
  Authorization: Bearer <token>
  ```
- **Guest Fallback**: If no token is provided during local development, endpoints default to the guest user account (`local_user`).

---

## 2. API Endpoints

### 2.1 System & Health

#### `GET /api/health`
Returns system status, database connection, LLM readiness, and tool count.
```json
{
  "database": "connected",
  "llm_configured": true,
  "model": "gemini-3.5-flash-lite",
  "status": "ok",
  "tools_registered": 5
}
```

#### `GET /api/admin/metrics`
Returns platform observability telemetry.
```json
{
  "metrics": {
    "conversations_count": 12,
    "database_mode": "mongodb",
    "documents_count": 4,
    "memories_count": 7,
    "tools_available": ["calculator", "date_time", "weather", "web_search", "document_search"]
  }
}
```

---

### 2.2 Authentication

#### `POST /api/auth/register`
Create a new user account.
- **Request Body**:
  ```json
  {
    "email": "user@example.com",
    "password": "SecurePassword123!",
    "name": "Jane Doe"
  }
  ```
- **Response (201 Created)**:
  ```json
  {
    "token": "eyJhbGciOi...",
    "user": {
      "id": "usr_9981",
      "email": "user@example.com",
      "name": "Jane Doe"
    }
  }
  ```

#### `POST /api/auth/login`
Authenticate existing user.
- **Request Body**: `{"email": "...", "password": "..."}`
- **Response (200 OK)**: `{"token": "...", "user": {...}}`

#### `GET /api/auth/me`
Retrieve currently authenticated user profile.
- **Headers**: `Authorization: Bearer <token>`
- **Response (200 OK)**: `{"user": {"id": "...", "email": "...", "name": "..."}}`

---

### 2.3 Conversations

#### `GET /api/conversations`
List all conversations belonging to the requesting user.

#### `POST /api/conversations`
Create a new conversation.
- **Request Body**: `{"title": "New conversation"}`

#### `GET /api/conversations/<id>`
Retrieve a conversation with all message history.

#### `PATCH /api/conversations/<id>`
Update conversation title.
- **Request Body**: `{"title": "Updated Title"}`

#### `DELETE /api/conversations/<id>`
Permanently delete a conversation.

---

### 2.4 Chat & Streaming

#### `POST /api/chat` (Synchronous)
- **Request Body**:
  ```json
  {
    "conversation_id": "optional-id",
    "message": "What is 15 * 4?",
    "mode": "chat",
    "attachment": {"name": "app.py", "content": "..."}
  }
  ```

#### `POST /api/chat/stream` (Server-Sent Events)
Streams real-time character tokens, tool execution events, and citation metadata.
- **Request Body**:
  ```json
  {
    "conversation_id": "optional-id",
    "message": "Calculate (48 / 6) + (12 * 7)",
    "mode": "agent"
  }
  ```
- **Modes**:
  - `chat`: Direct conversational generation with user memory.
  - `agent`: Autonomous multi-step reasoning with tool calling.
  - `document`: Semantic RAG retrieval over uploaded knowledge base documents.
- **SSE Event Stream Format**:
  ```
  data: {"type": "tool_call", "tool_name": "calculator", "arguments": {"expression": "(48 / 6) + (12 * 7)"}}

  data: {"type": "tool_result", "tool_name": "calculator", "output": {"result": 92.0}, "success": true, "execution_time_ms": 11}

  data: {"type": "chunk", "text": "The calculated total is 92.0."}

  data: {"type": "done", "conversation": {...}, "message": {...}, "meta": {"mode": "agent", "latency_ms": 420}}
  ```

---

### 2.5 Knowledge Base (RAG)

#### `POST /api/documents`
Upload and index a document.
- **Multipart Form**: `file: <binary-file>` (PDF, DOCX, TXT, MD, Code)
- **Or JSON Body**: `{"filename": "spec.md", "content": "# Architecture..."}`
- **Response (201 Created)**:
  ```json
  {
    "document": {
      "document_id": "doc_8f1a23",
      "filename": "spec.md",
      "total_chunks": 4,
      "char_count": 1820
    }
  }
  ```

#### `GET /api/documents`
List all indexed documents for user.

#### `DELETE /api/documents/<document_id>`
Remove a document and its vector embeddings.

---

### 2.6 Persistent Memory

#### `GET /api/memories`
List memories. Query parameter: `?category=preference|fact|project|instruction`.

#### `POST /api/memories`
Save a new memory fact.
- **Request Body**:
  ```json
  {
    "content": "User prefers Python 3.12 dataclasses",
    "category": "preference",
    "importance": 4
  }
  ```

#### `PATCH /api/memories/<id>`
Update a stored memory item.

#### `DELETE /api/memories/<id>`
Delete a stored memory item.

---

## 3. Error Codes & Format

All error responses adhere to a standardized JSON schema:

```json
{
  "error": "Descriptive error message here."
}
```

| HTTP Code | Description | Typical Cause |
| :--- | :--- | :--- |
| `400 Bad Request` | Missing field, invalid format, or unsupported file. |
| `401 Unauthorized` | Invalid or expired JWT token. |
| `404 Not Found` | Target conversation, document, or memory does not exist or belongs to another user (IDOR guard). |
| `413 Payload Too Large` | Message exceeds limit or file upload exceeds 10 MB. |
| `429 Too Many Requests` | Request rate limit exceeded. |
| `502 Bad Gateway` | Upstream Gemini API unreachable. |
| `503 Service Unavailable` | LLM service unconfigured (missing `GEMINI_API_KEY`). |
