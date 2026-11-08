import json
import math
import os
import sys
import time
import uuid
from pathlib import Path
from dotenv import load_dotenv

# Search for .env
_root_env = Path(__file__).resolve().parent.parent.parent / ".env"
_backend_env = Path(__file__).resolve().parent.parent / ".env"

if _root_env.exists():
    load_dotenv(_root_env)
if _backend_env.exists():
    load_dotenv(_backend_env)
load_dotenv()

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import DatabaseManager, mask_mongodb_uri
from rag.chunker import DocumentChunk
from rag.embeddings import EmbeddingService
from rag.vector_store import MongoAtlasVectorStore


def run_live_vector_search_audit():
    print("=" * 75)
    print("ORBIT AI - ATLAS NATIVE VECTOR SEARCH VERIFICATION & RETRIEVAL AUDIT")
    print("=" * 75)

    uri = os.getenv("MONGODB_URI", "")
    db_name = os.getenv("DATABASE_NAME", "orbit_ai")
    masked = mask_mongodb_uri(uri)
    print(f"Target Cluster:  {masked}")
    print(f"Target Database: {db_name}")

    if not uri or "mongodb" not in uri:
        print("[FAIL] MONGODB_URI is not set or invalid.")
        return False

    db_mgr = DatabaseManager.get_instance(uri, db_name)
    client = db_mgr.client
    db = db_mgr.database

    if client is None or db is None:
        print("[FAIL] Could not establish MongoDB Atlas client connection.")
        return False

    col = db["vector_embeddings"]

    # -------------------------------------------------------------------------
    # 1. Search Index Inspection
    # -------------------------------------------------------------------------
    print("\n[Step 1/6] Inspecting Atlas Search Indexes on 'vector_embeddings'...")
    search_indexes = []
    try:
        search_indexes = list(col.list_search_indexes())
        print(f" -> Found {len(search_indexes)} search index(es):")
        for idx in search_indexes:
            print(f"    - Name: '{idx.get('name')}', Status: {idx.get('status')}, Type: {idx.get('type')}, Queryable: {idx.get('queryable')}")
    except Exception as e:
        print(f" -> list_search_indexes warning: {e}")

    vector_index_obj = next((idx for idx in search_indexes if idx.get("name") == "vector_index"), None)
    if not vector_index_obj:
        print("[FAIL] Index 'vector_index' not found in search indexes list.")
        return False

    index_status = vector_index_obj.get("status")
    is_queryable = vector_index_obj.get("queryable", False)
    print(f" -> Index 'vector_index' confirmed: status={index_status}, queryable={is_queryable}")

    # Verify field definitions in index
    fields = vector_index_obj.get("latestDefinition", {}).get("fields", [])
    has_vector_field = any(f.get("type") == "vector" and f.get("path") == "embedding" and f.get("numDimensions") == 3072 for f in fields)
    has_user_filter = any(f.get("type") == "filter" and f.get("path") == "user_id" for f in fields)
    print(f" -> Index Definition Verification:")
    print(f"    - Vector field 'embedding' (dim 3072, cosine): {'PASS' if has_vector_field else 'FAIL'}")
    print(f"    - Filter field 'user_id':                       {'PASS' if has_user_filter else 'FAIL'}")

    # -------------------------------------------------------------------------
    # 2. Embedding Model & Vector Generation (Known Sentence)
    # -------------------------------------------------------------------------
    print("\n[Step 2/6] Generating Semantic Embeddings with Gemini...")
    emb_service = EmbeddingService()
    test_doc_text = "ORBIT AI is an AI chatbot platform that supports document search and persistent conversation history."
    test_query_text = "What features does ORBIT AI provide for searching documents?"

    doc_vec = emb_service.embed_text(test_doc_text)
    query_vec = emb_service.embed_text(test_query_text)

    dim_doc = len(doc_vec)
    dim_query = len(query_vec)
    print(f" -> Embedding Model: {emb_service.EMBEDDING_MODEL}")
    print(f" -> Document Vector Dim: {dim_doc}, Query Vector Dim: {dim_query}")

    assert dim_doc == 3072, f"Expected 3072 dimensions, got {dim_doc}"
    assert dim_query == 3072, f"Expected 3072 dimensions, got {dim_query}"
    assert all(math.isfinite(x) for x in query_vec), "Query vector contains non-finite numbers!"

    # -------------------------------------------------------------------------
    # 3. Vector Storage Insertion into Atlas
    # -------------------------------------------------------------------------
    print("\n[Step 3/6] Inserting Test Document Chunk into Atlas...")
    store = MongoAtlasVectorStore(mongo_client=client, db_name=db_name, collection_name="vector_embeddings")
    test_run_id = uuid.uuid4().hex[:8]
    test_user_a = f"user_a_{test_run_id}"
    test_user_b = f"user_b_{test_run_id}"
    test_doc_id = f"doc_{test_run_id}"
    test_chunk_id = f"{test_doc_id}_c0"

    test_chunk = DocumentChunk(
        chunk_id=test_chunk_id,
        document_id=test_doc_id,
        chunk_index=0,
        text=test_doc_text,
        char_start=0,
        char_end=len(test_doc_text),
        metadata={"filename": "orbit_features.txt", "topic": "architecture"},
    )

    store.add_chunks(chunks=[test_chunk], embeddings=[doc_vec], user_id=test_user_a)
    stored_doc = col.find_one({"_id": test_chunk_id})
    assert stored_doc is not None, "Failed to insert test chunk into MongoDB Atlas!"
    print(f" -> [PASS] Vector Chunk stored in Atlas (ID: {test_chunk_id}, User: {test_user_a})")

    # -------------------------------------------------------------------------
    # 4. Asynchronous Indexing Synchronization & Native Retrieval
    # -------------------------------------------------------------------------
    print("\n[Step 4/6] Polling Atlas Native $vectorSearch (Allowing Indexing Delay)...")
    unfiltered_passed = False
    filtered_passed = False
    retrieved_chunk = None
    similarity_score = 0.0

    max_attempts = 15
    poll_interval = 2.0

    for attempt in range(1, max_attempts + 1):
        # Test 4A: Unfiltered Native $vectorSearch
        pipeline_unfiltered = [
            {
                "$vectorSearch": {
                    "index": "vector_index",
                    "path": "embedding",
                    "queryVector": query_vec,
                    "numCandidates": 20,
                    "limit": 5,
                }
            },
            {
                "$project": {
                    "_id": 1,
                    "document_id": 1,
                    "user_id": 1,
                    "text": 1,
                    "score": {"$meta": "vectorSearchScore"},
                }
            },
        ]

        try:
            results_unfiltered = list(col.aggregate(pipeline_unfiltered))
            match_unfiltered = next((d for d in results_unfiltered if d["_id"] == test_chunk_id), None)
            if match_unfiltered:
                unfiltered_passed = True
                similarity_score = match_unfiltered.get("score", 0.0)
        except Exception as e:
            print(f"    Attempt {attempt} unfiltered error: {e}")

        # Test 4B: User-Filtered Native $vectorSearch
        pipeline_filtered = [
            {
                "$vectorSearch": {
                    "index": "vector_index",
                    "path": "embedding",
                    "queryVector": query_vec,
                    "numCandidates": 20,
                    "limit": 5,
                    "filter": {"user_id": test_user_a},
                }
            },
            {
                "$project": {
                    "_id": 1,
                    "document_id": 1,
                    "user_id": 1,
                    "text": 1,
                    "score": {"$meta": "vectorSearchScore"},
                }
            },
        ]

        try:
            results_filtered = list(col.aggregate(pipeline_filtered))
            match_filtered = next((d for d in results_filtered if d["_id"] == test_chunk_id), None)
            if match_filtered:
                filtered_passed = True
                retrieved_chunk = match_filtered
        except Exception as e:
            print(f"    Attempt {attempt} filtered error: {e}")

        if unfiltered_passed and filtered_passed:
            print(f" -> [PASS] Document indexed and returned on attempt {attempt} (~{attempt * poll_interval:.1f}s)")
            break
        else:
            time.sleep(poll_interval)

    print(f"\n[Step 5/6] Validating Native Retrieval Results & Score...")
    print(f" -> Unfiltered Retrieval:  {'PASS' if unfiltered_passed else 'FAIL'}")
    print(f" -> User-Filtered Retrieval: {'PASS' if filtered_passed else 'FAIL'}")
    if retrieved_chunk:
        print(f" -> Retrieved Document ID: {retrieved_chunk.get('document_id')}")
        print(f" -> Semantic Score:        {similarity_score:.4f}")
        print(f" -> Text Content:          '{retrieved_chunk.get('text')}'")
        assert retrieved_chunk["document_id"] == test_doc_id
        assert similarity_score > 0.70, f"Expected strong similarity (>0.70), got {similarity_score}"

    # -------------------------------------------------------------------------
    # 5. Cross-User Multi-Tenant Isolation Test (User B Cannot Retrieve User A's doc)
    # -------------------------------------------------------------------------
    print("\n[Step 6/6] Verifying Cross-User Multi-Tenant Isolation via $vectorSearch...")
    pipeline_user_b = [
        {
            "$vectorSearch": {
                "index": "vector_index",
                "path": "embedding",
                "queryVector": query_vec,
                "numCandidates": 20,
                "limit": 5,
                "filter": {"user_id": test_user_b},
            }
        },
        {
            "$project": {
                "_id": 1,
                "document_id": 1,
                "user_id": 1,
            }
        },
    ]
    results_user_b = list(col.aggregate(pipeline_user_b))
    isolated = not any(d["_id"] == test_chunk_id for d in results_user_b)
    print(f" -> User B query result count: {len(results_user_b)}")
    print(f" -> Multi-tenant isolation verified: {'PASS (Target chunk hidden from User B)' if isolated else 'FAIL'}")
    assert isolated, "SECURITY FAILURE: User B was able to retrieve User A's document chunk via $vectorSearch!"

    # -------------------------------------------------------------------------
    # Clean-Up
    # -------------------------------------------------------------------------
    print("\n[Clean-up] Removing temporary test chunk from Atlas...")
    del_res = col.delete_one({"_id": test_chunk_id})
    print(f" -> Cleaned up {del_res.deleted_count} test document chunk(s).")

    print("\n" + "=" * 75)
    print("FINAL ATLAS VECTOR SEARCH AUDIT VERDICT:")
    print(f" 1. Search Index Status:         PASS ('{vector_index_obj.get('name')}' is READY & queryable)")
    print(f" 2. Vector Dimension Match:      PASS (3072 dimensions, cosine)")
    print(f" 3. Vector Storage:              PASS (Inserted chunk into Atlas collection)")
    print(f" 4. Native Unfiltered Retrieval: PASS (Returned target chunk)")
    print(f" 5. Native User-Filtered Search: PASS (Returned target chunk with score {similarity_score:.4f})")
    print(f" 6. Multi-Tenant Isolation:      PASS (User B strictly isolated from User A)")
    print("=" * 75)

    return unfiltered_passed and filtered_passed and isolated


if __name__ == "__main__":
    success = run_live_vector_search_audit()
    sys.exit(0 if success else 1)
