import time
import logging
from typing import Generator, List, Dict, Any, Tuple
from google import genai
from google.genai import types
from google.genai.errors import APIError

logger = logging.getLogger(__name__)


class LLMService:
    def __init__(self, config):
        self.model = getattr(config, "GEMINI_MODEL", "gemini-3.5-flash-lite")
        self.system_prompt = getattr(
            config,
            "SYSTEM_PROMPT",
            "You are Orbit, an intelligent, helpful, and concise AI assistant.",
        )
        api_key = getattr(config, "GEMINI_API_KEY", "")
        self.client = genai.Client(api_key=api_key) if api_key else None

    @property
    def configured(self) -> bool:
        return self.client is not None

    def _build_contents(self, messages: List[Dict[str, Any]]) -> List[types.Content]:
        contents = []
        for message in messages:
            role = "user" if message.get("role") == "user" else "model"
            content_text = str(message.get("content", ""))
            contents.append(
                types.Content(
                    role=role,
                    parts=[types.Part.from_text(text=content_text)],
                )
            )
        return contents

    def _extract_text_and_meta(self, response, elapsed_ms: int) -> Tuple[str, Dict[str, Any]]:
        text_parts = []
        if response.candidates:
            for candidate in response.candidates:
                if candidate.content and candidate.content.parts:
                    for part in candidate.content.parts:
                        if hasattr(part, "text") and part.text:
                            text_parts.append(part.text)
        
        extracted_text = "".join(text_parts).strip() if text_parts else (response.text or "I was unable to generate a response.").strip()

        usage = getattr(response, "usage_metadata", None)
        meta = {
            "model": self.model,
            "latency_ms": elapsed_ms,
            "prompt_tokens": getattr(usage, "prompt_token_count", None) if usage else None,
            "candidates_tokens": getattr(usage, "candidates_token_count", None) if usage else None,
            "total_tokens": getattr(usage, "total_token_count", None) if usage else None,
        }
        return extracted_text, meta

    def generate(self, messages: List[Dict[str, Any]], max_retries: int = 2) -> Tuple[str, Dict[str, Any]]:
        """Generate response with exponential backoff on transient errors."""
        if not self.client:
            raise RuntimeError("GEMINI_API_KEY is not configured. Add it to backend/.env to enable AI responses.")

        contents = self._build_contents(messages)
        start_time = time.monotonic()
        last_error = None

        for attempt in range(max_retries + 1):
            try:
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=self.system_prompt,
                        temperature=0.7,
                    ),
                )
                elapsed_ms = int((time.monotonic() - start_time) * 1000)
                return self._extract_text_and_meta(response, elapsed_ms)
            except APIError as api_err:
                last_error = api_err
                status_code = getattr(api_err, "code", 500)
                # Retry on 429 (rate limit) or 503 (service unavailable)
                if status_code in (429, 503) and attempt < max_retries:
                    wait_sec = (attempt + 1) * 1.5
                    logger.warning(f"Gemini API rate/transient error ({status_code}). Retrying in {wait_sec}s...")
                    time.sleep(wait_sec)
                    continue
                raise
            except Exception as e:
                last_error = e
                if attempt < max_retries:
                    time.sleep(1.0)
                    continue
                raise

        raise last_error or RuntimeError("Failed to generate response after retries.")

    def stream_response(self, messages: List[Dict[str, Any]], system_instruction: str = None) -> Generator[Dict[str, Any], None, None]:
        """Stream chunks with custom system instruction for agent/RAG orchestrators."""
        if not self.client:
            raise RuntimeError("GEMINI_API_KEY is not configured. Add it to backend/.env to enable AI responses.")

        contents = self._build_contents(messages)
        start_time = time.monotonic()
        sys_prompt = system_instruction if system_instruction is not None else self.system_prompt

        response_stream = self.client.models.generate_content_stream(
            model=self.model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=sys_prompt,
                temperature=0.7,
            ),
        )

        accumulated_text = []
        for chunk in response_stream:
            chunk_text = ""
            if chunk.candidates:
                for candidate in chunk.candidates:
                    if candidate.content and candidate.content.parts:
                        for part in candidate.content.parts:
                            if hasattr(part, "text") and part.text:
                                chunk_text += part.text
            elif hasattr(chunk, "text") and chunk.text:
                chunk_text = chunk.text

            if chunk_text:
                accumulated_text.append(chunk_text)
                yield {"type": "chunk", "text": chunk_text, "content": chunk_text}

        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        yield {
            "type": "done",
            "content": "".join(accumulated_text),
            "full_text": "".join(accumulated_text),
            "meta": {
                "model": self.model,
                "latency_ms": elapsed_ms,
            },
        }

    def generate_stream(self, messages: List[Dict[str, Any]]) -> Generator[Dict[str, Any], None, None]:
        """Stream chunks as they are generated by the Gemini API."""
        return self.stream_response(messages)
