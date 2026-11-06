from copy import deepcopy
from datetime import datetime, timezone
from threading import Lock
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
        self._lock = Lock()
        if getattr(config, "MONGODB_URI", ""):
            try:
                from pymongo import MongoClient
                client = MongoClient(config.MONGODB_URI, serverSelectionTimeoutMS=1500)
                client.admin.command("ping")
                self.collection = client[config.DATABASE_NAME].conversations
                self.collection.create_index("updated_at")
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

    def create(self, title="New conversation"):
        timestamp = now()
        safe_title = (title or "New conversation").strip()[:100]
        conversation = {
            "_id": str(uuid4()),
            "title": safe_title,
            "messages": [],
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        if self.collection is not None:
            self.collection.insert_one(conversation)
        else:
            with self._lock:
                # Evict oldest conversation if memory limit reached
                if len(self._items) >= self.MAX_IN_MEMORY_CONVERSATIONS:
                    oldest_id = min(self._items.keys(), key=lambda k: self._items[k]["updated_at"])
                    self._items.pop(oldest_id, None)
                self._items[conversation["_id"]] = conversation
        return serialize(conversation)

    def list(self):
        if self.collection is not None:
            items = self.collection.find({}, {"messages": 0}).sort("updated_at", -1)
            return [serialize(item) for item in items]
        with self._lock:
            sorted_items = sorted(
                self._items.values(),
                key=lambda x: x["updated_at"] if isinstance(x["updated_at"], datetime) else datetime.fromisoformat(x["updated_at"]),
                reverse=True,
            )
            # Exclude full messages in listing for performance
            summary_items = []
            for item in sorted_items:
                s = serialize(item)
                s.pop("messages", None)
                summary_items.append(s)
            return summary_items

    def get(self, conversation_id):
        if self.collection is not None:
            item = self.collection.find_one({"_id": conversation_id})
        else:
            with self._lock:
                item = self._items.get(conversation_id)
        return serialize(item) if item else None

    def delete(self, conversation_id):
        if self.collection is not None:
            return self.collection.delete_one({"_id": conversation_id}).deleted_count == 1
        with self._lock:
            return self._items.pop(conversation_id, None) is not None

    def append_messages(self, conversation_id, messages, title=None):
        timestamp = now()
        update_fields = {"updated_at": timestamp}
        if title:
            update_fields["title"] = title.strip()[:100]

        if self.collection is not None:
            update = {"$push": {"messages": {"$each": messages}}, "$set": update_fields}
            result = self.collection.update_one({"_id": conversation_id}, update)
            if result.matched_count == 0:
                return None
        else:
            with self._lock:
                item = self._items.get(conversation_id)
                if not item:
                    return None
                item["messages"].extend(deepcopy(messages))
                item["updated_at"] = timestamp
                if title:
                    item["title"] = title.strip()[:100]

        return self.get(conversation_id)

    def update_metadata(self, conversation_id, data):
        allowed = {}
        if "title" in data and isinstance(data["title"], str) and data["title"].strip():
            allowed["title"] = data["title"].strip()[:100]

        if not allowed:
            return self.get(conversation_id)

        timestamp = now()
        allowed["updated_at"] = timestamp

        if self.collection is not None:
            result = self.collection.update_one({"_id": conversation_id}, {"$set": allowed})
            return self.get(conversation_id) if result.matched_count else None
        with self._lock:
            item = self._items.get(conversation_id)
            if not item:
                return None
            item.update(allowed)
            return serialize(item)
