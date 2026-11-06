# ORBIT AI: Advanced AI Agent Platform

ORBIT AI is an enterprise-grade, full-stack autonomous AI agent and conversational platform built with **Python Flask**, **React 18**, **Google Gemini GenAI SDK**, **RAG Vector Knowledge Ingestion**, and **Multi-Tenant Memory Management**.

ORBIT transforms standard conversational LLMs into an autonomous multi-step reasoning platform capable of executing verified tools (Safe AST Calculator, Time/Date calculations, Live Weather, Web Search, and Document RAG Vector Search), maintaining persistent multi-tier user memory, and enforcing defense-in-depth security.

---

## Key System Capabilities

- **Autonomous Agent Orchestration**:
  - Multi-step reasoning loops with maximum execution thresholds (default 5 steps).
  - Loop detection preventing infinite repetitive tool invocations.
  - Per-tool execution timeouts (5.0s default) and comprehensive argument validation.
  - Non-blocking Server-Sent Events (SSE) streaming delivering real-time tokens, tool calls, and tool outputs.
- **Secure Sandboxed Tool Calling**:
  - **Safe Calculator**: Pure AST-based mathematical evaluation without `eval()` or `exec()`.
  - **Date & Time**: Real-time UTC/ISO timestamps, calendar offsets, and day-of-week evaluations.
  - **Open-Meteo Weather**: Geocoding and real-time atmospheric weather forecast retrieval.
  - **Live Web Search**: DuckDuckGo API integration for real-time external knowledge retrieval.
  - **Document Search (RAG)**: Dense vector similarity retrieval over user-uploaded knowledge assets.
- **RAG Knowledge Base & Retrieval**:
  - Supports PDF (`pypdf`), DOCX (`python-docx`), Markdown, Text, and source code files.
  - Recursive boundary-preserving text chunker with configurable chunk size (500 chars) and overlap (100 chars).
  - Dense vector embeddings via Google GenAI (`text-embedding-004`) with deterministic offline L2-normalized fallback.
  - Exact source attribution and citation chips rendered in assistant responses.
- **Multi-Tier AI Memory**:
  - Short-term conversation context, episodic summaries, and persistent user preferences.
  - Rule-based proactive preference extraction from conversation prompts.
  - User-scoped memory inspection, creation, filtering, and deletion APIs.
- **Multi-Tenancy & Security**:
  - PBKDF2-HMAC-SHA256 password hashing with random 32-byte salt and 100,000 iterations.
  - Signed JWT session tokens with tamper protection and expiration validation.
  - IDOR ownership validation on all conversations, documents, and memory assets.
  - Dual persistence: MongoDB with seamless thread-safe in-memory/JSON disk fallback.
  - Sliding-window DoS rate limiter with automatic stale key memory eviction.
- **Observability & DevOps**:
  - Telemetry endpoint `/api/admin/metrics` tracking conversations, documents, memories, and active tools.
  - Multi-stage `frontend/Dockerfile` (Nginx Alpine) and production `backend/Dockerfile` (Python 3.12 + Gunicorn).
  - `docker-compose.yml` orchestrating MongoDB, Backend, and Frontend.
  - Automated CI/CD pipeline via GitHub Actions (`.github/workflows/ci.yml`).

---

## Architecture Overview

```
User Browser (React 18 SPA)
       |
       |  HTTP REST / SSE Stream (JWT Auth)
       v
Flask API Server (Application Factory)
       |
       +---> Auth & Multi-Tenancy (UserStore, PBKDF2, JWT)
       |
       +---> Sliding-Window Rate Limiter (Memory-bounded)
       |
       +---> Agent Orchestrator
                |
                +---> Memory Manager (Preferences, Facts, Projects)
                |
                +---> RAG Knowledge Base (VectorStore, Chunking, Citations)
                |
                +---> Tool Registry & Execution Manager (AST Calc, Weather, Web, Time)
                |
                +---> Gemini LLM Service (google-genai SDK, Retries, Streaming)
```

---

## Quickstart

### Prerequisites
- **Python 3.10+** (Python 3.12 recommended)
- **Node.js 18+** (Node v22 recommended)
- **MongoDB** (Optional: automatically falls back to thread-safe local JSON storage)
- **Google Gemini API Key** (`GEMINI_API_KEY`)

### 1. Backend Setup

```bash
cd backend

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .\.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt

# Run backend development server
python app.py
```
Backend runs on `http://localhost:5000`.

### 2. Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Start development server
npm start
```
Frontend runs on `http://localhost:3000`.

### 3. Docker Deployment

```bash
docker compose up --build -d
```
Access the application at `http://localhost:3000`.

---

## Running Test Suites

### Backend Unit Tests & AI Benchmark (44 Tests)
```bash
backend/.venv/bin/pytest backend/tests/ -v -o pythonpath=backend
```

### Frontend Unit & Component Tests (14 Tests)
```bash
npm --prefix frontend test -- --watchAll=false
```

### Production Build
```bash
npm --prefix frontend run build
```

---

## Documentation Roadmap

- [Architecture Specification](ADVANCED_AGENT_ARCHITECTURE.md)
- [RAG Knowledge Base Guide](RAG_DOCUMENTATION.md)
- [Persistent AI Memory System](MEMORY_SYSTEM.md)
- [Secure Tool Calling Specification](TOOL_CALLING_GUIDE.md)
- [Security & Penetration Guide](SECURITY_GUIDE.md)
- [Docker Deployment Guide](DOCKER_DEPLOYMENT.md)
- [Cloud Deployment Architecture](CLOUD_DEPLOYMENT.md)
- [API Reference Documentation](API_DOCUMENTATION.md)
- [Verification & Test Suite Report](ADVANCED_AGENT_TEST_REPORT.md)
- [Production Readiness Audit](PRODUCTION_READINESS_REPORT.md)
- [Platform Changelog](CHANGELOG.md)
