import io
import math
import sys
from unittest.mock import MagicMock
import pytest
from rag.extractor import DocumentExtractor, DocumentExtractionException
from rag.chunker import TextChunker
from rag.embeddings import EmbeddingService, EmbeddingError
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


def test_embeddings_service(monkeypatch):
    """Verify default offline embedding behavior: 3072 dimensions, normalized, and deterministic."""
    monkeypatch.setenv("GEMINI_API_KEY", "")
    service = EmbeddingService(api_key="")
    assert service.FALLBACK_DIMENSION == 3072
    assert service.expected_dimension == 3072

    vec = service.embed_text("Orbital artificial intelligence agent")
    assert len(vec) == 3072
    # Vector should be unit normalized
    norm = sum(x * x for x in vec)
    assert pytest.approx(norm, rel=1e-3) == 1.0

    batch = service.embed_batch(["First sentence.", "Second query."])
    assert len(batch) == 2
    assert len(batch[0]) == 3072
    assert len(batch[1]) == 3072


def test_embeddings_service_empty_input(monkeypatch):
    """Verify empty input returns 3072-dimensional zero vector."""
    monkeypatch.setenv("GEMINI_API_KEY", "")
    service = EmbeddingService(api_key="")
    zero_vec = service.embed_text("")
    assert len(zero_vec) == 3072
    assert all(v == 0.0 for v in zero_vec)

    empty_batch = service.embed_batch([])
    assert empty_batch == []


def test_embeddings_service_deterministic_fallback(monkeypatch):
    """Verify deterministic fallback produces identical normalized embeddings for identical text."""
    monkeypatch.setenv("GEMINI_API_KEY", "")
    service = EmbeddingService(api_key="")
    vec1 = service.embed_text("Autonomous AI multi-agent orchestration")
    vec2 = service.embed_text("Autonomous AI multi-agent orchestration")
    assert vec1 == vec2

    # Different text should produce different vectors
    vec_diff = service.embed_text("Completely unrelated financial ledger statement")
    assert vec1 != vec_diff


def test_embeddings_service_gemini_api_success():
    """Verify mocked successful Gemini API call returning 3072-dimensional vector."""
    service = EmbeddingService(api_key="")
    mock_client = MagicMock()
    # Provide a raw 3072-dimensional mock vector
    raw_vector = [float(i % 10 + 1) for i in range(3072)]
    mock_response = MagicMock()
    mock_response.embeddings = [MagicMock(values=raw_vector)]
    mock_client.models.embed_content.return_value = mock_response
    service._client = mock_client

    result = service.embed_text("Testing Gemini API integration")
    assert len(result) == 3072
    # Result must be L2 normalized
    norm = math.sqrt(sum(x * x for x in result))
    assert pytest.approx(norm, rel=1e-3) == 1.0
    mock_client.models.embed_content.assert_called_once()


def test_embeddings_service_gemini_api_failure_fallback():
    """Verify Gemini API failure safely falls back to 3072-dimensional deterministic vector."""
    service = EmbeddingService(api_key="")
    mock_client = MagicMock()
    mock_client.models.embed_content.side_effect = RuntimeError("Quota exceeded or network timeout")
    service._client = mock_client

    result = service.embed_text("Query during external API outage")
    assert len(result) == 3072
    norm = sum(x * x for x in result)
    assert pytest.approx(norm, rel=1e-3) == 1.0


def test_embeddings_service_gemini_invalid_dimension_fallback():
    """Verify unexpected/truncated dimensions from Gemini are rejected and fallback is used."""
    service = EmbeddingService(api_key="")
    mock_client = MagicMock()
    # Mock returning wrong dimension (e.g., 256 or 512 instead of 3072)
    mock_response = MagicMock()
    mock_response.embeddings = [MagicMock(values=[0.1] * 256)]
    mock_client.models.embed_content.return_value = mock_response
    service._client = mock_client

    result = service.embed_text("Query with malformed model dimensions")
    # Must reject 256 and return exactly 3072 dimensions
    assert len(result) == 3072
    norm = sum(x * x for x in result)
    assert pytest.approx(norm, rel=1e-3) == 1.0


def test_embeddings_service_batch_behavior():
    """Verify batch embedding behavior for mixed queries and Gemini batching."""
    service = EmbeddingService(api_key="")
    mock_client = MagicMock()
    raw1 = [0.2] * 3072
    raw2 = [0.5] * 3072
    mock_response = MagicMock()
    mock_response.embeddings = [MagicMock(values=raw1), MagicMock(values=raw2)]
    mock_client.models.embed_content.return_value = mock_response
    service._client = mock_client

    results = service.embed_batch(["First doc", "Second doc"])
    assert len(results) == 2
    assert len(results[0]) == 3072
    assert len(results[1]) == 3072


