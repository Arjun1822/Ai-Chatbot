# Orbit AI Chat - Security Audit & Threat Modeling Report

**Date:** 2026-11-06  
**Auditor:** Senior Security Auditor & QA Engineer (Antigravity)  
**Scope:** AI Chat Application (Backend Flask API, React Frontend, Data Storage, AI Inference)  
**Status:** COMPLETED & MITIGATIONS APPLIED  

---

## 1. Executive Security Summary

A comprehensive security review was performed on the **Orbit AI Chat** application to identify potential vulnerabilities across authentication, API security, AI model safety, database queries, cross-site scripting (XSS), rate limiting, sensitive data exposure, and file upload safety.

All discovered critical and high-severity risks have been remediated in the codebase. Standard defense-in-depth principles—including strict origin verification, sliding-window rate limiting with memory cleanup, request body size limits, safe markdown link schemes, and HTTP security headers—have been integrated and validated.

---

## 2. Threat Vector Analysis & Implemented Mitigations

### 2.1 API Key Exposure & Secret Management
- **Risk Identified:** API keys or database connection strings could be committed to version control or leaked to client browsers.
- **Audit Finding:**
  - `backend/.env` is tracked by `.gitignore` (`*.env` rule).
  - Server-side only: Gemini API keys and MongoDB credentials are exclusively loaded in the Flask backend via `config.py` and are never serialized or sent in any API responses.
  - The health check endpoint (`/api/health`) reports only a boolean `llm_configured` flag and the public model name; it never exposes the key or connection string.
- **Remediation & Best Practice:**
  - A standardized `.env.example` file is provided for both backend and frontend with sanitized placeholders.
  - Production deployments should source `GEMINI_API_KEY` from managed secret stores (e.g., Google Secret Manager, AWS Secrets Manager, or container environment injections).

---

### 2.2 Cross-Site Scripting (XSS) & Content Injection
- **Risk Identified:** Rendering AI-generated Markdown or user messages might allow malicious `<script>` tags, event handlers (`onload`, `onerror`), or `javascript:` URI schemes to execute in the victim's browser.
- **Audit Finding:**
  - The application uses `react-markdown` without `rehype-raw`, meaning arbitrary raw HTML tags in user messages or AI responses are treated as literal text and not injected into the DOM.
  - React's JSX engine automatically escapes all interpolated strings.
- **Remediation Applied:**
  - Implemented `SafeLink` component in `App.jsx`:
    ```javascript
    function SafeLink({ href, children, ...props }) {
      const isSafe = /^https?:\/\//i.test(href || '') || (href || '').startsWith('/');
      if (!isSafe) {
        return <span>{children}</span>;
      }
      return <a href={href} target="_blank" rel="noopener noreferrer" {...props}>{children}</a>;
    }
    ```
  - This blocks `javascript:`, `data:text/html`, and `vbscript:` URI links inside Markdown output while guaranteeing `rel="noopener noreferrer"` to eliminate reverse tabnabbing attacks.

---

### 2.3 Injection Defenses (SQL / NoSQL Injection)
- **Risk Identified:** Manipulating user IDs or query parameters to inject MongoDB query operators (e.g. `{"$gt": ""}`).
- **Audit Finding:**
  - PyMongo queries use parameter dictionary lookups with explicit string keys (`{"_id": conversation_id}`).
  - `conversation_id` is generated as a UUIDv4 string on the server.
  - `update_metadata` strictly validates that payload fields match whitelisted keys (`title`) and enforces `isinstance(val, str)`.
- **Verdict:** Immune to standard NoSQL injection patterns.

---

### 2.4 Denial of Service (DoS) & Resource Exhaustion
- **Risk Identified:** Excessive or oversized payloads crashing the server or exhausting in-memory dictionary limits / MongoDB connections.
- **Audit Finding & Remediations Applied:**
  1. **Sliding-Window Rate Limiting:**
     - Implemented `RateLimiter` class in `app.py` with thread locks.
     - Enforces a default limit of 60 requests per minute per client IP address across all write endpoints (`/api/chat`, `/api/chat/stream`, `/api/conversations`).
     - **Memory Eviction:** Added an automatic prune cycle that clears stale client entries older than the window, preventing memory exhaustion under distributed access.
  2. **Bounded In-Memory Fallback:**
     - `ConversationStore` caps in-memory storage to 1,000 conversations using FIFO/timestamp eviction, preventing Out-Of-Memory (OOM) faults.
  3. **Strict Size Controls:**
     - Flask `MAX_CONTENT_LENGTH` configured to `512 KB`.
     - Individual messages bounded by `MAX_MESSAGE_LENGTH` (8,000 characters).
     - Attachments bounded by `MAX_ATTACHMENT_SIZE_BYTES` (100 KB).
  4. **Bounded AI Context Window:**
     - Chat history fed to the AI is capped at `MAX_CONTEXT_MESSAGES` (default 16 messages), eliminating prompt expansion attacks and token exhaustion.

