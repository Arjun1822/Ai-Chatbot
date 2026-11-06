import io
import pytest
from rag.extractor import DocumentExtractor, DocumentExtractionException
from rag.chunker import TextChunker
from rag.embeddings import EmbeddingService
from rag.vector_store import LocalVectorStore, SearchResult
from rag.rag_service import RAGService


def test_extractor_plain_text():
    text = "Hello world! This is a test file for ORBIT AI RAG."
    extracted, meta = DocumentExtractor.extract_text("readme.txt", text.encode("utf-8"))
    assert extracted == text
    assert meta["filename"] == "readme.txt"
    assert meta["extension"] == ".txt"


def test_extractor_unsupported_and_empty():
    with pytest.raises(DocumentExtractionException, match="empty"):
        DocumentExtractor.extract_text("test.txt", b"")

    with pytest.raises(DocumentExtractionException, match="Unsupported file format"):
        DocumentExtractor.extract_text("malware.exe", b"MZ\x90\x00\x03\x00")


def test_chunker_boundaries():
    chunker = TextChunker(chunk_size=100, chunk_overlap=20)
    sample_text = (
        "Paragraph one is here with interesting facts about artificial intelligence.\n\n"
        "Paragraph two continues with deep discussions on autonomous agents, tool use, and RAG systems."
    )
    chunks = chunker.chunk_document("doc_1", sample_text, {"filename": "sample.txt"})
    assert len(chunks) >= 2
    for c in chunks:
        assert len(c.text) > 0
        assert c.document_id == "doc_1"


def test_embeddings_service():
    service = EmbeddingService(api_key=None)  # Tests deterministic fallback
    vec = service.embed_text("Orbital artificial intelligence agent")
    assert len(vec) == service.FALLBACK_DIMENSION
    # Vector should be unit normalized
    norm = sum(x * x for x in vec)
    assert pytest.approx(norm, rel=1e-3) == 1.0

    batch = service.embed_batch(["First sentence.", "Second query."])
    assert len(batch) == 2
    assert len(batch[0]) == service.FALLBACK_DIMENSION


def test_vector_store_crud_and_isolation():
    store = LocalVectorStore()
    chunker = TextChunker(chunk_size=50, chunk_overlap=10)
    chunks_user1 = chunker.chunk_document("doc_u1", "Secret document for Alice about quantum physics.", {"filename": "u1.txt"})
    chunks_user2 = chunker.chunk_document("doc_u2", "Confidential memo for Bob about finance.", {"filename": "u2.txt"})

    emb_service = EmbeddingService()
    emb_u1 = emb_service.embed_batch([c.text for c in chunks_user1])
    emb_u2 = emb_service.embed_batch([c.text for c in chunks_user2])

    store.add_chunks(chunks_user1, emb_u1, user_id="user_alice")
    store.add_chunks(chunks_user2, emb_u2, user_id="user_bob")

    # Search isolated to user_alice
    q_emb = emb_service.embed_text("quantum physics")
    alice_results = store.search(q_emb, top_k=5, user_id="user_alice")
    assert len(alice_results) > 0
    assert all(r.user_id == "user_alice" for r in alice_results)

    # Search isolated to user_bob
    bob_results = store.search(q_emb, top_k=5, user_id="user_bob")
    assert all(r.user_id == "user_bob" for r in bob_results)

    # Delete document
    deleted = store.delete_document("doc_u1", user_id="user_alice")
    assert deleted > 0
    alice_after = store.search(q_emb, top_k=5, user_id="user_alice")
    assert len(alice_after) == 0


def test_rag_service_end_to_end():
    rag = RAGService()
    content = b"The Gemini model is a family of multimodal models developed by Google DeepMind."
    doc = rag.ingest_document("gemini.txt", content, user_id="tester")
    assert doc["total_chunks"] >= 1
    assert doc["filename"] == "gemini.txt"

    res = rag.query_documents("Google DeepMind multimodal", user_id="tester")
    assert res["results_count"] > 0
    assert len(res["citations"]) > 0
    assert "Gemini" in res["context"]
    assert res["citations"][0]["filename"] == "gemini.txt"

    rag.delete_document(doc["document_id"], user_id="tester")
    assert len(rag.list_documents(user_id="tester")) == 0
