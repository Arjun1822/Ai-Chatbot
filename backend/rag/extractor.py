import io
import os
from typing import Dict, List, Tuple


class DocumentExtractionException(Exception):
    pass


class DocumentExtractor:
    """Safe text extractor supporting PDF, DOCX, TXT, Markdown, and source code files."""

    SUPPORTED_EXTENSIONS = {
        ".pdf",
        ".docx",
        ".txt",
        ".md",
        ".markdown",
        ".py",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".json",
        ".csv",
        ".html",
        ".css",
        ".yaml",
        ".yml",
        ".sql",
    }

    MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB upload ceiling

    @classmethod
    def extract_text(cls, filename: str, file_bytes: bytes) -> Tuple[str, Dict[str, any]]:
        if not file_bytes:
            raise DocumentExtractionException("File is empty (0 bytes).")

        if len(file_bytes) > cls.MAX_FILE_SIZE_BYTES:
            raise DocumentExtractionException(
                f"File size exceeds maximum allowed limit of {cls.MAX_FILE_SIZE_BYTES // (1024*1024)} MB."
            )

        _, ext = os.path.splitext(filename.lower())
        if ext not in cls.SUPPORTED_EXTENSIONS:
            raise DocumentExtractionException(
                f"Unsupported file format '{ext}'. Supported formats: {', '.join(sorted(cls.SUPPORTED_EXTENSIONS))}"
            )

        metadata = {
            "filename": filename,
            "extension": ext,
            "byte_size": len(file_bytes),
        }

        if ext == ".pdf":
            return cls._extract_pdf(file_bytes, metadata)
        elif ext == ".docx":
            return cls._extract_docx(file_bytes, metadata)
        else:
            return cls._extract_plain_text(file_bytes, metadata)

    @classmethod
    def _extract_pdf(cls, file_bytes: bytes, metadata: dict) -> Tuple[str, dict]:
        try:
            import pypdf
            reader = pypdf.PdfReader(io.BytesIO(file_bytes))
            pages_text = []
            for i, page in enumerate(reader.pages):
                text = page.extract_text() or ""
                if text.strip():
                    pages_text.append(text.strip())

            full_text = "\n\n".join(pages_text).strip()
            if not full_text:
                raise DocumentExtractionException("PDF contains no extractable text (may be image-only or scanned).")

            metadata["page_count"] = len(reader.pages)
            return full_text, metadata
        except DocumentExtractionException:
            raise
        except Exception as e:
            raise DocumentExtractionException(f"Failed to parse PDF document: {str(e)}")

    @classmethod
    def _extract_docx(cls, file_bytes: bytes, metadata: dict) -> Tuple[str, dict]:
        try:
            import docx
            doc = docx.Document(io.BytesIO(file_bytes))
            paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
            full_text = "\n\n".join(paragraphs).strip()
            if not full_text:
                raise DocumentExtractionException("DOCX file contains no extractable text paragraphs.")

            metadata["paragraph_count"] = len(paragraphs)
            return full_text, metadata
        except DocumentExtractionException:
            raise
        except Exception as e:
            raise DocumentExtractionException(f"Failed to parse DOCX document: {str(e)}")

    @classmethod
    def _extract_plain_text(cls, file_bytes: bytes, metadata: dict) -> Tuple[str, dict]:
        try:
            text = file_bytes.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text = file_bytes.decode("latin-1")
            except Exception as e:
                raise DocumentExtractionException(f"Failed to decode text file: {str(e)}")

        clean_text = text.strip()
        if not clean_text:
            raise DocumentExtractionException("Text file contains no readable content.")

        metadata["line_count"] = len(clean_text.splitlines())
        return clean_text, metadata