---

### 2.5 File Upload & Attachment Security
- **Risk Identified:** Users uploading malicious binaries, executables, or excessively large files that could lead to remote code execution (RCE) or denial of service.
- **Audit Finding & Remediations Applied:**
  - Files are handled purely as text attachments in memory:
    - **No Server-Side File Writes:** Attached files are never written to disk or executed as scripts.
    - **Strict Whitelist & Size Enforcement:**
      - Frontend restricts file selection to text/code extensions (`.txt`, `.md`, `.py`, `.js`, `.json`, `.csv`, `.sql`, etc.).
      - File size is checked client-side (max 100 KB) and strictly re-validated on the backend (`MAX_ATTACHMENT_SIZE_BYTES`).
    - **Content Sanitization:** Text is decoded as UTF-8, wrapped in Markdown code blocks, and passed as non-executable context to the language model.

---

### 2.6 CORS & Network Security
- **Risk Identified:** Permissive CORS origins (`*`) permitting unauthorized web applications to access conversations.
- **Remediations Applied:**
  - Replaced single hardcoded origin with support for multiple validated frontend origins via `FRONTEND_URLS` in `config.py` (e.g. `http://localhost:3000`, `http://localhost:5173`).
  - Added HTTP Security Headers via Flask `after_request` middleware:
    - `X-Content-Type-Options: nosniff`: Prevents MIME-type sniffing.
    - `X-Frame-Options: DENY`: Defends against clickjacking.
    - `Referrer-Policy: strict-origin-when-cross-origin`: Minimizes referrer leakage.
    - `Permissions-Policy: geolocation=(), microphone=(), camera=()`: Restricts browser API capabilities.

---

### 2.7 AI Prompt Injection & Safety Guardrails
- **Risk Identified:** Malicious user messages attempting to bypass system instructions or alter assistant behavior.
- **Remediations Applied:**
  - Google GenAI `GenerateContentConfig` uses dedicated `system_instruction` parameter, isolating persona and behavioral instructions from conversation turns.
  - User and model turns are strictly encapsulated within `types.Content(role="user"|"model")` structures, preventing users from spoofing assistant messages in conversation turns.
  - Temperature set to `0.7` with structured system instructions defining clear boundaries.

---

## 3. Vulnerability Status Matrix

| Vulnerability Category | Risk Level | Status | Implemented Solution |
|---|---|---|---|
| **API Secret Leakage** | Critical | Resolved | Credentials kept exclusively server-side in `.env`, ignored in git. |
| **XSS via Markdown Links** | High | Resolved | `SafeLink` validator blocks `javascript:`/`data:` URIs and enforces `noopener`. |
| **Denial of Service (Memory Leak)** | Medium | Resolved | `RateLimiter` sliding window with periodic pruning of stale IP entries. |
| **Missing HTTP Security Headers** | Medium | Resolved | Added `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`. |
| **Accidental Data Loss (Deletions)** | Medium | Resolved | Modal confirmation gate added to UI before conversation deletion. |
| **Unbounded Payload Size** | Medium | Resolved | Explicit limits on payload (512 KB), message length (8,000), attachment (100 KB). |
| **CORS Origin Mismatch** | Medium | Resolved | Support for multi-origin whitelist (`FRONTEND_URLS`) covering ports 3000 and 5173. |
| **File Upload Exploits** | Medium | Resolved | Memory-only text parsing, size validation, no server-side disk writes. |
| **Unchecked Null Reference Crash** | Low | Resolved | Defensive fallback `(item?.title || '').toLowerCase()` in search filter. |

---

## 4. Production Hardening Checklist

When deploying to a public production environment:
1. **Set `FLASK_SECRET_KEY`**: Generate a strong 64-character random key (`python -c "import secrets; print(secrets.token_hex(32))"`).
2. **Reverse Proxy Configuration**:
   - Run Flask behind a production WSGI/ASGI server (e.g. `gunicorn -w 4 -b 0.0.0.0:5000 app:app`) fronted by Nginx or Cloudflare.
   - Configure `X-Forwarded-For` proxy fix (`from werkzeug.middleware.proxy_fix import ProxyFix`) to ensure accurate client IP rate limiting.
3. **Database Credentials**:
   - Utilize a secured MongoDB Atlas cluster with TLS/SSL enabled and IP access control.
4. **HTTPS / TLS**:
   - Enforce HTTPS across all traffic and enable `Strict-Transport-Security: max-age=31536000; includeSubDomains`.

