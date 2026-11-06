from dataclasses import dataclass
from typing import Dict, List


@dataclass
class DocumentChunk:
    chunk_id: str
    document_id: str
    chunk_index: int
    text: str
    char_start: int
    char_end: int
    metadata: Dict[str, any]


class TextChunker:
    """Configurable text chunker preserving paragraph and sentence boundaries with overlap."""

    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 100):
        if chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be strictly less than chunk_size.")
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def chunk_document(self, document_id: str, text: str, doc_metadata: dict) -> List[DocumentChunk]:
        if not text or not text.strip():
            return []

        clean_text = text.strip()
        chunks: List[DocumentChunk] = []
        start = 0
        text_len = len(clean_text)
        chunk_index = 0

        while start < text_len:
            end = min(start + self.chunk_size, text_len)

            # Try to snap end to a paragraph or sentence boundary if not at end of text
            if end < text_len:
                boundary = self._find_boundary(clean_text, start, end)
                if boundary > start + (self.chunk_size // 2):
                    end = boundary

            chunk_text = clean_text[start:end].strip()
            if chunk_text:
                chunk_id = f"{document_id}_chunk_{chunk_index}"
                chunk_meta = dict(doc_metadata)
                chunk_meta.update({
                    "chunk_index": chunk_index,
                    "char_length": len(chunk_text),
                })
                chunks.append(
                    DocumentChunk(
                        chunk_id=chunk_id,
                        document_id=document_id,
                        chunk_index=chunk_index,
                        text=chunk_text,
                        char_start=start,
                        char_end=end,
                        metadata=chunk_meta,
                    )
                )
                chunk_index += 1

            if end >= text_len:
                break

            # Advance by step size (chunk_size - chunk_overlap)
            step = max(1, (end - start) - self.chunk_overlap)
            start += step

        return chunks

    def _find_boundary(self, text: str, start: int, end: int) -> int:
        segment = text[start:end]
        # Look for paragraph break
        p_break = segment.rfind("\n\n")
        if p_break != -1:
            return start + p_break + 2
        # Look for sentence break (. ! ?)
        for sep in [". ", "? ", "! ", "\n"]:
            s_break = segment.rfind(sep)
            if s_break != -1:
                return start + s_break + len(sep)
        # Look for space
        space = segment.rfind(" ")
        if space != -1:
            return start + space + 1
        return end
