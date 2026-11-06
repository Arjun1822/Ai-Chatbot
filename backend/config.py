import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from backend folder or current working directory
_backend_env = Path(__file__).resolve().parent / ".env"
if _backend_env.exists():
    load_dotenv(_backend_env)
else:
    load_dotenv()


class Config:
    SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev-only-change-me")
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
    MONGODB_URI = os.getenv("MONGODB_URI", "")
    DATABASE_NAME = os.getenv("DATABASE_NAME", "ai_chat_db")

    # Allow multiple origins separated by comma (e.g. http://localhost:3000,http://localhost:5173)
    _frontend_env = os.getenv(
        "FRONTEND_URL",
        "http://localhost:3000,http://localhost:5173,http://127.0.0.1:3000,http://127.0.0.1:5173",
    )
    FRONTEND_URLS = [origin.strip() for origin in _frontend_env.split(",") if origin.strip()]
    FRONTEND_URL = FRONTEND_URLS[0] if FRONTEND_URLS else "http://localhost:3000"

    MAX_CONTEXT_MESSAGES = int(os.getenv("MAX_CONTEXT_MESSAGES", "16"))
    MAX_MESSAGE_LENGTH = int(os.getenv("MAX_MESSAGE_LENGTH", "8000"))
    MAX_ATTACHMENT_SIZE_BYTES = int(os.getenv("MAX_ATTACHMENT_SIZE_BYTES", "102400"))  # 100 KB text

    RATE_LIMIT_REQUESTS = int(os.getenv("RATE_LIMIT_REQUESTS", "60"))
    RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))

    SYSTEM_PROMPT = os.getenv(
        "SYSTEM_PROMPT",
        "You are Orbit, an intelligent, helpful, and concise AI assistant. "
        "Provide direct, high-quality answers formatted in clean Markdown. "
        "Use GitHub Flavored Markdown (tables, task lists, code fences with language tags) when relevant. "
        "Maintain clarity, acknowledge assumptions when requirements are ambiguous, and be objective and polite.",
    )
