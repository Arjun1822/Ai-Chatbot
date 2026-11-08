# MongoDB Atlas Cloud Setup & Migration Guide

## 1. Overview
This guide provides step-by-step instructions for connecting **ORBIT AI** to your **MongoDB Atlas** cloud cluster (`Cluster0`) for secure, scalable cloud deployment.

---

## 2. Prerequisites & Atlas Configuration

### Step 1: Database User & Role
1. Log in to your [MongoDB Atlas Console](https://cloud.mongodb.com/).
2. In the left navigation, click **Database Access** (under Security).
3. Ensure a database user exists (e.g. `orbit_admin`).
4. Set the **Built-in Role** to `readWriteAnyDatabase` or restrict it to `orbit_ai` (`Read and write to any collection in orbit_ai`).
5. Choose **Password Authentication** and record the password securely.

### Step 2: Network Access (IP Whitelist)
1. In the left navigation, click **Network Access**.
2. Click **Add IP Address**.
3. For local workstation testing: Click **Add Current IP Address**.
   > *Security Note: Do not configure `0.0.0.0/0`. When deploying to cloud hosts such as Render, add Render's specific regional outbound IP CIDR ranges or assign a dedicated static outbound IP.*
4. Wait for the status indicator to become active (Green).

### Step 3: Retrieve Connection String
1. In the left navigation, click **Database** / **Clusters**.
2. On your cluster (`Cluster0`), click **Connect**.
3. Choose **Drivers** (Python / 3.12 or later).
4. Copy the connection string format:
   ```
   mongodb+srv://<username>:<password>@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority
   ```
5. Specify the target database name `orbit_ai`:
   ```
   mongodb+srv://<username>:<password>@cluster0.xxxxx.mongodb.net/orbit_ai?retryWrites=true&w=majority
   ```

---

## 3. Environment Configuration

### Local Workstation & Docker Compose
Edit the root `.env` file (or `backend/.env`):
```env
# Google Gemini API
GEMINI_API_KEY=your-gemini-api-key
GEMINI_MODEL=gemini-3.5-flash-lite

# MongoDB Atlas
MONGODB_URI=mongodb+srv://<username>:<password>@cluster0.xxxxx.mongodb.net/orbit_ai?retryWrites=true&w=majority
DATABASE_NAME=orbit_ai

# Security & App Config
SECRET_KEY=your-secure-random-32-char-secret-key
FLASK_ENV=production
FRONTEND_URL=http://localhost:3000
RATE_LIMIT_REQUESTS=120
RATE_LIMIT_WINDOW_SECONDS=60
```

> [!IMPORTANT]
> Never commit `.env` or `backend/.env` to Git. Both files are strictly ignored by `.gitignore`.

---

## 4. Testing Your MongoDB Atlas Connection

A dedicated connectivity test script is bundled with ORBIT AI:

```bash
# Run against MONGODB_URI configured in .env:
python backend/scripts/test_atlas_connection.py

# Or pass the URI directly:
python backend/scripts/test_atlas_connection.py "mongodb+srv://user:pass@cluster0.xxxxx.mongodb.net/orbit_ai"
```

The script performs:
1. Scheme validation (`mongodb+srv://`).
2. DNS SRV resolution via `dnspython`.
3. Cluster ping command (`admin.command('ping')`) with latency measurement.
4. Temporary test document write/read/delete on `orbit_ai._atlas_connectivity_test`.
5. Automatic credential masking in all output.

---

## 5. Docker Compose Deployment

### Production Mode (MongoDB Atlas)
When using Atlas, the local MongoDB container is not required:
```bash
docker-compose up --build -d
```
Docker Compose launches:
- `orbit-backend`: Flask / Gunicorn container communicating with MongoDB Atlas over TLS.
- `orbit-frontend`: Production Nginx container serving React static build.

### Optional Local Development Mode (Local MongoDB Container)
To run a local MongoDB container instead of Atlas:
```bash
docker-compose --profile local-db up -d
# or use the dedicated local compose file:
docker-compose -f docker-compose.local.yml up -d
```

---

## 6. Atlas Vector Search Configuration (RAG)

To enable Atlas Vector Search for semantic document retrieval:
1. In the Atlas Console, navigate to **Atlas Search** -> **Create Search Index**.
2. Select **JSON Editor** and target:
   - Database: `orbit_ai`
   - Collection: `vector_embeddings`
3. Enter index definition:
```json
{
  "mappings": {
    "dynamic": true,
    "fields": {
      "embedding": {
        "dimensions": 768,
        "similarity": "cosine",
        "type": "knnVector"
      },
      "user_id": {
        "type": "token"
      }
    }
  }
}
```
4. Name the index `vector_index`.
5. Click **Create Search Index**.

---

## 7. Troubleshooting Common Errors

| Error | Root Cause | Solution |
| :--- | :--- | :--- |
| `ServerSelectionTimeoutError` | IP access list not configured or ISP firewall blocking port 27017 | Add current IP or cloud provider's outbound IP CIDR in Atlas Network Access. |
| `ConfigurationError` (`dnspython`) | Missing DNS SRV resolution library | Ensure `dnspython>=2.6.0` is installed (included in `requirements.txt`). |
| `OperationFailure: Authentication failed` | Incorrect database username or password | Recheck credentials in Atlas Database Access. If password contains special characters (`@`, `:`, `/`), URL-encode them. |
| `WinError 10013` / Permission Denied | Host security software blocking socket | Run command outside sandbox or whitelist Python binary in local firewall. |

