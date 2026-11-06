# Docker Deployment Guide

## 1. Container Architecture

ORBIT AI is containerized into a multi-tier service topology defined in `docker-compose.yml`:

```
+--------------------------------------------------------------+
|                        DOCKER NETWORK                        |
|                                                              |
|   +-------------------+              +-------------------+   |
|   |  orbit-frontend   |              |   orbit-backend   |   |
|   |  Nginx Alpine     |------------->|   Python 3.12     |   |
|   |  Port: 3000       |   Reverse    |   Gunicorn (WSGI) |   |
|   |                   |    Proxy     |   Port: 5000      |   |
|   +-------------------+              +-------------------+   |
|                                                |             |
|                                                v             |
|                                      +-------------------+   |
|                                      |  orbit-mongodb    |   |
|                                      |  Mongo 7.0 Engine |   |
|                                      |  Port: 27017      |   |
|                                      +-------------------+   |
+--------------------------------------------------------------+
```

---

## 2. Environment Configuration

Before running containers, create a `.env` file in the project root:

```env
# Gemini AI Credentials
GEMINI_API_KEY=your_google_gemini_api_key_here
GEMINI_MODEL=gemini-3.5-flash-lite

# Production Security
SECRET_KEY=change_this_to_a_random_32_character_secret_string

# Rate Limiting
RATE_LIMIT_REQUESTS=120
RATE_LIMIT_WINDOW_SECONDS=60
```

---

## 3. Starting the Containers

Build and start the complete application stack in detached mode:

```bash
docker compose up --build -d
```

Verify service status:

```bash
docker compose ps
```

Expected output:
```
NAME              IMAGE                     COMMAND                  SERVICE   STATUS              PORTS
orbit-mongodb     mongo:7.0                 "docker-entrypoint.s…"   mongodb   running (healthy)   0.0.0.0:27017->27017/tcp
orbit-backend     ai-chat-agent-backend     "gunicorn --bind 0.0…"   backend   running (healthy)   0.0.0.0:5000->5000/tcp
orbit-frontend    ai-chat-agent-frontend    "/docker-entrypoint.…"   frontend  running             0.0.0.0:3000->80/tcp
```

---

## 4. Persistent Storage Volumes

Docker Compose creates two named volumes:
- `mongo_data`: Persists MongoDB database files across container restarts.
- `backend_data`: Persists local user records, vector index embeddings, and user memories.

To inspect volumes:
```bash
docker volume ls
```

---

## 5. Container Maintenance & Troubleshooting

### Viewing Live Logs
```bash
# View backend logs
docker compose logs -f backend

# View frontend reverse proxy logs
docker compose logs -f frontend

# View MongoDB logs
docker compose logs -f mongodb
```

### Stopping & Restarting
```bash
# Stop containers gracefully
docker compose down

# Stop and purge volumes (caution: deletes persistent data)
docker compose down -v
```
