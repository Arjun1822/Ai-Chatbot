import os
import pytest
from config import Config


@pytest.fixture(autouse=True)
def isolate_test_environment(monkeypatch):
    """Ensure all unit tests run in an isolated test environment unless explicitly testing production."""
    monkeypatch.setattr(Config, "MONGODB_URI", "")
    monkeypatch.setattr(Config, "FLASK_ENV", "test")
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.delenv("RENDER_SERVICE_ID", raising=False)
