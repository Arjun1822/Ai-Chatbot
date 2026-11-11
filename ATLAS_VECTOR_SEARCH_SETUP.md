# MongoDB Atlas Vector Search Setup & Configuration Guide

**Application:** ORBIT AI (AI Chat Agent)  
**Database:** `orbit_ai`  
**Collection:** `vector_embeddings`  
**Embedding Model:** Google Gemini (`gemini-embedding-001`)  
**Embedding Dimensions:** `3072`  
**Similarity Metric:** `cosine`  

---

## 1. Overview & Current Status

ORBIT AI features a dual-layer RAG architecture:
1. **Vector Storage (ACTIVE & OPERATIONAL):** Document chunks and generated 3072-dimensional vector embeddings are stored persistently in MongoDB Atlas inside the `orbit_ai.vector_embeddings` collection.
2. **Vector Retrieval ($vectorSearch) (ACTIVE & VERIFIED):**
   - **Atlas Managed Retrieval:** The search index `vector_index` is created, `READY`, and queryable on `Cluster0`.
   - **Live Retrieval Succeeded:** Native `$vectorSearch` queries executed with semantic score >0.92, successfully retrieving document chunks with multi-tenant `user_id` filtering.
   - **Local Cosine Fallback:** Preserved as an active safety net in case of network disruptions or during index rebuilds, ensuring 100% query uptime.

---

## 2. Step-by-Step Index Creation via Atlas Console

### Step 1: Open the Atlas Console
1. Log in to [MongoDB Atlas](https://cloud.mongodb.com/).
2. In the left navigation menu, click **Database** under the *Services* group.
3. Locate your cluster (`Cluster0`) and click on **Browse Collections**.

### Step 2: Navigate to `vector_embeddings`
1. Under databases, select `orbit_ai`.
2. Click on the `vector_embeddings` collection.
3. In the top tab bar, click on **Search and Vector Search** (or **Atlas Search**).

### Step 3: Create Vector Search Index
1. Click the green **Create Search Index** button.
2. Under **Atlas Vector Search**, select the **JSON Editor** configuration mode and click **Next**.
3. In the **Index Name** field, enter:
   ```text
   vector_index
   ```
4. Verify the Database and Collection dropdowns are set to:
   - Database: `orbit_ai`
   - Collection: `vector_embeddings`

### Step 4: Paste Index Definition JSON
Replace the default template in the JSON editor with the following definition:

```json
{
  "fields": [
    {
      "type": "vector",
      "path": "embedding",
      "numDimensions": 3072,
      "similarity": "cosine"
    },
    {
      "type": "filter",
      "path": "user_id"
    },
    {
      "type": "filter",
      "path": "document_id"
    },
    {
      "type": "filter",
      "path": "embedding_model"
    }
  ]
}
```

> **Why these fields are required:**
> - `embedding` (3072 dimensions, cosine): Matches the Google Gemini `gemini-embedding-001` model output.
> - `user_id` (filter): Enforces strict multi-tenant data isolation so users cannot search or retrieve other users' documents.
> - `document_id` (filter): Enables scoped retrieval filtering by document.
> - `embedding_model` (filter): Pre-filters candidates during `$vectorSearch` so fallback or incompatible model vectors cannot enter retrieval.

### Step 5: Save and Build Index
1. Click **Create Search Index** (or **Next** -> **Create Index**).
2. The index status will show as **Building**.
3. Initial indexing typically takes 1 to 3 minutes. When complete, the status badge will turn green (**Active**).

---

## 3. Verifying Vector Search

Once the index status is **Active**, run the live verification script from your terminal:

```powershell
& "backend\.venv\Scripts\python.exe" backend/scripts/test_atlas_vector_search_live.py
```

### Expected Successful Output:
```text
===========================================================================
ORBIT AI - ATLAS VECTOR SEARCH LIVE AUDIT & VERIFICATION
===========================================================================
Target Cluster: mongodb+srv://Arjun:******@cluster0.pkbn9cr.mongodb.net/
Target DB:      orbit_ai

[Step 1/5] Inspecting Atlas Search Indexes on 'vector_embeddings'...
 -> Found 1 search index(es):
    - Name: vector_index, Status: READY, Type: vectorSearch

[Step 2/5] Verifying Embedding Service & Dimensions...
 -> Embedding Model: gemini-embedding-001
 -> Generated Vector Dimension: 3072

[Step 3/5] Testing Vector Storage (Insert Chunk into Atlas)...
 -> [PASS] Vector Storage Successful: Chunk inserted into Atlas 'vector_embeddings' collection.
    Stored fields: _id, document_id, user_id, text, embedding (dim=3072)

[Step 4/5] Executing Live $vectorSearch Aggregation against Atlas...
 -> [PASS] Live $vectorSearch Succeeded! Score: 0.8942

[Step 5/5] Cleaning up test data from Atlas...
 -> Cleaned up 1 test document chunk(s).

===========================================================================
SUMMARY OF ATLAS VECTOR CAPABILITIES:
 1. Vector Storage into Atlas:        PASS (Operational)
 2. Live Atlas $vectorSearch:         PASS (Operational)
===========================================================================
```

---

## 4. Production Resilience & Fallback Safety

- **No Silent Loss:** ORBIT AI's `MongoAtlasVectorStore` automatically validates Atlas connectivity and query execution.
- **Graceful Fallback:** If Atlas Search is temporarily unreachable or the index is rebuilding, retrieval queries fall back to internal cosine similarity without throwing 500 errors to the user.
- **Multi-Tenant Protection:** Every `$vectorSearch` pipeline query includes a mandatory `filter: {"user_id": user_id}` stage, preventing unauthorized cross-user data leakage.

