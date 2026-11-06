# Cloud Deployment Architecture Guide

## 1. Cloud Architecture Overview

For enterprise cloud environments, ORBIT AI can be deployed on serverless container infrastructure (such as **Google Cloud Run**, **AWS ECS Fargate**, or **Azure Container Apps**) combined with managed **MongoDB Atlas**.

```
[ User Traffic ]
       |
       v
[ Cloudflare / Cloud CDN / SSL Termination ]
       |
       +---> Frontend Static Assets (Cloud Storage / Cloudflare Pages / S3)
       |
       +---> API Gateway / Backend Container (Google Cloud Run / AWS ECS)
                 |
                 +---> Google Secret Manager (GEMINI_API_KEY, SECRET_KEY)
                 |
                 +---> Google Cloud Gemini API (google-genai SDK)
                 |
                 +---> MongoDB Atlas Cluster (M10+ with Atlas Vector Search)
```

---

## 2. Google Cloud Run Deployment

Google Cloud Run is recommended due to native co-location with Google Gemini infrastructure and low latency.

### Step 1: Build & Push Backend Image
```bash
# Set GCP Project
gcloud config set project your-gcp-project-id

# Build container image with Google Cloud Build
gcloud builds submit backend --tag gcr.io/your-gcp-project-id/orbit-backend:latest
```

### Step 2: Configure Secret Manager
```bash
# Store Gemini API Key securely
echo -n "your-gemini-api-key" | gcloud secrets create GEMINI_API_KEY --data-file=-
echo -n "your-random-secret-key" | gcloud secrets create ORBIT_SECRET_KEY --data-file=-
```

### Step 3: Deploy Backend Service
```bash
gcloud run deploy orbit-backend \
  --image gcr.io/your-gcp-project-id/orbit-backend:latest \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --min-instances 1 \
  --max-instances 10 \
  --memory 1Gi \
  --cpu 1 \
  --set-secrets GEMINI_API_KEY=GEMINI_API_KEY:latest,SECRET_KEY=ORBIT_SECRET_KEY:latest \
  --set-env-vars FLASK_ENV=production,FRONTEND_URL=https://chat.yourdomain.com,MONGODB_URI=mongodb+srv://user:pass@cluster.mongodb.net/orbit_db
```

### Step 4: Deploy Frontend
The frontend can be deployed to Cloud Run, Firebase Hosting, or Cloudflare Pages pointing to the Cloud Run backend URL.

---

## 3. MongoDB Atlas Vector Search Configuration

To leverage managed Atlas Vector Search:
1. Create a MongoDB Atlas cluster (M10 tier or higher).
2. In the Atlas UI, navigate to **Atlas Search** -> **Create Search Index** -> **JSON Editor**.
3. Target collection: `orbit_db.vector_embeddings`.
4. Index definition:
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
5. Name the index `vector_index`. The `MongoAtlasVectorStore` automatically queries this index via `$vectorSearch`.

---

## 4. Production Hardening Checklist

- [x] SSL/TLS termination with HTTP/2 and modern TLS 1.3 ciphers.
- [x] Secrets stored exclusively in Cloud Secret Manager (no plain-text in configs or Git).
- [x] CORS restricted to verified frontend domains.
- [x] Automatic container autoscaling with min-instance = 1 to eliminate cold starts.
- [x] In-flight DDoS protection via Cloud Armor or Cloudflare WAF.
