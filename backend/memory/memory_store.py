import json
import logging
import os
import threading
from typing import Any, Dict, List, Optional
import uuid
from datetime import datetime, timezone

from memory.models import MemoryItem

logger = logging.getLogger(__name__)


class MemoryStore:
    """Thread-safe persistent memory store supporting local JSON and MongoDB."""

    def __init__(self, persistence_path: Optional[str] = None, mongo_client=None, db_name="orbit_ai"):
        self._lock = threading.RLock()
        self.persistence_path = persistence_path
        self.mongo_client = mongo_client
        self.db_name = db_name or "orbit_ai"
        self._memories: Dict[str, MemoryItem] = {}  # id -> MemoryItem

        if persistence_path and os.path.exists(persistence_path):
            self._load()

        if self.mongo_client:
            try:
                col = self.mongo_client[self.db_name]["user_memories"]
                col.create_index([("user_id", 1), ("category", 1)])
                col.create_index([("user_id", 1), ("importance", -1)])
            except Exception as e:
                logger.warning(f"Could not initialize MongoDB user_memories indexes: {e}")

    def add(self, user_id: str, category: str, content: str, importance: int = 3) -> MemoryItem:
        if not content or not content.strip():
            raise ValueError("Memory content cannot be empty.")

        item = MemoryItem(
            id=f"mem_{uuid.uuid4().hex[:12]}",
            user_id=user_id,
            category=category.strip().lower(),
            content=content.strip(),
            importance=max(1, min(5, int(importance))),
        )

        with self._lock:
            self._memories[item.id] = item
            self._save()

        if self.mongo_client:
            try:
                col = self.mongo_client[self.db_name]["user_memories"]
                col.replace_one({"_id": item.id}, {**item.to_dict(), "_id": item.id}, upsert=True)
            except Exception as e:
                logger.warning(f"MongoDB memory sync failed: {e}")

        return item

    def get(self, memory_id: str, user_id: Optional[str] = None) -> Optional[MemoryItem]:
        with self._lock:
            item = self._memories.get(memory_id)
            if item and (not user_id or item.user_id == user_id):
                return item
            return None

    def list_by_user(self, user_id: str, category: Optional[str] = None) -> List[MemoryItem]:
        if self.mongo_client:
            try:
                col = self.mongo_client[self.db_name]["user_memories"]
                query: Dict[str, Any] = {"user_id": user_id}
                if category:
                    query["category"] = category.lower()
                docs = list(col.find(query).sort([("importance", -1), ("updated_at", -1)]))
                if docs:
                    return [MemoryItem.from_dict({k: v for k, v in d.items() if k != "_id"}) for d in docs]
            except Exception:
                pass

        with self._lock:
            results = [
                m for m in self._memories.values()
                if m.user_id == user_id and (not category or m.category == category.lower())
            ]
            results.sort(key=lambda m: (m.importance, m.updated_at), reverse=True)
            return results

    def update(
        self,
        memory_id: str,
        user_id: str,
        content: Optional[str] = None,
        category: Optional[str] = None,
        importance: Optional[int] = None,
    ) -> Optional[MemoryItem]:
        with self._lock:
            item = self._memories.get(memory_id)
            if not item or item.user_id != user_id:
                return None

            if content is not None:
                item.content = content.strip()
            if category is not None:
                item.category = category.strip().lower()
            if importance is not None:
                item.importance = max(1, min(5, int(importance)))

            item.updated_at = datetime.now(timezone.utc).isoformat()
            self._save()

            if self.mongo_client:
                try:
                    col = self.mongo_client[self.db_name]["user_memories"]
                    col.update_one(
                        {"_id": memory_id, "user_id": user_id},
                        {"$set": item.to_dict()},
                    )
                except Exception as e:
                    logger.warning(f"MongoDB memory update failed: {e}")

            return item

    def delete(self, memory_id: str, user_id: str) -> bool:
        with self._lock:
            item = self._memories.get(memory_id)
            if not item or item.user_id != user_id:
                return False

            del self._memories[memory_id]
            self._save()

            if self.mongo_client:
                try:
                    col = self.mongo_client[self.db_name]["user_memories"]
                    col.delete_one({"_id": memory_id, "user_id": user_id})
                except Exception as e:
                    logger.warning(f"MongoDB memory delete failed: {e}")

            return True

    def clear_user(self, user_id: str) -> int:
        with self._lock:
            keys_to_del = [mid for mid, m in self._memories.items() if m.user_id == user_id]
            for mid in keys_to_del:
                del self._memories[mid]
            self._save()

            if self.mongo_client:
                try:
                    col = self.mongo_client[self.db_name]["user_memories"]
                    col.delete_many({"user_id": user_id})
                except Exception as e:
                    logger.warning(f"MongoDB clear memories failed: {e}")

            return len(keys_to_del)

    def _save(self) -> None:
        if not self.persistence_path:
            return
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.persistence_path)), exist_ok=True)
            with open(self.persistence_path, "w", encoding="utf-8") as f:
                data = {mid: m.to_dict() for mid, m in self._memories.items()}
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to persist memories to {self.persistence_path}: {e}")

    def _load(self) -> None:
        try:
            with open(self.persistence_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self._memories = {mid: MemoryItem.from_dict(v) for mid, v in data.items()}
        except Exception as e:
            logger.warning(f"Failed to load memories from {self.persistence_path}: {e}")

