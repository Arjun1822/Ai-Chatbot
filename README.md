# Orbit AI Chat

A modern, production-ready full-stack AI chat application built with **Flask**, **React**, **MongoDB** (with in-memory fallback), and the **Google Gemini API** (`google-genai` SDK).

Orbit supports persistent conversations, real-time response streaming, clean Markdown formatting with syntax-highlighted code blocks, safe text/code file attachments, search, conversation renaming, one-click copy actions, light and dark themes, confirmation modals, rate limiting, and live service health monitoring.

---

## Architecture & Features

- **Backend**:
  - **Flask 3.1.0** application factory pattern with robust error handling and structured security headers.
  - **Google Gemini API** (`google-genai` SDK) with streaming support, exponential backoff retries, and token/latency telemetry.
  - **Dual Persistence**: MongoDB via PyMongo with thread-safe in-memory fallback and bounded capacity.
  - **Security & DoS Protection**: Sliding-window rate limiter with memory eviction, 512 KB request size limit, 8,000 character message length limit, and safe text attachment parsing (max 100 KB).
  - **CORS Support**: Whitelist supporting multiple frontend origins (e.g. `localhost:3000` and `localhost:5173`).
- **Frontend**:
  - **React 18** Single-Page Application with responsive desktop and mobile drawer navigation.
  - **Real-Time Streaming**: Live character-by-character response rendering via Server-Sent Events (SSE).
  - **Syntax Highlighting**: PrismJS code block wrapper with language badges and dedicated per-block copy buttons.
  - **File Attachments**: Attach `.txt`, `.py`, `.js`, `.json`, `.csv`, `.md`, or code files with size checking and preview chips.
  - **Conversation Management**: Create new chats, rename conversation titles, search chats, and delete conversations with confirmation modals.
  - **Themes & UI Polish**: Dark and light themes persisted to `localStorage`, animated thinking indicator, latency indicators, and live backend connection badge.

---

## Requirements

- **Python 3.10+** (Python 3.12 recommended)
- **Node.js 18+** (Node v22 recommended)
- **MongoDB** (Optional: automatically falls back to thread-safe in-memory storage)
- **Google Gemini API Key** (`GEMINI_API_KEY`)

---

## Quickstart Guide

### 1. Backend Setup

From the repository root:

```powershell
Set-Location backend

# Create virtual environment using your Python installation
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install dependencies
python -m pip install -r requirements.txt

# Configure environment variables
Copy-Item .env.example .env
# Edit .env and set your GEMINI_API_KEY (and optional MONGODB_URI)

# Start Flask API server (runs on http://localhost:5000)
python app.py
```

### 2. Frontend Setup

In a second terminal:

```powershell
Set-Location frontend

# Install dependencies
npm install

# Start React development server (runs on http://localhost:3000)
npm start
```

Open `http://localhost:3000` in your browser.

---

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/health` | Backend status, DB mode (`connected` or `in-memory`), and LLM readiness |
| `GET` | `/api/conversations` | List conversation threads (metadata only, sorted by `updated_at`) |
| `POST` | `/api/conversations` | Create a new conversation (`{ "title": "optional" }`) |
| `GET` | `/api/conversations/<id>` | Retrieve complete conversation messages |
| `PATCH` | `/api/conversations/<id>` | Rename conversation title (`{ "title": "New Title" }`) |
| `DELETE` | `/api/conversations/<id>` | Delete conversation and its messages |
| `POST` | `/api/chat` | Send message (`{ "conversation_id": "...", "message": "...", "attachment": {...} }`) |
| `POST` | `/api/chat/stream` | Server-Sent Events (SSE) streaming endpoint for live token generation |

---

## Automated Testing

### Backend Tests (Pytest)

The backend test suite covers endpoint validation, context persistence, streaming SSE responses, attachment size limits, rate limiting, conversation metadata updates, security headers, and LLM error handling.

```powershell
Set-Location backend
.\.venv\Scripts\Activate.ps1
python -m pytest backend/tests --cov=backend -o pythonpath=backend -v
```

### Frontend Tests (Jest & React Testing Library)

The frontend test suite validates branding, empty state suggestions, search filtering, dark/light theme switching, message history rendering, and the delete confirmation dialog.

```powershell
Set-Location frontend
$env:CI="true"; npm test -- --watchAll=false
```

---

## Security Documentation

Detailed security architecture, threat model analysis, vulnerability status matrix, and production hardening recommendations can be found in [SECURITY_AUDIT.md](file:///c:/Users/aduva/OneDrive/Desktop/AI%20CHAT%20AGENT/SECURITY_AUDIT.md).
