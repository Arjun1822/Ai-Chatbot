from datetime import datetime, timezone
import logging
import os
from typing import Any, Dict, List, Optional
import uuid

from rag.chunker import TextChunker
from rag.embeddings import EmbeddingService
from rag.extractor import DocumentExtractor
from rag.vector_store import BaseVectorStore, LocalVectorStore, SearchResult

logger = logging.getLogger(__name__)


class RAGService:
    """High-level RAG coordinator for document ingestion, retrieval, and citation generation."""

    def __init__(
        self,
        vector_store: Optional[BaseVectorStore] = None,
        embedding_service: Optional[EmbeddingService] = None,
        chunk_size: int = 500,
        chunk_overlap: int = 100,
        data_dir: Optional[str] = None,
    ):
        base_dir = data_dir or os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
        persistence_path = os.path.join(base_dir, "vector_store.json")

        self.vector_store = vector_store or LocalVectorStore(persistence_path=persistence_path)
        self.embedding_service = embedding_service or EmbeddingService()
        self.chunker = TextChunker(chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    def ingest_document(
        self,
        filename: str,
        file_bytes: bytes,
        user_id: str = "default_user",
    ) -> Dict[str, Any]:
        """Extract, chunk, embed, and index a document."""
        text, meta = DocumentExtractor.extract_text(filename, file_bytes)

        document_id = f"doc_{uuid.uuid4().hex[:12]}"
        now_iso = datetime.now(timezone.utc).isoformat()
        meta.update({
            "document_id": document_id,
            "user_id": user_id,
            "created_at": now_iso,
        })

        chunks = self.chunker.chunk_document(document_id, text, meta)
        if not chunks:
            raise ValueError("No valid text chunks could be extracted from document.")

        chunk_texts = [c.text for c in chunks]
        embeddings = self.embedding_service.embed_batch(chunk_texts)

        self.vector_store.add_chunks(chunks, embeddings, user_id=user_id)

        return {
            "document_id": document_id,
            "filename": filename,
            "user_id": user_id,
            "total_chunks": len(chunks),
            "char_count": len(text),
            "created_at": now_iso,
            "metadata": meta,
        }

    def query_documents(
        self,
        query: str,
        top_k: int = 4,
        score_threshold: float = 0.0,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Retrieve most relevant document chunks and assemble formatted context and citations."""
        if not query or not query.strip():
            return {"context": "", "citations": [], "results_count": 0}

        query_emb = self.embedding_service.embed_text(query)
        results: List[SearchResult] = self.vector_store.search(
            query_embedding=query_emb,
            top_k=top_k,
            score_threshold=score_threshold,
            user_id=user_id,
        )

        if not results:
            return {"context": "", "citations": [], "results_count": 0}

        citations = []
        context_parts = []
        for i, res in enumerate(results, start=1):
            fn = res.metadata.get("filename", "Unknown Document")
            chunk_idx = res.metadata.get("chunk_index", 0)
            citations.append({
                "source_number": i,
                "document_id": res.document_id,
                "chunk_id": res.chunk_id,
                "filename": fn,
                "score": round(res.score, 4),
                "snippet": res.text[:240].strip(),
            })
            context_parts.append(
                f"[Source {i} | File: {fn} | Chunk: {chunk_idx}]\n{res.text}"
            )

        formatted_context = "\n\n".join(context_parts)
        return {
            "context": formatted_context,
            "citations": citations,
            "results_count": len(results),
        }

    def delete_document(self, document_id: str, user_id: Optional[str] = None) -> int:
        return self.vector_store.delete_document(document_id, user_id=user_id)

    def list_documents(self, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        return self.vector_store.list_documents(user_id=user_id)
