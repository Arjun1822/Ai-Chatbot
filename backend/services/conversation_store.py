from copy import deepcopy
from datetime import datetime, timezone
from threading import RLock
from typing import Any, Dict, List, Optional
from uuid import uuid4


def now():
    return datetime.now(timezone.utc)


def serialize(conversation):
    if not conversation:
        return None
    result = deepcopy(conversation)
    for key in ("created_at", "updated_at"):
        if isinstance(result.get(key), datetime):
            result[key] = result[key].isoformat()
    # Normalize messages created_at if datetime
    if "messages" in result and isinstance(result["messages"], list):
        for msg in result["messages"]:
            if isinstance(msg.get("created_at"), datetime):
                msg["created_at"] = msg["created_at"].isoformat()
    return result


class ConversationStore:
    MAX_IN_MEMORY_CONVERSATIONS = 1000

    def __init__(self, config):
        self.collection = None
        self._items = {}
        self._lock = RLock()
        if getattr(config, "MONGODB_URI", ""):
            try:
                from pymongo import MongoClient
                client = MongoClient(config.MONGODB_URI, serverSelectionTimeoutMS=1500)
                client.admin.command("ping")
                self.collection = client[config.DATABASE_NAME].conversations
                self.collection.create_index("updated_at")
                self.collection.create_index("user_id")
            except Exception:
                self.collection = None

    @property
    def using_mongodb(self):
        return self.collection is not None

    def health(self):
        if self.collection is None:
            return False
        try:
            self.collection.database.client.admin.command("ping")
            return True
        except Exception:
            return False

    def create(self, title="New conversation", user_id="default_user"):
        timestamp = now()
        safe_title = (title or "New conversation").strip()[:100]
        conversation = {
            "_id": str(uuid4()),
            "user_id": user_id or "default_user",
            "title": safe_title,
            "messages": [],
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        if self.collection is not None:
            self.collection.insert_one(conversation)
        else:
            with self._lock:
                if len(self._items) >= self.MAX_IN_MEMORY_CONVERSATIONS:
                    oldest_id = min(self._items.keys(), key=lambda k: self._items[k]["updated_at"])
                    self._items.pop(oldest_id, None)
                self._items[conversation["_id"]] = conversation
        return serialize(conversation)

    def list(self, user_id=None):
        if self.collection is not None:
            query = {"user_id": user_id} if user_id else {}
            items = self.collection.find(query, {"messages": 0}).sort("updated_at", -1)
            return [serialize(item) for item in items]
        with self._lock:
            all_items = self._items.values()
            if user_id:
                all_items = [
                    x for x in all_items
                    if x.get("user_id") == user_id or "user_id" not in x
                ]
            sorted_items = sorted(
                all_items,
                key=lambda x: x["updated_at"] if isinstance(x["updated_at"], datetime) else datetime.fromisoformat(x["updated_at"]),
                reverse=True,
            )
            summary_items = []
            for item in sorted_items:
                s = serialize(item)
                s.pop("messages", None)
                summary_items.append(s)
            return summary_items

    def get(self, conversation_id, user_id=None):
        if self.collection is not None:
            query = {"_id": conversation_id}
            if user_id:
                query["user_id"] = user_id
            item = self.collection.find_one(query)
        else:
            with self._lock:
                item = self._items.get(conversation_id)
                if item and user_id and item.get("user_id") and item.get("user_id") != user_id:
                    item = None
        return serialize(item) if item else None

    def delete(self, conversation_id, user_id=None):
        if self.collection is not None:
            query = {"_id": conversation_id}
            if user_id:
                query["user_id"] = user_id
            return self.collection.delete_one(query).deleted_count == 1
        with self._lock:
            item = self._items.get(conversation_id)
            if not item:
                return False
            if user_id and item.get("user_id") and item.get("user_id") != user_id:
                return False
            return self._items.pop(conversation_id, None) is not None

    def append_messages(self, conversation_id, messages, title=None, user_id=None):
        timestamp = now()
        update_fields = {"updated_at": timestamp}
        if title:
            update_fields["title"] = title.strip()[:100]

        if self.collection is not None:
            query = {"_id": conversation_id}
            if user_id:
                query["user_id"] = user_id
            update = {"$push": {"messages": {"$each": messages}}, "$set": update_fields}
            result = self.collection.update_one(query, update)
            if result.matched_count == 0:
                return None
        else:
            with self._lock:
                item = self._items.get(conversation_id)
                if not item:
                    return None
                if user_id and item.get("user_id") and item.get("user_id") != user_id:
                    return None
                item["messages"].extend(deepcopy(messages))
                item["updated_at"] = timestamp
                if title:
                    item["title"] = title.strip()[:100]

        return self.get(conversation_id, user_id=user_id)

    def update_metadata(self, conversation_id, data, user_id=None):
        allowed = {}
        if "title" in data and isinstance(data["title"], str) and data["title"].strip():
            allowed["title"] = data["title"].strip()[:100]

        if not allowed:
            return self.get(conversation_id, user_id=user_id)

        timestamp = now()
        allowed["updated_at"] = timestamp

        if self.collection is not None:
            query = {"_id": conversation_id}
            if user_id:
                query["user_id"] = user_id
            result = self.collection.update_one(query, {"$set": allowed})
            return self.get(conversation_id, user_id=user_id) if result.matched_count else None
        with self._lock:
            item = self._items.get(conversation_id)
            if not item:
                return None
            if user_id and item.get("user_id") and item.get("user_id") != user_id:
                return None
            item.update(allowed)
            return self.get(conversation_id, user_id=user_id)