def test_embeddings_service_env_isolation(monkeypatch):
    """Verify environment variable isolation prevents accidental external calls."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    service = EmbeddingService()
    assert service._client is None
    vec = service.embed_text("Isolated offline execution")
    assert len(vec) == 3072


def test_vector_store_crud_and_isolation():
    store = LocalVectorStore()
    chunker = TextChunker(chunk_size=50, chunk_overlap=10)
    chunks_user1 = chunker.chunk_document("doc_u1", "Secret document for Alice about quantum physics.", {"filename": "u1.txt"})
    chunks_user2 = chunker.chunk_document("doc_u2", "Confidential memo for Bob about finance.", {"filename": "u2.txt"})

    emb_service = EmbeddingService(api_key="")
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
    emb_service = EmbeddingService(api_key="")
    rag = RAGService(embedding_service=emb_service)
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


def test_embeddings_service_production_blocks_fallback(monkeypatch):
    """Verify production environment blocks silent fallback when Gemini fails."""
    monkeypatch.setenv("FLASK_ENV", "production")
    monkeypatch.delenv("ALLOW_EPHEMERAL_STORAGE", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "")

    service = EmbeddingService(allow_fallback=False)
    with pytest.raises(EmbeddingError, match="prohibited in production"):
        service.embed_text("Production query without client")

    with pytest.raises(EmbeddingError, match="prohibited in production"):
        service.embed_batch(["Batch production chunk"])


def test_embeddings_service_production_api_failure_raises(monkeypatch):
    """Verify Gemini API failure in production raises EmbeddingError instead of returning hash vectors."""
    service = EmbeddingService(api_key="mock_key", allow_fallback=False)
    mock_client = MagicMock()
    mock_client.models.embed_content.side_effect = RuntimeError("Quota 429 exceeded")
    service._client = mock_client

    with pytest.raises(EmbeddingError, match="Semantic embedding generation failed in production"):
        service.embed_text("Query during rate limit")

    with pytest.raises(EmbeddingError, match="Semantic batch embedding generation failed in production"):
        service.embed_batch(["Doc chunk during rate limit"])


def test_rag_ingest_production_blocks_fallback_storage():
    """Verify RAGService does not persist fallback vectors if Gemini fails in production."""
    mock_vector_store = MagicMock()
    service = EmbeddingService(api_key="", allow_fallback=False)
    rag = RAGService(vector_store=mock_vector_store, embedding_service=service)

    with pytest.raises(EmbeddingError):
        rag.ingest_document("test.txt", b"Sensitive enterprise doc", user_id="user_123")

    # Vector store must NOT have been called to add chunks
    mock_vector_store.add_chunks.assert_not_called()


def test_embedding_model_metadata_tracked_and_stored():
    """Verify model metadata is attached to chunks and document records."""
    store = LocalVectorStore()
    emb_service = EmbeddingService(api_key="", allow_fallback=True)
    rag = RAGService(vector_store=store, embedding_service=emb_service)

    doc = rag.ingest_document("report.txt", b"Financial report data 2026", user_id="admin_1")
    assert doc["embedding_model"] == EmbeddingService.MODEL_FALLBACK
    assert doc["metadata"]["embedding_model"] == EmbeddingService.MODEL_FALLBACK
    assert doc["metadata"]["embedding_dimension"] == 3072

    # Check store items
    for item in store._items.values():
        assert item["embedding_model"] == EmbeddingService.MODEL_FALLBACK
        assert len(item["embedding"]) == 3072


def test_retrieval_rejects_incompatible_embedding_models():
    """Verify retrieval rejects comparing Gemini query vector with fallback document vectors."""
    store = LocalVectorStore()
    chunker = TextChunker(chunk_size=100, chunk_overlap=20)
    chunks = chunker.chunk_document("doc_fallback", "Content indexed with fallback hashing", {"filename": "fb.txt"})

    # Manually store with MODEL_FALLBACK
    fallback_vecs = [[0.1] * 3072]
    store.add_chunks(chunks, fallback_vecs, user_id="user_test", embedding_model=EmbeddingService.MODEL_FALLBACK)

    # Query using gemini model
    gemini_query_vec = [0.1] * 3072
    res = store.search(
        query_embedding=gemini_query_vec,
        user_id="user_test",
        query_model=EmbeddingService.MODEL_GEMINI,
    )
    # Must reject because models differ!
    assert len(res) == 0

    # Query with compatible model succeeds
    res_compatible = store.search(
        query_embedding=gemini_query_vec,
        user_id="user_test",
        query_model=EmbeddingService.MODEL_FALLBACK,
    )
    assert len(res_compatible) > 0


def test_vector_store_dimension_validation():
    """Verify LocalVectorStore rejects malformed vector dimensions."""
    store = LocalVectorStore(expected_dimension=3072)
    chunker = TextChunker()
    chunks = chunker.chunk_document("doc_dim", "Test dimension validation", {"filename": "dim.txt"})

    with pytest.raises(ValueError, match="dimension mismatch"):
        store.add_chunks(chunks, [[0.1] * 256], user_id="user_test")

    with pytest.raises(ValueError, match="Query embedding dimension mismatch"):
        store.search(query_embedding=[0.1] * 512, user_id="user_test")


def test_production_detection_precedence_and_overrides(monkeypatch):
    """Verify Render, Atlas, and production env take absolute precedence over development defaults."""
    from config import Config

    # 1. Clean local development: no Render, empty/local URI, FLASK_ENV=development -> False
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.delenv("RENDER_SERVICE_ID", raising=False)
    monkeypatch.setattr(Config, "FLASK_ENV", "development")
    monkeypatch.setattr(Config, "MONGODB_URI", "")
    assert Config.is_production_mode() is False

    # 2. Render indicator takes absolute precedence over FLASK_ENV=development
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setattr(Config, "FLASK_ENV", "development")
    monkeypatch.setattr(Config, "MONGODB_URI", "")
    assert Config.is_production_mode() is True

    # 3. Atlas URI takes absolute precedence over FLASK_ENV=development
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.setattr(Config, "FLASK_ENV", "development")
    monkeypatch.setattr(Config, "MONGODB_URI", "mongodb+srv://cluster.mongodb.net/orbit_ai")
    assert Config.is_production_mode() is True

    # 4. Atlas URI with missing/empty FLASK_ENV -> True (fail-closed)
    monkeypatch.setattr(Config, "FLASK_ENV", "")
    assert Config.is_production_mode() is True

    # 5. Production ENV takes precedence even if FLASK_ENV missing
    monkeypatch.setattr(Config, "MONGODB_URI", "")
    monkeypatch.setenv("ENV", "production")
    assert Config.is_production_mode() is True
    monkeypatch.delenv("ENV", raising=False)

    # 6. Explicit FLASK_ENV=production -> True
    monkeypatch.setattr(Config, "FLASK_ENV", "production")
    assert Config.is_production_mode() is True


def test_production_fallback_always_disabled_even_with_allow_flags(monkeypatch):
    """Verify ALLOW_FALLBACK and ALLOW_EPHEMERAL_STORAGE can NEVER re-enable fallback in production."""
    from config import Config
    monkeypatch.setattr(Config, "FLASK_ENV", "production")
    monkeypatch.setenv("ALLOW_FALLBACK", "true")
    monkeypatch.setenv("ALLOW_EPHEMERAL_STORAGE", "true")

    # In production, EmbeddingService must force allow_fallback=False
    emb_service = EmbeddingService(api_key="")
    assert emb_service.allow_fallback is False
    with pytest.raises(EmbeddingError):
        emb_service.embed_text("Attempting fallback in production with override flags")

    # Local development without flags permits fallback
    monkeypatch.setattr(Config, "FLASK_ENV", "development")
    monkeypatch.setattr(Config, "MONGODB_URI", "")
    monkeypatch.delenv("RENDER", raising=False)
    dev_service = EmbeddingService(api_key="")
    assert dev_service.allow_fallback is True


def test_embeddings_service_fails_closed_when_config_import_fails(monkeypatch):
    """Verify EmbeddingService fails closed to production mode if Config import fails."""
    monkeypatch.setitem(sys.modules, "config", None)

    service = EmbeddingService(api_key="")
    assert service.allow_fallback is False
    with pytest.raises(EmbeddingError, match="prohibited in production"):
        service.embed_text("Text during Config import failure")


def test_embeddings_service_fails_closed_when_config_detection_raises(monkeypatch):
    """Verify EmbeddingService fails closed if Config.is_production_mode raises an exception."""
    from config import Config

    def mock_is_production_mode():
        raise RuntimeError("Unexpected failure during production inspection")

    monkeypatch.setattr(Config, "is_production_mode", mock_is_production_mode)

    service = EmbeddingService(api_key="")
    assert service.allow_fallback is False
    with pytest.raises(EmbeddingError, match="prohibited in production"):
        service.embed_text("Text during Config detection exception")


def test_embeddings_service_render_environment_disables_fallback(monkeypatch):
    """Verify Render environment variables strictly disable fallback even if FLASK_ENV=development."""
    from config import Config
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setattr(Config, "FLASK_ENV", "development")
    monkeypatch.setattr(Config, "MONGODB_URI", "")
    monkeypatch.setenv("ALLOW_FALLBACK", "true")

    service = EmbeddingService(api_key="")
    assert service.allow_fallback is False
    with pytest.raises(EmbeddingError, match="prohibited in production"):
        service.embed_text("Text on Render platform")


def test_embeddings_service_atlas_uri_disables_fallback(monkeypatch):
    """Verify MongoDB Atlas URI strictly disables fallback even if FLASK_ENV=development."""
    from config import Config
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.setattr(Config, "FLASK_ENV", "development")
    monkeypatch.setattr(Config, "MONGODB_URI", "mongodb+srv://admin:pass@cluster0.pkbn9cr.mongodb.net/orbit_ai")
    monkeypatch.setenv("ALLOW_FALLBACK", "true")

    service = EmbeddingService(api_key="")
    assert service.allow_fallback is False
    with pytest.raises(EmbeddingError, match="prohibited in production"):
        service.embed_text("Text with Atlas URI configured")


def test_embeddings_service_development_mode_supports_isolated_fallback(monkeypatch):
    """Verify development mode with local/unconfigured DB permits isolated deterministic fallback."""
    from config import Config
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.delenv("RENDER_SERVICE_ID", raising=False)
    monkeypatch.setattr(Config, "FLASK_ENV", "development")
    monkeypatch.setattr(Config, "MONGODB_URI", "")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    service = EmbeddingService(api_key="")
    assert service.allow_fallback is True
    vec = service.embed_text("Isolated local dev text")
    assert len(vec) == 3072
    assert pytest.approx(sum(x * x for x in vec), rel=1e-3) == 1.0


def test_atlas_vector_search_pipeline_pre_filter():
    """Verify $vectorSearch pipeline embeds both user_id and embedding_model in pre-filter."""
    from rag.vector_store import MongoAtlasVectorStore

    mock_client = MagicMock()
    mock_collection = MagicMock()
    mock_client.__getitem__.return_value.__getitem__.return_value = mock_collection
    mock_collection.aggregate.return_value = [
        {
            "_id": "chk_1",
            "document_id": "doc_1",
            "user_id": "tenant_a",
            "text": "Relevant chunk text",
            "metadata": {"filename": "doc.txt"},
            "embedding_model": "gemini-embedding-001",
            "score": 0.92,
        }
    ]

    store = MongoAtlasVectorStore(mongo_client=mock_client)
    q_vec = [0.05] * 3072
    results = store.search(
        query_embedding=q_vec,
        user_id="tenant_a",
        query_model="gemini-embedding-001",
    )

    assert len(results) == 1
    assert results[0].chunk_id == "chk_1"

    # Inspect the exact pipeline passed to aggregate()
    mock_collection.aggregate.assert_called_once()
    pipeline = mock_collection.aggregate.call_args[0][0]
    vector_search_stage = pipeline[0]["$vectorSearch"]

    # Pre-filter MUST contain both user_id and embedding_model
    filter_doc = vector_search_stage["filter"]
    assert "$and" in filter_doc
    filter_keys = {}
    for clause in filter_doc["$and"]:
        filter_keys.update(clause)
    assert filter_keys.get("user_id") == "tenant_a"
    assert filter_keys.get("embedding_model") == "gemini-embedding-001"


def test_atlas_vector_search_excludes_legacy_untracked_records():
    """Verify legacy records without embedding_model are rejected by defense-in-depth."""
    from rag.vector_store import MongoAtlasVectorStore

    mock_client = MagicMock()
    mock_collection = MagicMock()
    mock_client.__getitem__.return_value.__getitem__.return_value = mock_collection
    # Mock returning one untracked record (missing embedding_model) and one valid record
    mock_collection.aggregate.return_value = [
        {
            "_id": "chk_legacy",
            "document_id": "doc_legacy",
            "user_id": "tenant_a",
            "text": "Legacy unversioned chunk",
            "metadata": {"filename": "old.txt"},
            # Missing embedding_model
            "score": 0.88,
        },
        {
            "_id": "chk_valid",
            "document_id": "doc_valid",
            "user_id": "tenant_a",
            "text": "Valid versioned chunk",
            "metadata": {"filename": "valid.txt"},
            "embedding_model": "gemini-embedding-001",
            "score": 0.85,
        }
    ]

    store = MongoAtlasVectorStore(mongo_client=mock_client)
    q_vec = [0.05] * 3072
    results = store.search(
        query_embedding=q_vec,
        user_id="tenant_a",
        query_model="gemini-embedding-001",
    )

    # Legacy record must be filtered out; only valid record returned
    assert len(results) == 1
    assert results[0].chunk_id == "chk_valid"
