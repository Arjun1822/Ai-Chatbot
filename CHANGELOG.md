# Changelog & Transformation Log

All notable architectural enhancements, security upgrades, and functional features implemented in the transformation of **ORBIT AI** are documented below.

---

## [2.0.0] - Advanced AI Agent Platform Release

### 1. Agent Orchestration Core
- Added `backend/agent/schemas.py` defining standard schemas for `AgentMode`, `ToolDefinition`, `ToolParameter`, `ToolCall`, `ToolResult`, and `AgentStep`.
- Implemented `ToolRegistry` (`backend/agent/tool_registry.py`) providing discovery, Gemini `FunctionDeclaration` translation, and default tool initialization.
- Built `SafeMathEvaluator` performing pure Python Abstract Syntax Tree (`ast`) evaluation with compute magnitude bounds, completely eliminating `eval()` and `exec()`.
- Implemented `ToolExecutionManager` (`backend/agent/execution.py`) enforcing strict parameter schema validation, per-tool execution timeouts (5.0s), consecutive identical loop detection, and structured audit telemetry.
- Built `AgentOrchestrator` (`backend/agent/orchestrator.py`) supporting 3 operational modes (`chat`, `agent`, `document`), coordinating multi-step reasoning loops up to 5 steps, streaming SSE events, and formatting citations.

### 2. Retrieval-Augmented Generation (RAG) System
- Installed and configured `pypdf`, `python-docx`, and `numpy` in `backend/requirements.txt`.
- Created `DocumentExtractor` (`backend/rag/extractor.py`) supporting PDF, DOCX, TXT, Markdown, and code files with a 10 MB upload ceiling.
- Created `TextChunker` (`backend/rag/chunker.py`) with 500-character windows, 100-character overlap, and sentence/paragraph boundary detection.
- Built `EmbeddingService` (`backend/rag/embeddings.py`) integrating Google GenAI `text-embedding-004` with deterministic L2-normalized dense fallback for offline and unit test environments.
- Implemented `LocalVectorStore` and `MongoAtlasVectorStore` interface (`backend/rag/vector_store.py`) providing cosine similarity top-$k$ retrieval and user-level multi-tenant isolation.
- Created `RAGService` (`backend/rag/rag_service.py`) coordinating ingestion, chunking, embedding, vector search, and citation generation.

### 3. Persistent AI Memory
- Created `MemoryItem` schema (`backend/memory/models.py`) with priority levels and categories (`preference`, `fact`, `project`, `instruction`).
- Built `MemoryStore` (`backend/memory/memory_store.py`) supporting thread-safe local JSON disk persistence and MongoDB `user_memories` collection.
- Built `MemoryManager` (`backend/memory/memory_manager.py`) with pattern-based proactive preference extraction, priority-weighted retrieval, and formatted system prompt injection.

### 4. Authentication, Security, & Multi-Tenancy
- Created `UserStore` (`backend/services/user_store.py`) with PBKDF2-HMAC-SHA256 password hashing (100,000 iterations, 32-byte salt).
- Created `AuthService` (`backend/services/auth_service.py`) generating URL-safe signed JWT tokens with tamper detection and timestamp validation.
- Updated `ConversationStore` (`backend/services/conversation_store.py`) with reentrant lock `RLock` and `user_id` query isolation to eliminate IDOR vulnerabilities.
- Added user authentication endpoints (`/api/auth/register`, `/api/auth/login`, `/api/auth/me`, `/api/auth/logout`) with fallback guest mode for local development.

### 5. Frontend UI/UX Enhancements
- Built **Agent Mode Selector** (`chat`, `agent`, `document`) above the composer.
- Built `ToolActivityCard` component displaying live and persisted tool executions with expandable input/output inspection and timing telemetry.
- Built `CitationPill` component displaying source filenames, relevance scores, and popover chunk inspection.
- Built `KnowledgeBaseModal` allowing PDF, DOCX, and TXT upload, indexing, and deletion.
- Built `MemoryModal` allowing user-managed preference viewing, adding, and deleting.
- Built `AuthModal` for registration, login, and profile switching.
- Built `MetricsModal` displaying real-time platform observability stats.
- Added comprehensive CSS styling in `frontend/src/styles.css` for all new components.

### 6. Automated Testing & Verification
- Total backend test count increased from 21 to **44 tests** (100% pass rate).
- Added 40-prompt AI benchmark dataset (`backend/tests/test_agent_evaluation.py`) across 12 distinct functional categories.
- Total frontend test count increased from 11 to **14 tests** (100% pass rate).
- Verified production frontend build (`npm run build`).

### 7. DevOps & CI/CD
- Created production `backend/Dockerfile` using Gunicorn WSGI.
- Created multi-stage `frontend/Dockerfile` using Node 22 build and Nginx Alpine.
- Created `docker-compose.yml` orchestrating MongoDB, Backend, and Frontend.
- Created GitHub Actions CI/CD workflow (`.github/workflows/ci.yml`).
- Created complete documentation suite (12 Markdown documents).

