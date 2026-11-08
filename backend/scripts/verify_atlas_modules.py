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

from config import Config
from database import DatabaseManager, mask_mongodb_uri
from services.user_store import UserStore
from services.conversation_store import ConversationStore
from memory.memory_store import MemoryStore
from rag.vector_store import MongoAtlasVectorStore
from rag.chunker import DocumentChunk


def run_atlas_module_verification():
    print("=" * 70)
    print("ORBIT AI - LIVE MONGODB ATLAS MODULE VERIFICATION")
    print("=" * 70)

    db_mgr = DatabaseManager(uri=Config.MONGODB_URI, db_name=Config.DATABASE_NAME)
    print(f"Target Cluster: {db_mgr.masked_uri}")
    print(f"Target Database: {db_mgr.db_name}")

    ping_res = db_mgr.ping()
    if not ping_res.get("connected"):
        print(f"[FAIL] Cluster is not reachable: {ping_res.get('error')}")
        return False
    print(f"[PASS] MongoDB Atlas Ping OK ({ping_res.get('latency_ms')}ms)")

    client = db_mgr.client
    db = db_mgr.database
    test_id = uuid.uuid4().hex[:8]

    # 1. User Store Verification
    print("\n--- 1. User Registration & Authentication (Atlas collection: 'users') ---")
    user_store = UserStore(mongo_client=client, db_name=Config.DATABASE_NAME)
    test_email = f"atlas_test_{test_id}@orbit.local"
    test_pwd = f"AtlasSecure_{test_id}!99"

    user = user_store.create_user(email=test_email, password=test_pwd, name="Atlas Test User")
    assert user["email"] == test_email
    print(f"[PASS] User created with ID: {user['id']}")

    # Verify directly in MongoDB collection
    doc_in_mongo = db["users"].find_one({"email": test_email})
    assert doc_in_mongo is not None
    assert doc_in_mongo["_id"] == user["id"]
    print(f"[PASS] User document physically verified in Atlas 'users' collection.")

    auth_user = user_store.authenticate(email=test_email, password=test_pwd)
    assert auth_user is not None
    assert auth_user["id"] == user["id"]
    print(f"[PASS] Authentication succeeded against Atlas PBKDF2 hash.")

    # 2. Conversation Store Verification
    print("\n--- 2. Conversations & History (Atlas collection: 'conversations') ---")
    conv_store = ConversationStore(Config, mongo_client=client, db_name=Config.DATABASE_NAME)
    conv = conv_store.create(title=f"Atlas Test Conversation {test_id}", user_id=user["id"])
    assert conv is not None
    conv_id = conv["_id"]
    print(f"[PASS] Conversation created: {conv_id}")

    # Append messages
    msg1 = {"role": "user", "content": "Hello Atlas from ORBIT AI!"}
    msg2 = {"role": "model", "content": "Hello! I am connected to MongoDB Atlas."}
    updated_conv = conv_store.append_messages(conv_id, [msg1, msg2], user_id=user["id"])
    assert len(updated_conv["messages"]) == 2

    # Verify directly in MongoDB collection
    conv_in_mongo = db["conversations"].find_one({"_id": conv_id})
    assert conv_in_mongo is not None
    assert len(conv_in_mongo["messages"]) == 2
    print(f"[PASS] Conversation and 2 messages physically verified in Atlas 'conversations' collection.")

    # 3. Memory Store Verification
    print("\n--- 3. Persistent Memory (Atlas collection: 'user_memories') ---")
    mem_store = MemoryStore(mongo_client=client, db_name=Config.DATABASE_NAME)
    mem_item = mem_store.add(
        user_id=user["id"],
        category="preference",
        content=f"User prefers MongoDB Atlas M10+ clusters (test {test_id})",
        importance=4,
    )
    assert mem_item is not None
    print(f"[PASS] Memory saved: {mem_item.id}")

    # Verify directly in MongoDB collection
    mem_in_mongo = db["user_memories"].find_one({"_id": mem_item.id})
    assert mem_in_mongo is not None
    assert mem_in_mongo["user_id"] == user["id"]
    print(f"[PASS] Memory document physically verified in Atlas 'user_memories' collection.")

    # 4. RAG Vector & Document Metadata Store Verification
    print("\n--- 4. RAG Document & Vector Storage (Atlas collection: 'vector_embeddings') ---")
    vec_store = MongoAtlasVectorStore(mongo_client=client, db_name=Config.DATABASE_NAME)
    test_chunk = DocumentChunk(
        chunk_id=f"chunk_{test_id}",
        document_id=f"doc_{test_id}",
        chunk_index=0,
        text=f"ORBIT AI is an enterprise AI Agent platform running on MongoDB Atlas test {test_id}.",
        char_start=0,
        char_end=85,
        metadata={"filename": f"spec_{test_id}.pdf", "created_at": "2026-11-07T00:00:00Z"},
    )
    dummy_embedding = [0.05] * 768
    vec_store.add_chunks([test_chunk], [dummy_embedding], user_id=user["id"])

    # Verify directly in MongoDB collection
    vec_in_mongo = db["vector_embeddings"].find_one({"_id": test_chunk.chunk_id})
    assert vec_in_mongo is not None
    assert vec_in_mongo["user_id"] == user["id"]
    print(f"[PASS] Vector chunk physically verified in Atlas 'vector_embeddings' collection.")

    docs = vec_store.list_documents(user_id=user["id"])
    assert any(d["document_id"] == f"doc_{test_id}" for d in docs)
    print(f"[PASS] Document metadata aggregation verified from Atlas collections.")

    # 5. Multi-User Isolation Verification
    print("\n--- 5. Cross-User Data Isolation in MongoDB Atlas ---")
    user_b_id = f"user_b_{test_id}"

    # Conversation isolation: User B cannot retrieve User A's conversation
    conv_b = conv_store.get(conv_id, user_id=user_b_id)
    assert conv_b is None
    print(f"[PASS] Cross-user conversation isolation: User B cannot retrieve User A's conversation.")

    # Memory isolation: User B cannot view User A's memories
    memories_b = mem_store.list_by_user(user_id=user_b_id)
    assert len(memories_b) == 0
    print(f"[PASS] Cross-user memory isolation: User B cannot retrieve User A's memories.")

    # Document isolation: User B cannot view User A's documents
    docs_b = vec_store.list_documents(user_id=user_b_id)
    assert not any(d["document_id"] == f"doc_{test_id}" for d in docs_b)
    print(f"[PASS] Cross-user RAG document isolation: User B cannot list User A's documents.")

    # 6. Cleanup of test artifacts
    print("\n--- 6. Clean Teardown of Test Artifacts ---")
    db["users"].delete_one({"_id": user["id"]})
    db["conversations"].delete_one({"_id": conv_id})
    db["user_memories"].delete_one({"_id": mem_item.id})
    db["vector_embeddings"].delete_one({"_id": test_chunk.chunk_id})
    print(f"[PASS] Cleaned up temporary test documents from all 4 Atlas collections.")

    db_mgr.close()

    print("\n" + "=" * 70)
    print("[SUCCESS] ALL 5 CORE MODULES VERIFIED AGAINST LIVE MONGODB ATLAS!")
    print("=" * 70)
    return True


if __name__ == "__main__":
    success = run_atlas_module_verification()
    sys.exit(0 if success else 1)
