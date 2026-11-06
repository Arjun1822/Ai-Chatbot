import logging
import os
import re
from typing import List, Optional

from memory.memory_store import MemoryStore
from memory.models import MemoryItem

logger = logging.getLogger(__name__)


class MemoryManager:
    """Manages AI memory retrieval, formatting, and automatic preference extraction."""

    EXTRACTION_PATTERNS = [
        (r"(?:remember that|note that|please remember|don't forget that)\s+(.*)", "fact", 4),
        (r"(?:my name is|i am called|call me)\s+([A-Za-z0-9_\-\s]{2,30})", "fact", 4),
        (r"(?:i prefer|i like|i always use|my favorite)\s+(.*)", "preference", 3),
        (r"(?:i am working on|my project is|current project is)\s+(.*)", "project", 3),
        (r"(?:never|always|do not)\s+([a-z0-9\s]{5,60})", "instruction", 4),
    ]

    def __init__(self, memory_store: Optional[MemoryStore] = None, data_dir: Optional[str] = None):
        base_dir = data_dir or os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
        persistence_path = os.path.join(base_dir, "memories.json")
        self.store = memory_store or MemoryStore(persistence_path=persistence_path)

    def add_memory(self, user_id: str, category: str, content: str, importance: int = 3) -> MemoryItem:
        return self.store.add(user_id, category, content, importance)

    def get_user_memories(self, user_id: str, category: Optional[str] = None) -> List[MemoryItem]:
        return self.store.list_by_user(user_id, category)

    def update_memory(
        self,
        memory_id: str,
        user_id: str,
        content: Optional[str] = None,
        category: Optional[str] = None,
        importance: Optional[int] = None,
    ) -> Optional[MemoryItem]:
        return self.store.update(memory_id, user_id, content, category, importance)

    def delete_memory(self, memory_id: str, user_id: str) -> bool:
        return self.store.delete(memory_id, user_id)

    def clear_user_memories(self, user_id: str) -> int:
        return self.store.clear_user(user_id)

    def retrieve_relevant_memories(
        self, user_id: str, query: Optional[str] = None, limit: int = 6
    ) -> List[MemoryItem]:
        memories = self.store.list_by_user(user_id)
        if not memories:
            return []

        if not query or not query.strip():
            return memories[:limit]

        query_tokens = set(re.findall(r"\w+", query.lower()))
        scored = []
        for mem in memories:
            mem_tokens = set(re.findall(r"\w+", mem.content.lower()))
            overlap = len(query_tokens.intersection(mem_tokens))
            score = (overlap * 2.0) + (mem.importance * 0.5)
            scored.append((score, mem))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [m for _, m in scored[:limit]]

    def format_system_memory_context(self, user_id: str, query: Optional[str] = None) -> str:
        relevant = self.retrieve_relevant_memories(user_id, query, limit=5)
        if not relevant:
            return ""

        lines = ["[PERSISTENT USER MEMORY & PREFERENCES]"]
        for m in relevant:
            lines.append(f"- [{m.category.upper()}] {m.content}")
        return "\n".join(lines)

    def auto_extract_memories(self, user_id: str, message: str) -> List[MemoryItem]:
        """Optionally detect explicit user statements about preferences/identity."""
        if not message or len(message) > 500:
            return []

        extracted = []
        for pattern, cat, imp in self.EXTRACTION_PATTERNS:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                fact_str = match.group(1).strip().rstrip(".,!")
                if fact_str.lower().startswith("that "):
                    fact_str = fact_str[5:].strip()
                if len(fact_str) >= 3:
                    # Check for duplicates
                    existing = self.store.list_by_user(user_id, category=cat)
                    if not any(fact_str.lower() in e.content.lower() for e in existing):
                        item = self.store.add(user_id, cat, fact_str, imp)
                        extracted.append(item)
        return extracted
