# ORBIT AI – Vercel & Render Cloud Production Deployment Guide

**Target Architecture:**
- **Frontend:** Vercel (Create React App SPA)
- **Backend:** Render (Docker Web Service with Gunicorn + Flask)
- **Database:** MongoDB Atlas (`Cluster0`)
- **AI Engine:** Google Gemini API (`gemini-3.5-flash-lite`, `gemini-embedding-001`)
- **Repository:** `https://github.com/Arjun1822/Ai-Chatbot`

---

## 1. Architecture & Production Overview

```
 [ Client Browser ]
        |
        | HTTPS (React SPA)
        v
  [ Vercel CDN ]  <--- (Frontend: Static SPA hosting with edge routing)
        |
        | HTTPS / CORS + SSE Streaming (Authorization: Bearer <JWT>)
        v
  [ Render Web Service ] <--- (Backend: Docker container running Gunicorn on $PORT)
        |
        +-----> [ Google Gemini API ] (gemini-3.5-flash-lite, gemini-embedding-001)
        |
        +-----> [ MongoDB Atlas Cluster0 ] (orbit_ai: users, convs, memories, vector_embeddings)
```

### Key Architectural Characteristics
1. **Stateless Backend:** The Flask/Gunicorn container retains zero critical state on Render's ephemeral filesystem.
2. **Persistent Cloud Storage:** User accounts, hashed credentials, conversations, memories, document chunks, and 3072-dimensional embeddings reside entirely in **MongoDB Atlas**.
3. **CORS & Multi-Origin Support:** Backend accepts the primary Vercel production domain, Vercel preview deployment URLs (`https://*.vercel.app`), and local development environments.
4. **Buffered Streaming Defense:** The SSE streaming response sets `X-Accel-Buffering: no` and `Cache-Control: no-cache, no-transform`, ensuring Render's proxy does not buffer tokens.
5. **Dynamic Port Binding:** Gunicorn binds dynamically to `0.0.0.0:${PORT:-5000}`, satisfying Render's runtime port contract while remaining compatible with local Docker Compose.

---

## 2. Pre-Deployment Checklist

