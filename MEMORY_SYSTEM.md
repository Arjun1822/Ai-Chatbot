# Persistent AI Memory System

## 1. Overview

ORBIT AI features an explicit, persistent multi-tier memory system enabling the AI assistant to remember user preferences, architectural rules, personal facts, and project details across sessions and conversations.

---

## 2. Memory Tiers

```
+-------------------------------------------------------------------------+
| Short-Term Memory    | Active conversation history (last N turns)       |
+-------------------------------------------------------------------------+
| Long-Term Memory     | User preferences, instructions, verified facts   |
+-------------------------------------------------------------------------+
| Episodic Memory      | Summarized highlights from past sessions         |
+-------------------------------------------------------------------------+
```

---

## 3. Data Model & Schema

Every stored memory is represented by a structured `MemoryItem` (`backend/memory/models.py`):

| Field | Type | Description |
| :--- | :--- | :--- |
| `id` | `str` | Unique memory identifier (e.g. `mem_f89c0a1b2d4e`). |
| `user_id` | `str` | Owner tenant identifier for strict access isolation. |
| `category` | `str` | Category: `preference`, `fact`, `project`, `instruction`. |
| `content` | `str` | The factual assertion or preference statement. |
| `importance`| `int` | Priority level (1 to 5). Higher priority ranks higher in context. |
| `created_at`| `str` | ISO 8601 UTC creation timestamp. |
| `updated_at`| `str` | ISO 8601 UTC last modified timestamp. |

---

## 4. Automatic Preference Extraction

In addition to manual memory creation via the UI or API, `MemoryManager` (`backend/memory/memory_manager.py`) passively scans user prompts for explicit memory declarations using non-invasive pattern heuristics:

- `(?:please remember that|remember that|note that|don't forget that)\s+(.*)` -> `category: "fact"`, `importance: 4`
- `(?:my name is|i am called|call me)\s+(.*)` -> `category: "fact"`, `importance: 4`
- `(?:i prefer|i like|i always use|my favorite)\s+(.*)` -> `category: "preference"`, `importance: 3`
- `(?:i am working on|my project is|current project is)\s+(.*)` -> `category: "project"`, `importance: 3`

Duplicates are automatically filtered by checking substring overlap against existing stored memories before insertion.

---

## 5. System Prompt Injection

When generating responses, relevant user memories are retrieved and formatted into the system prompt:

```
[PERSISTENT USER MEMORY & PREFERENCES]
- [PREFERENCE] Prefers clean Python 3.12 with type annotations and dataclasses.
- [FACT] User name is Dr. Aris Thorne.
- [PROJECT] Developing the ORBIT AI Agent Platform.
```

The model adheres to these preferences across all subsequent conversation threads without requiring repetitive prompting.

---

## 6. User Control & Privacy APIs

Users retain full control to view, add, edit, or delete stored memories at any time:

- `GET /api/memories?category={cat}`: List all memories for the authenticated user.
- `POST /api/memories`: Explicitly save a new preference or fact.
- `PATCH /api/memories/<id>`: Update content, priority, or category.
- `DELETE /api/memories/<id>`: Permanently remove a memory item.

