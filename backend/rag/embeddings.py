import hashlib
import logging
import math
import os
import re
from typing import List, Optional

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Embedding service generating vector embeddings using Google GenAI or local fallback."""

    EMBEDDING_MODEL = os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001")
    FALLBACK_DIMENSION = 256

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self._client = None
        if self.api_key:
            try:
                from google import genai
                self._client = genai.Client(api_key=self.api_key)
            except Exception as e:
                logger.warning(f"Could not initialize GenAI client for embeddings: {e}")
                self._client = None

    def embed_text(self, text: str) -> List[float]:
        """Generate embedding vector for a single string."""
        if not text:
            return [0.0] * self.FALLBACK_DIMENSION

        if self._client:
            try:
                response = self._client.models.embed_content(
                    model=self.EMBEDDING_MODEL,
                    contents=text,
                )
                if hasattr(response, "embeddings") and response.embeddings:
                    values = response.embeddings[0].values
                    return self._l2_normalize(values)
            except Exception as e:
                logger.warning(f"GenAI embedding call failed ({e}); using deterministic fallback.")

        return self._fallback_embed(text)

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for a list of texts."""
        if not texts:
            return []

        if self._client:
            try:
                response = self._client.models.embed_content(
                    model=self.EMBEDDING_MODEL,
                    contents=texts,
                )
                if hasattr(response, "embeddings") and len(response.embeddings) == len(texts):
                    return [self._l2_normalize(emb.values) for emb in response.embeddings]
            except Exception as e:
                logger.warning(f"GenAI batch embedding call failed ({e}); falling back to batch local embed.")

        return [self._fallback_embed(t) for t in texts]

    def _fallback_embed(self, text: str) -> List[float]:
        """Deterministic dense token hashing embedding for offline/testing/fallback environments."""
        vector = [0.0] * self.FALLBACK_DIMENSION
        tokens = re.findall(r"\w+", text.lower())
        if not tokens:
            return vector

        # Bag of hashed n-grams & tokens
        for token in tokens:
            h = int(hashlib.sha256(token.encode("utf-8")).hexdigest(), 16)
            idx = h % self.FALLBACK_DIMENSION
            weight = 1.0 + (len(token) / 10.0)
            vector[idx] += weight

        # Substring 3-grams for partial match
        clean = re.sub(r"\s+", " ", text.lower().strip())
        for i in range(len(clean) - 2):
            trigram = clean[i:i+3]
            h = int(hashlib.md5(trigram.encode("utf-8")).hexdigest(), 16)
            idx = h % self.FALLBACK_DIMENSION
            vector[idx] += 0.3

        return self._l2_normalize(vector)

    @staticmethod
    def _l2_normalize(vec: List[float]) -> List[float]:
        norm = math.sqrt(sum(v * v for v in vec))
        if norm <= 1e-9:
            return vec
        return [v / norm for v in vec]