Before deploying, ensure you have:
- [x] A MongoDB Atlas account with `Cluster0` active.
- [x] Atlas Database User created with readWrite permissions on `orbit_ai`.
- [x] Atlas Network Access configured: Add Render's outbound IP CIDR ranges for your chosen region, plus your local development workstation IP (never use `0.0.0.0/0`).
- [x] Atlas Vector Search Index `vector_index` created and in `READY` status on `orbit_ai.vector_embeddings`.
- [x] A Google Gemini API Key from Google AI Studio.
- [x] Accounts on [Render](https://render.com) and [Vercel](https://vercel.com) connected to your GitHub account (`Arjun1822`).

---

## 3. Step 1: Deploy Backend on Render (Docker Web Service)

### A. Create the Render Web Service
1. Log in to your [Render Dashboard](https://dashboard.render.com/).
2. Click **New +** -> **Web Service**.
3. Select **Build and deploy from a Git repository** -> Connect `Arjun1822/Ai-Chatbot`.
4. Configure the service settings (Directory & Docker Mapping):
   - **Repository Root:** `.` (top-level Git repo `Ai-Chatbot`)
   - **Render Root Directory:** `backend` (directs Render to watch and execute builds inside `backend/`)
   - **Runtime:** `Docker`
   - **Dockerfile Path:** `./Dockerfile` (relative to the Render Root Directory `backend`)
   - **Docker Build Context:** `.` (relative to the Render Root Directory `backend`)
   - **Instance Type:** `Free` (or `Starter` for production workloads with zero spin-down)

   *(Alternative Configuration if Render Root Directory is left empty/default)*:
   - **Render Root Directory:** *(empty)*
   - **Dockerfile Path:** `backend/Dockerfile`
   - **Docker Build Context:** `backend`

### B. Configure Health Check Path
In Render **Advanced Settings**:
- **Health Check Path:** `/api/health`

### C. Configure Render Environment Variables
Add the following environment variables in the Render Dashboard (**Environment** tab):

| Variable Name | Required | Example / Description |
|---|---|---|
| `FLASK_ENV` | Yes | `production` |
| `PORT` | Auto | Render injects this automatically (e.g. `10000`). Gunicorn binds to it. |
| `SECRET_KEY` | Yes | 64-character random hex string. Generate via: `python -c "import secrets; print(secrets.token_hex(32))"` |
| `MONGODB_URI` | Yes | `mongodb+srv://<db_user>:<db_password>@cluster0.pkbn9cr.mongodb.net/orbit_ai?retryWrites=true&w=majority` |
| `DATABASE_NAME` | Yes | `orbit_ai` |
| `GEMINI_API_KEY` | Yes | Your Google Gemini API Key |
| `GEMINI_MODEL` | Yes | `gemini-3.5-flash-lite` |
| `GEMINI_EMBEDDING_MODEL` | Optional | `gemini-embedding-001` (default) |
| `FRONTEND_URL` | Yes | `https://*.vercel.app,http://localhost:3000` *(Update with your exact Vercel URL once deployed)* |
| `RATE_LIMIT_REQUESTS` | Optional | `120` (requests per minute per IP) |
| `RATE_LIMIT_WINDOW_SECONDS` | Optional | `60` |
| `MAX_CONTEXT_MESSAGES` | Optional | `16` |
| `MAX_MESSAGE_LENGTH` | Optional | `8000` |

### D. Configure MongoDB Atlas Network Access (Render CIDRs & Development IP)
Never use `0.0.0.0/0` in production. Instead, configure exact CIDR ranges in MongoDB Atlas:

1. **Local Development IP:**
   - In MongoDB Atlas Console -> **Network Access** -> Click **Add IP Address**.
   - Click **Add Current IP Address** to whitelist your development workstation.
   - Enter Comment: `Dev-Workstation`.
2. **Render Outbound IP CIDRs:**
   - In Render Dashboard -> Your Web Service -> Check **Connect** / **Settings** for the assigned **Outbound IP Addresses**.
   - Or consult Render's regional outbound CIDR blocks for your selected region (e.g., Oregon US-West, Ohio US-East, Frankfurt EU):
     - In MongoDB Atlas -> **Network Access** -> Click **Add IP Address**.
     - Add each regional CIDR block published by Render for your deployment region (refer to [Render IP Addresses Documentation](https://render.com/docs/all-ip-addresses)).
     - Enter Comment: `Render-Outbound-<Region>`.
   - *Static IP Option:* On paid Render plans, you can attach a Dedicated Static Outbound IP and whitelist a single `/32` IP in Atlas.

### E. Deploy
Click **Create Web Service**. Render will pull the repo, build the Docker image, run the health check against `/api/health`, and publish your backend URL:
`https://orbit-ai-backend.onrender.com`

---

## 4. Step 2: Deploy Frontend on Vercel

### A. Import Project into Vercel
1. Log in to [Vercel](https://vercel.com/).
2. Click **Add New...** -> **Project**.
3. Import the `Arjun1822/Ai-Chatbot` repository.

### B. Configure Project Settings
- **Framework Preset:** `Create React App`
- **Root Directory:** Click **Edit** and select **`frontend`** *(CRITICAL: Must be set to `frontend`)*
- **Build Command:** `npm run build` (Default)
- **Output Directory:** `build` (Default)
- **Install Command:** `npm install` (Default)

### C. Configure Vercel Environment Variables
Add the following environment variable in the Vercel **Environment Variables** panel:

| Variable Name | Environment | Value |
|---|---|---|
| `REACT_APP_API_URL` | Production, Preview, Development | `https://<your-render-backend-name>.onrender.com/api` |

> **Note:** Do NOT include any database URIs or Gemini keys in Vercel. All AI generation and database calls are handled server-side by Render.

### D. Deploy
Click **Deploy**. Vercel will compile the React production bundle and deploy it globally to their edge CDN, giving you a production URL:
`https://orbit-ai.vercel.app` (or similar).

---

## 5. Step 3: Connect CORS on Render

Once your Vercel production URL is active:
1. Open Render Dashboard -> `orbit-ai-backend` -> **Environment**.
2. Update `FRONTEND_URL` with your actual Vercel domain and wildcard for preview branches:
   ```text
   FRONTEND_URL=https://orbit-ai.vercel.app,https://*.vercel.app,http://localhost:3000
   ```
3. Click **Save Changes**. Render will automatically redeploy with the updated CORS policy in seconds.

---

## 6. End-to-End Verification Steps

Perform this verification sequence after deployment:

### 1. Test Backend Health Endpoint
```bash
curl -X GET https://<your-render-backend>.onrender.com/api/health
```
**Expected Response (HTTP 200):**
```json
{
  "database": "connected",
  "database_name": "orbit_ai",
  "database_type": "atlas",
  "llm_configured": true,
  "model": "gemini-3.5-flash-lite",
  "status": "ok",
  "tools_registered": 3
}
```

### 2. Test Database Ping & Vector Search Health
```bash
curl -X GET https://<your-render-backend>.onrender.com/api/health/db
```
**Expected Response (HTTP 200):**
```json
{
  "connected": true,
  "database": "orbit_ai",
  "is_atlas": true,
  "latency_ms": 15,
  "status": "connected"
}
```

### 3. Test Full User Workflow on Vercel
1. Open `https://<your-app>.vercel.app` in your browser.
2. **Register:** Create a new user account.
3. **Login:** Verify successful login and token reception.
4. **Chat (Streaming):** Send a message (e.g., *"What is 12 * 12?"*) and verify streaming text chunks arrive smoothly with typewriter effect.
5. **Persistence:** Refresh the browser tab and confirm the conversation title and messages are restored from Atlas.
6. **RAG Document Upload:** Upload a `.txt` or `.pdf` document in Document Mode.
7. **Document Search:** Ask a question regarding the uploaded document and verify citation badges appear with source snippets.
8. **Logout:** Verify session termination and redirect.

---

## 7. Storage Architecture & Persistence Guarantees

| Data Category | Storage Mechanism | Location | Persistence Behavior |
|---|---|---|---|
| **User Accounts & Hashes** | MongoDB Collection `users` | MongoDB Atlas | Permanent (survives any deployment) |
| **Conversations & Messages** | MongoDB Collection `conversations` | MongoDB Atlas | Permanent |
| **User Memories** | MongoDB Collection `user_memories` | MongoDB Atlas | Permanent |
| **RAG Embeddings & Chunks** | MongoDB Collection `vector_embeddings` | MongoDB Atlas | Permanent |
| **Atlas Vector Search Index** | Hardware-accelerated Lucene index | MongoDB Atlas | Managed by Atlas |
| **Client Authentication** | Signed JWT Bearer token | Client `localStorage` | Valid for 7 days |
| **Render Web Service Filesystem** | Ephemeral Docker container layer | Render Cloud | Discarded on redeploy/restart |

> **Raw File Storage Note:** Uploaded documents (PDF, DOCX, TXT) are parsed in-memory during upload, split into semantic chunks, embedded via Gemini, and stored directly inside Atlas collection `vector_embeddings`. The raw original uploaded binary file is not required by the RAG engine. If your application later needs a "Download Original File" feature, integrate AWS S3, Cloudflare R2, or Google Cloud Storage.

---

## 8. Rollback & Disaster Recovery Procedures

### A. Rolling Back Render Backend
1. Open Render Dashboard -> `orbit-ai-backend`.
2. Navigate to the **Deploys** tab.
3. Locate the previous successful deploy.
4. Click the three dots `...` next to that deploy -> Select **Rollback to this deploy**.
5. Render immediately switches traffic back to the prior Docker image with zero downtime.

### B. Rolling Back Vercel Frontend
1. Open Vercel Dashboard -> your project.
2. Navigate to the **Deployments** tab.
3. Locate the previous stable deployment.
4. Click `...` -> Select **Promote to Production** (or **Rollback**).
5. Vercel routes traffic immediately to the selected immutable build.

### C. Database Disaster Recovery
1. MongoDB Atlas provides automatic continuous backups and point-in-time restores (PITR).
2. To restore: Atlas Console -> Databases -> `Cluster0` -> **Backup** tab -> Choose snapshot -> **Restore**.

---

## 9. Troubleshooting & FAQ

### Issue: "Network Error" or "Could not connect to backend" on Vercel
- **Cause:** `REACT_APP_API_URL` is missing, incorrect, or `FRONTEND_URL` on Render does not allow the Vercel domain.
- **Fix:** Verify `REACT_APP_API_URL=https://<your-render-backend>.onrender.com/api` on Vercel and trigger a redeploy (environment variables in React require a rebuild to take effect). Verify `FRONTEND_URL` in Render includes your Vercel URL.

### Issue: Streaming feels jerky or arrives in one big chunk
- **Cause:** Proxy buffering.
- **Fix:** Verified resolved in code via `X-Accel-Buffering: no` and `Cache-Control: no-cache, no-transform`.

### Issue: Render shows "Timed out waiting for port"
- **Cause:** Gunicorn did not bind to `$PORT`.
- **Fix:** Verified resolved in `backend/Dockerfile` via `gunicorn --bind 0.0.0.0:${PORT:-5000}`.

