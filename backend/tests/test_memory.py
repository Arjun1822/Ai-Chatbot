import pytest
from memory.memory_store import MemoryStore
from memory.memory_manager import MemoryManager


def test_memory_store_crud():
    store = MemoryStore()
    item = store.add("user_1", "preference", "Prefers clean TypeScript and concise answers.", importance=4)
    assert item.id.startswith("mem_")
    assert item.category == "preference"

    # Read
    fetched = store.get(item.id, "user_1")
    assert fetched is not None
    assert fetched.content == "Prefers clean TypeScript and concise answers."

    # Update
    updated = store.update(item.id, "user_1", content="Prefers Python 3.12 and dataclasses.", importance=5)
    assert updated.content == "Prefers Python 3.12 and dataclasses."
    assert updated.importance == 5

    # Multi-user isolation
    assert store.get(item.id, "user_2") is None

    # Delete
    assert store.delete(item.id, "user_1") is True
    assert store.get(item.id, "user_1") is None


def test_memory_manager_retrieval_and_prompt_formatting():
    manager = MemoryManager(memory_store=MemoryStore())
    manager.add_memory("user_dev", "fact", "User name is Alex.", importance=5)
    manager.add_memory("user_dev", "preference", "Always use pytest for testing.", importance=4)
    manager.add_memory("user_dev", "project", "Working on ORBIT AI Agent platform.", importance=3)

    formatted = manager.format_system_memory_context("user_dev", "testing setup")
    assert "PERSISTENT USER MEMORY" in formatted
    assert "Alex" in formatted
    assert "pytest" in formatted

    # Other user gets empty context
    other_formatted = manager.format_system_memory_context("other_user")
    assert other_formatted == ""


def test_auto_extract_memories():
    manager = MemoryManager(memory_store=MemoryStore())
    extracted = manager.auto_extract_memories("u_auto", "Please remember that my favorite database is PostgreSQL.")
    assert len(extracted) >= 1
    assert any("postgresql" in e.content.lower() for e in extracted)
