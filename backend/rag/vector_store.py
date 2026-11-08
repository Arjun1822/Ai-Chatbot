from abc import ABC, abstractmethod
from dataclasses import dataclass
import json
import logging
import os
import threading
from typing import Any, Dict, List, Optional
from rag.chunker import DocumentChunk

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    chunk_id: str
    document_id: str
    user_id: str
    text: str
    score: float
    metadata: Dict[str, Any]


class BaseVectorStore(ABC):
    """Abstract interface for vector stores."""

    @abstractmethod
    def add_chunks(
        self,
        chunks: List[DocumentChunk],
        embeddings: List[List[float]],
        user_id: str = "default_user",
    ) -> None:
        pass

    @abstractmethod
    def search(
        self,
        query_embedding: List[float],
        top_k: int = 4,
        score_threshold: float = 0.0,
        user_id: Optional[str] = None,
        document_id: Optional[str] = None,
    ) -> List[SearchResult]:
        pass

    @abstractmethod
    def delete_document(self, document_id: str, user_id: Optional[str] = None) -> int:
        pass

    @abstractmethod
    def list_documents(self, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        pass


class LocalVectorStore(BaseVectorStore):
    """Thread-safe in-memory vector store with optional JSON disk persistence."""

    def __init__(self, persistence_path: Optional[str] = None):
        self._lock = threading.RLock()
        self._persistence_path = persistence_path
        self._items: Dict[str, Dict[str, Any]] = {}  # chunk_id -> item dict
        self._documents: Dict[str, Dict[str, Any]] = {}  # doc_id -> doc metadata
        if persistence_path and os.path.exists(persistence_path):
            self._load()

    def add_chunks(
        self,
        chunks: List[DocumentChunk],
        embeddings: List[List[float]],
        user_id: str = "default_user",
    ) -> None:
        if len(chunks) != len(embeddings):
            raise ValueError("Chunks count must match embeddings count.")

        with self._lock:
            for chunk, emb in zip(chunks, embeddings):
                self._items[chunk.chunk_id] = {
                    "chunk_id": chunk.chunk_id,
                    "document_id": chunk.document_id,
                    "user_id": user_id,
                    "chunk_index": chunk.chunk_index,
                    "text": chunk.text,
                    "embedding": emb,
                    "char_start": chunk.char_start,
                    "char_end": chunk.char_end,
                    "metadata": chunk.metadata,
                }
                # Track document metadata
                doc_id = chunk.document_id
                if doc_id not in self._documents:
                    self._documents[doc_id] = {
                        "document_id": doc_id,
                        "user_id": user_id,
                        "filename": chunk.metadata.get("filename", "Unknown"),
                        "total_chunks": 1,
                        "created_at": chunk.metadata.get("created_at"),
                    }
                else:
                    self._documents[doc_id]["total_chunks"] += 1

            self._save()

    def search(
        self,
        query_embedding: List[float],
        top_k: int = 4,
        score_threshold: float = 0.0,
        user_id: Optional[str] = None,
        document_id: Optional[str] = None,
    ) -> List[SearchResult]:
        with self._lock:
            scored_results: List[SearchResult] = []
            for item in self._items.values():
                # Isolation check
                if user_id and item.get("user_id") != user_id:
                    continue
                if document_id and item.get("document_id") != document_id:
                    continue

                emb = item["embedding"]
                # Cosine similarity for unit-normalized vectors: dot product
                score = sum(q * d for q, d in zip(query_embedding, emb))
                if score >= score_threshold:
                    scored_results.append(
                        SearchResult(
                            chunk_id=item["chunk_id"],
                            document_id=item["document_id"],
                            user_id=item.get("user_id", "default_user"),
                            text=item["text"],
                            score=float(score),
                            metadata=item["metadata"],
                        )
                    )

            # Sort descending by score
            scored_results.sort(key=lambda x: x.score, reverse=True)
            return scored_results[:top_k]

    def delete_document(self, document_id: str, user_id: Optional[str] = None) -> int:
        with self._lock:
            keys_to_del = [
                cid
                for cid, item in self._items.items()
                if item["document_id"] == document_id and (not user_id or item.get("user_id") == user_id)
            ]
            for cid in keys_to_del:
                del self._items[cid]

            if document_id in self._documents:
                if not user_id or self._documents[document_id].get("user_id") == user_id:
                    del self._documents[document_id]

            if keys_to_del:
                self._save()
            return len(keys_to_del)

    def list_documents(self, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock:
            docs = []
            for doc in self._documents.values():
                if not user_id or doc.get("user_id") == user_id:
                    docs.append(dict(doc))
            return docs

    def _save(self) -> None:
        if not self._persistence_path:
            return
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self._persistence_path)), exist_ok=True)
            with open(self._persistence_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "items": self._items,
                        "documents": self._documents,
                    },
                    f,
                )
        except Exception as e:
            logger.warning(f"Could not persist vector store to disk: {e}")

    def _load(self) -> None:
        try:
            with open(self._persistence_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self._items = data.get("items", {})
                self._documents = data.get("documents", {})
        except Exception as e:
            logger.warning(f"Could not load vector store from disk: {e}")


class MongoAtlasVectorStore(BaseVectorStore):
    """MongoDB Atlas Vector Store implementation with fallback to LocalVectorStore."""

    def __init__(self, mongo_client=None, db_name="orbit_ai", collection_name="vector_embeddings"):
        self.mongo_client = mongo_client
        self.db_name = db_name or "orbit_ai"
        self.collection_name = collection_name
        self._fallback = LocalVectorStore()

    def add_chunks(
        self,
        chunks: List[DocumentChunk],
        embeddings: List[List[float]],
        user_id: str = "default_user",
    ) -> None:
        self._fallback.add_chunks(chunks, embeddings, user_id=user_id)
        if self.mongo_client:
            try:
                col = self.mongo_client[self.db_name][self.collection_name]
                docs = []
                for chunk, emb in zip(chunks, embeddings):
                    docs.append({
                        "_id": chunk.chunk_id,
                        "document_id": chunk.document_id,
                        "user_id": user_id,
                        "chunk_index": chunk.chunk_index,
                        "text": chunk.text,
                        "embedding": emb,
                        "metadata": chunk.metadata,
                    })
                if docs:
                    col.insert_many(docs, ordered=False)
            except Exception as e:
                logger.warning(f"MongoDB Atlas vector insert failed ({e}); local store active.")

    def search(
        self,
        query_embedding: List[float],
        top_k: int = 4,
        score_threshold: float = 0.0,
        user_id: Optional[str] = None,
        document_id: Optional[str] = None,
    ) -> List[SearchResult]:
        if self.mongo_client:
            try:
                col = self.mongo_client[self.db_name][self.collection_name]
                vector_search_stage: Dict[str, Any] = {
                    "index": "vector_index",
                    "path": "embedding",
                    "queryVector": query_embedding,
                    "numCandidates": max(top_k * 10, 20),
                    "limit": top_k,
                }

                # Build filter if user_id or document_id is supplied
                filter_doc: Dict[str, Any] = {}
                if user_id:
                    filter_doc["user_id"] = user_id
                if document_id:
                    filter_doc["document_id"] = document_id

                if filter_doc:
                    if len(filter_doc) == 1:
                        vector_search_stage["filter"] = filter_doc
                    else:
                        vector_search_stage["filter"] = {"$and": [{k: v} for k, v in filter_doc.items()]}

                pipeline = [
                    {"$vectorSearch": vector_search_stage},
                    {
                        "$project": {
                            "_id": 1,
                            "document_id": 1,
                            "user_id": 1,
                            "text": 1,
                            "metadata": 1,
                            "score": {"$meta": "vectorSearchScore"},
                        }
                    },
                ]
                cursor = col.aggregate(pipeline)
                results = []
                for doc in cursor:
                    if doc.get("score", 0.0) >= score_threshold:
                        results.append(
                            SearchResult(
                                chunk_id=doc["_id"],
                                document_id=doc["document_id"],
                                user_id=doc.get("user_id", "default_user"),
                                text=doc["text"],
                                score=float(doc.get("score", 0.0)),
                                metadata=doc.get("metadata", {}),
                            )
                        )
                if results:
                    return results
            except Exception as e:
                logger.warning(f"MongoDB Atlas vector search failed ({e}); falling back to local store.")
        return self._fallback.search(query_embedding, top_k, score_threshold, user_id, document_id)

    def delete_document(self, document_id: str, user_id: Optional[str] = None) -> int:
        if self.mongo_client:
            try:
                col = self.mongo_client[self.db_name][self.collection_name]
                query: Dict[str, Any] = {"document_id": document_id}
                if user_id:
                    query["user_id"] = user_id
                res = col.delete_many(query)
                return res.deleted_count
            except Exception as e:
                logger.warning(f"MongoDB Atlas vector delete failed ({e}); falling back to local store.")
        return self._fallback.delete_document(document_id, user_id)

    def list_documents(self, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        if self.mongo_client:
            try:
                col = self.mongo_client[self.db_name][self.collection_name]
                match = {"user_id": user_id} if user_id else {}
                pipeline = [
                    {"$match": match},
                    {
                        "$group": {
                            "_id": "$document_id",
                            "document_id": {"$first": "$document_id"},
                            "user_id": {"$first": "$user_id"},
                            "filename": {"$first": "$metadata.filename"},
                            "created_at": {"$first": "$metadata.created_at"},
                            "total_chunks": {"$sum": 1},
                        }
                    },
                ]
                docs = list(col.aggregate(pipeline))
                for d in docs:
                    d.pop("_id", None)
                    if not d.get("filename"):
                        d["filename"] = "Unknown"
                if docs:
                    return docs
            except Exception as e:
                logger.warning(f"MongoDB Atlas list_documents failed ({e}); using local store.")
        return self._fallback.list_documents(user_id)

