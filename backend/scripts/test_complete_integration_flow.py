import json
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

from app import create_app
from config import Config
from database import DatabaseManager


def run_complete_integration_flow():
    print("=" * 75)
    print("ORBIT AI - 15-STEP COMPLETE END-TO-END WORKFLOW INTEGRATION TEST")
    print("=" * 75)

    app = create_app(Config)
    client = app.test_client()
    db_mgr = DatabaseManager.get_instance()
    db = db_mgr.database

    test_run_id = uuid.uuid4().hex[:8]
    user1_email = f"user1_{test_run_id}@orbit.local"
    user1_pwd = f"Pass_{test_run_id}!1A"
    user2_email = f"user2_{test_run_id}@orbit.local"
    user2_pwd = f"Pass_{test_run_id}!2B"

    created_user_ids = []
    created_conv_ids = []
    created_doc_ids = []

    try:
        # STEP 1: Register User 1
        print("\n[Step 1/15] Registering new test user 1...")
        res = client.post("/api/auth/register", json={
            "email": user1_email,
            "password": user1_pwd,
            "name": "E2E User 1",
        })
        assert res.status_code == 201, f"Failed registration: {res.get_json()}"
        data = res.get_json()
        user1_id = data["user"]["id"]
        created_user_ids.append(user1_id)
        print(f" -> PASS: User 1 registered (ID: {user1_id})")

        # STEP 2: Log In as User 1
        print("\n[Step 2/15] Logging in as User 1...")
        res = client.post("/api/auth/login", json={
            "email": user1_email,
            "password": user1_pwd,
        })
        assert res.status_code == 200, f"Login failed: {res.get_json()}"
        token1 = res.get_json()["token"]
        headers1 = {"Authorization": f"Bearer {token1}"}
        print(" -> PASS: Logged in successfully. Received auth token.")

        # STEP 3: Create Conversation
        print("\n[Step 3/15] Creating new conversation...")
        res = client.post("/api/conversations", json={"title": "E2E Production Chat"}, headers=headers1)
        assert res.status_code == 201, f"Create conv failed: {res.get_json()}"
        conv1_id = res.get_json()["conversation"]["_id"]
        created_conv_ids.append(conv1_id)
        print(f" -> PASS: Conversation created in Atlas (ID: {conv1_id})")

        # STEP 4: Send Chat Message & STEP 5: Receive Response & STEP 6: Verify Streaming
        print("\n[Step 4-6/15] Sending message & verifying streaming SSE response...")
        res = client.post("/api/chat/stream", json={
            "conversation_id": conv1_id,
            "message": "Hello Orbit! What is 15 * 6? Answer briefly.",
            "mode": "chat",
        }, headers=headers1)
        assert res.status_code == 200
        assert "text/event-stream" in res.content_type

        # Parse SSE stream
        raw_sse = res.get_data(as_text=True)
        lines = [line.strip() for line in raw_sse.split("\n") if line.strip().startswith("data: ")]
        chunks = []
        is_done = False
        full_text = ""

        for line in lines:
            payload_str = line[6:]
            if payload_str == "[DONE]":
                is_done = True
                continue
            try:
                evt = json.loads(payload_str)
                if evt.get("type") == "chunk":
                    chunk_content = evt.get("text") or evt.get("content", "")
                    chunks.append(chunk_content)
                    full_text += chunk_content
                elif evt.get("type") == "done":
                    is_done = True
            except Exception:
                pass

        assert len(chunks) > 0, "No streaming chunks received!"
        assert is_done, "Stream did not emit completion [DONE] signal!"
        print(f" -> PASS: Streaming verified. Received {len(chunks)} tokens/chunks.")
        print(f" -> Model response snippet: '{full_text[:80]}...'")

        # STEP 7: Simulate Browser Refresh / Retrieve History & STEP 8: Verify Persistence
        print("\n[Step 7-8/15] Simulating page refresh & retrieving conversation from Atlas...")
        res = client.get(f"/api/conversations/{conv1_id}", headers=headers1)
        assert res.status_code == 200
        conv_restored = res.get_json()["conversation"]
        assert len(conv_restored["messages"]) >= 2
        assert conv_restored["messages"][0]["role"] == "user"
        assert conv_restored["messages"][1]["role"] in ("assistant", "model")
        print(" -> PASS: History physically restored from Atlas with user and model messages.")

        # STEP 9: Upload Document & STEP 10: Verify Chunking
        print("\n[Step 9-10/15] Uploading document and verifying chunking...")
        sample_doc_content = (
            "ORBIT AI ARCHITECTURE DOCUMENTATION (CONFIDENTIAL)\n"
            "System Section 8.4: Maximum simultaneous connections per node is capped at 5000.\n"
            "Section 8.5: The primary authentication mechanism is PBKDF2-HMAC-SHA256 with 100,000 rounds.\n"
            "Section 8.6: RAG semantic embeddings use normalized cosine similarity metrics."
        )
        res = client.post("/api/documents", json={
            "filename": "orbit_spec.txt",
            "content": sample_doc_content,
        }, headers=headers1)
        assert res.status_code == 201, f"Document upload failed: {res.get_json()}"
        doc_record = res.get_json()["document"]
        doc_id = doc_record["document_id"]
        created_doc_ids.append(doc_id)
        assert doc_record["total_chunks"] >= 1
        print(f" -> PASS: Document ingested (ID: {doc_id}, Chunks: {doc_record['total_chunks']})")

        # STEP 11: Ask Question About Document & STEP 12: Verify RAG Citations
        print("\n[Step 11-12/15] Querying RAG agent and verifying citations...")
        res = client.post("/api/chat/stream", json={
            "conversation_id": conv1_id,
            "message": "What is the maximum simultaneous connections per node according to Section 8.4?",
            "mode": "document",
        }, headers=headers1)
        assert res.status_code == 200
        raw_rag_sse = res.get_data(as_text=True)
        rag_events = [
            json.loads(line[6:])
            for line in raw_rag_sse.split("\n")
            if line.strip().startswith("data: ") and line.strip() != "data: [DONE]"
        ]
        done_event = next((e for e in rag_events if e.get("type") == "done"), {})
        citations = done_event.get("citations", [])
        assert len(citations) > 0, "RAG query should produce document citations!"
        assert citations[0]["filename"] == "orbit_spec.txt"
        print(f" -> PASS: RAG response generated with valid citation: '{citations[0]['filename']}'")

        # STEP 13: Log Out
        print("\n[Step 13/15] Logging out User 1...")
        res = client.post("/api/auth/logout", headers=headers1)
        assert res.status_code == 200
        print(" -> PASS: Logged out successfully.")

        # STEP 14: Protected Endpoint Rejection Without Auth
        print("\n[Step 14/15] Verifying protected endpoints reject unauthenticated calls...")
        res = client.get("/api/auth/me")  # strict auth required
        assert res.status_code == 401
        res = client.get("/api/auth/me", headers={"Authorization": "Bearer invalid_tampered_token"})
        assert res.status_code == 401
        print(" -> PASS: Protected endpoints correctly returned HTTP 401 Unauthorized.")

        # STEP 15: Cross-User Isolation (User 2 Cannot Access User 1's Data)
        print("\n[Step 15/15] Logging in as User 2 and verifying cross-user isolation...")
        res = client.post("/api/auth/register", json={
            "email": user2_email,
            "password": user2_pwd,
            "name": "E2E User 2",
        })
        user2_id = res.get_json()["user"]["id"]
        created_user_ids.append(user2_id)
        token2 = res.get_json()["token"]
        headers2 = {"Authorization": f"Bearer {token2}"}

        # Attempt to access User 1's conversation
        res = client.get(f"/api/conversations/{conv1_id}", headers=headers2)
        assert res.status_code == 404, "Security Defect: User 2 accessed User 1's conversation!"

        # Attempt to delete User 1's conversation
        res = client.delete(f"/api/conversations/{conv1_id}", headers=headers2)
        assert res.status_code == 404, "Security Defect: User 2 deleted User 1's conversation!"

        # Attempt to list User 1's documents
        res = client.get("/api/documents", headers=headers2)
        user2_docs = res.get_json()["documents"]
        assert not any(d["document_id"] == doc_id for d in user2_docs), "Security Defect: User 2 saw User 1's document!"

        print(" -> PASS: Complete multi-tenant data isolation verified across conversations and documents.")

        print("\n" + "=" * 75)
        print("[SUCCESS] ALL 15 PRODUCTION WORKFLOW STEPS PASSED WITH 100% SUCCESS!")
        print("=" * 75)
        return True

    finally:
        # Clean up test documents and users created during this test
        print("\n[Clean-up] Removing temporary test records from Atlas...")
        if db is not None:
            for uid in created_user_ids:
                db["users"].delete_one({"_id": uid})
            for cid in created_conv_ids:
                db["conversations"].delete_one({"_id": cid})
            for did in created_doc_ids:
                db["vector_embeddings"].delete_many({"document_id": did})
        print("[Clean-up] Completed.")


if __name__ == "__main__":
    success = run_complete_integration_flow()
    sys.exit(0 if success else 1)
