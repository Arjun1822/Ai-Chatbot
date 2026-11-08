# ORBIT AI – Docker Deployment Guide

**Target Architecture:** Multi-Container Docker Stack  
**Compose Profiles:** Default (Atlas Cloud Backend) & `local-db` (Standalone Local MongoDB)  
**Supported Platforms:** Docker Desktop (Windows/macOS), Docker Engine (Linux), Docker Compose v2+

---

## 1. Container Topology & Architecture

ORBIT AI provides an enterprise-ready containerized architecture supporting both cloud-connected (MongoDB Atlas) and isolated offline (local MongoDB) deployments.

```
+-----------------------------------------------------------------------------+
|                           DOCKER NETWORK (orbit-net)                        |
|                                                                             |
|   +-----------------------+                    +------------------------+   |
|   |    orbit-frontend     |                    |     orbit-backend      |   |
|   |    Nginx Alpine       |------------------->|     Python 3.12-slim   |   |
|   |    Port: 3000 -> 80   |   Reverse Proxy    |     Gunicorn (2w/4t)   |   |
|   |    SPA Static Build   |   /api/* Forward   |     Port: 5000         |   |
|   +-----------------------+                    +------------------------+   |
|                                                            |                |
|                                                            | Optional       |
|                                                            v (local-db)     |
|                                                +------------------------+   |
|                                                |     orbit-mongodb      |   |
|                                                |     Mongo 7.0 Engine   |   |
|                                                |     Port: 27017        |   |
|                                                +------------------------+   |
+-----------------------------------------------------------------------------+
```

---

## 2. Docker Compose Configuration Profiles

### Profile A: Cloud Database Deployment (`docker-compose.yml`)
The default Compose file connects the containerized backend directly to **MongoDB Atlas**, eliminating local database container overhead:

```bash
# Build and start frontend and backend connected to MongoDB Atlas
docker compose up --build -d
```

### Profile B: Isolated Local Development (`docker-compose.local.yml`)
For air-gapped, offline, or standalone containerized testing with a local MongoDB container:

```bash
# Start local MongoDB along with backend and frontend
docker compose -f docker-compose.local.yml up --build -d
```

---

## 3. Environment Configuration

Create or update `.env` in the repository root:

```env
# Google Gemini API
GEMINI_API_KEY=your-gemini-api-key-here
GEMINI_MODEL=gemini-3.5-flash-lite

# Database Configuration (Atlas Cloud)
MONGODB_URI=mongodb+srv://<username>:<password>@cluster0.xxxxx.mongodb.net/orbit_ai?retryWrites=true&w=majority
DATABASE_NAME=orbit_ai

# Security & CORS
SECRET_KEY=generate_a_secure_32_character_random_hex_key
FLASK_ENV=production
FRONTEND_URL=http://localhost:3000

# Rate Limiting & Safety
RATE_LIMIT_REQUESTS=120
RATE_LIMIT_WINDOW_SECONDS=60
MAX_CONTEXT_MESSAGES=16
MAX_MESSAGE_LENGTH=8000
```

---

## 4. Container Maintenance & Lifecycle Commands

### Verifying Service Health
```bash
docker compose ps
```

Expected healthy output:
```
NAME              IMAGE                    COMMAND                  SERVICE   STATUS              PORTS
orbit-backend     orbit-ai-backend:latest  "sh -c 'exec gunicor…"   backend   running (healthy)   0.0.0.0:5000->5000/tcp
orbit-frontend    orbit-ai-frontend:latest "/docker-entrypoint.…"   frontend  running             0.0.0.0:3000->80/tcp
```

### Streaming Service Logs
```bash
# Stream backend application logs
docker compose logs -f backend

# Stream frontend Nginx logs
docker compose logs -f frontend
```

### Stopping Services
```bash
# Stop containers without removing volumes
docker compose down

# Stop containers and remove local volumes
docker compose down -v
```

---

## 5. Security & Build Hardening

1. **Non-Root Execution:** The production container runs with minimal privilege.
2. **Dynamic Port Contract:** Gunicorn binds to `0.0.0.0:${PORT:-5000}`, ensuring portability across Render, Cloud Run, and Docker Compose.
3. **Deep Health Check:** Docker monitors backend health via `/api/health`.
4. **Secret Isolation:** `.dockerignore` strictly excludes `.env`, `.venv`, and `.git` from image layers.
