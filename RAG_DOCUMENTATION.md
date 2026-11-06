# Retrieval-Augmented Generation (RAG) Architecture

## 1. Overview

ORBIT AI features an integrated, production-grade Retrieval-Augmented Generation (RAG) system that allows users to index knowledge documents and synthesize grounded, verifiable answers with exact source citations.

```
Document Upload (PDF, DOCX, TXT, MD, Code)
                    |
                    v
          DocumentExtractor
    - File format validation
    - Page/paragraph text extraction
    - Sanitization (10 MB cap)
                    |
                    v
             TextChunker
    - 500 character target size
    - 100 character overlap
    - Sentence/paragraph boundary snap
                    |
                    v
          EmbeddingService
    - Gemini text-embedding-004
    - Offline normalized fallback
    - Unit L2 vector normalization
                    |
                    v
            BaseVectorStore
    - LocalVectorStore (JSON Disk / RAM)
    - MongoAtlasVectorStore ($vectorSearch)
    - User ID isolation & index pruning
```

---

## 2. Ingestion Pipeline

### 2.1 File Format Extraction (`backend/rag/extractor.py`)
The `DocumentExtractor` supports:
- **PDF Documents** (`.pdf`): Multi-page text extraction via `pypdf.PdfReader` with page-level metadata.
- **Word Documents** (`.docx`): Paragraph extraction via `python-docx` preserving text flow.
- **Plaintext & Source Code** (`.txt`, `.md`, `.py`, `.js`, `.json`, `.sql`, `.html`, etc.): Multi-encoding Unicode extraction (`utf-8`, `latin-1`).
- **Security Constraints**: Maximum upload size is strictly capped at 10 MB per file. Executables and unsupported formats are rejected with HTTP 400.

### 2.2 Boundary-Preserving Text Chunking (`backend/rag/chunker.py`)
The `TextChunker` segments extracted text into semantic windows:
- **Default Chunk Size**: 500 characters.
- **Overlap**: 100 characters.
- **Boundary Detection**: Rather than splitting words or sentences abruptly, the chunker snaps boundaries to paragraph breaks (`\n\n`), sentence boundaries (`. `, `? `, `! `), or space delimiters when available in the latter half of the window.

### 2.3 Vector Embedding Generation (`backend/rag/embeddings.py`)
- **Primary Model**: Google GenAI `text-embedding-004` (producing 768-dimensional embeddings).
- **Offline / Test Resiliency**: If `GEMINI_API_KEY` is not present, or if external API quotas are exhausted, a deterministic bag-of-tokens L2-normalized dense vectorizer (256 dimensions) takes over seamlessly without halting execution.
- **L2 Normalization**: All vectors are unit-normalized upon generation:
  $$\|v\|_2 = \sqrt{\sum_{i=1}^n v_i^2} = 1.0$$
  This optimizes retrieval because cosine similarity reduces to a fast dot product:
  $$\text{sim}(q, d) = q \cdot d$$

---

## 3. Storage & Retrieval

### 3.1 Vector Stores (`backend/rag/vector_store.py`)
- **`LocalVectorStore`**: Thread-safe in-memory index protected by reentrant locks (`threading.RLock`) with JSON persistence to `backend/data/vector_store.json`. Ideal for standalone, local, and edge deployments.
- **`MongoAtlasVectorStore`**: Integrates with MongoDB Atlas `$vectorSearch` pipeline for high-scale enterprise deployments, automatically falling back to `LocalVectorStore` if Atlas is inactive.

### 3.2 User Multi-Tenant Isolation
All vectors stored include a mandatory `user_id` attribute. When a query is executed, candidates belonging to other users are strictly pruned before scoring, preventing cross-tenant information leakage (IDOR prevention).

---

## 4. Citation Generation & Output Format

When an answer is synthesized in `document` mode:
1. Retrieved document chunks are formatted into the LLM system context with source identifiers:
   ```
   [Source 1 | File: architecture.pdf | Chunk: 3]
   The vector store enforces user isolation using tenant identifiers...
   ```
2. The LLM is instructed to cite sources using bracket notation `[Source N]`.
3. In the final `done` SSE stream event, structured citation metadata is returned:
   ```json
   {
     "citations": [
       {
         "source_number": 1,
         "document_id": "doc_a4f918bc2210",
         "filename": "architecture.pdf",
         "score": 0.9412,
         "snippet": "The vector store enforces user isolation using tenant identifiers..."
       }
     ]
   }
   ```
4. The React client renders interactive citation badges under the assistant response, allowing the user to click and inspect the underlying text chunk.
