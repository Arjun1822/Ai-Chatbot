# Advanced Agent Architecture Specification

## 1. Architectural Blueprint

ORBIT AI implements a modular, autonomous agent architecture decoupling user intent handling, memory retrieval, tool discovery, sandboxed execution, and final response synthesis from presentation route handlers.

```
+-----------------------------------------------------------------------------------+
|                                 CLIENT LAYER                                      |
|  React 18 SPA | EventSource/SSE Reader | Mode Switcher (Chat | Agent | Doc RAG)   |
+-----------------------------------------------------------------------------------+
                                         |
                                         | REST / SSE Stream
                                         v
+-----------------------------------------------------------------------------------+
|                                API GATEWAY LAYER                                  |
|  Security Headers | Sliding Rate Limiter | PBKDF2 JWT Authentication | IDOR Guard  |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
|                            AGENT ORCHESTRATOR LAYER                               |
|                                                                                   |
|   1. Request Context Extraction & User Intent Normalization                       |
|   2. Persistent User Memory Retrieval (MemoryManager)                             |
|   3. RAG Vector Knowledge Base Search (RAGService)                                |
|   4. Multi-Step Reasoning Loop (Max 5 Steps)                                      |
|                                                                                   |
|           +-----------------------+           +----------------------+            |
|           |   Gemini 3.5 Model    |<--------->|  Tool Registry       |            |
|           |   (Reasoning Core)    |           |  - AST Calculator    |            |
|           +-----------------------+           |  - Date/Time Engine  |            |
|                       |                       |  - Weather Client    |            |
|                       v                       |  - Web Search Engine |            |
|           +-----------------------+           |  - RAG Vector Tool   |            |
|           |   Execution Manager   |<--------->+----------------------+            |
|           |   - Argument Validation               |                               |
|           |   - Loop Detection (Max Reps)         |                               |
|           |   - Execution Timeouts (5s)           |                               |
|           +---------------------------------------+                               |
|                       |                                                           |
|                       v                                                           |
|   5. Streaming Synthesizer & Citation Builder                                     |
+-----------------------------------------------------------------------------------+
```

---

## 2. Core Components

### 2.1 AgentOrchestrator (`backend/agent/orchestrator.py`)
- Coordinates the complete request lifecycle across execution modes:
  - **`chat` Mode**: Direct conversational streaming with active persistent memory context injection.
  - **`document` Mode**: Automated vector retrieval over uploaded documents, injecting indexed source chunks into the system instruction and formatting citation metadata into responses.
  - **`agent` Mode**: Autonomous multi-step reasoning with native function calls or JSON-delimited tool calls, executing up to 5 reasoning steps before finalizing responses.

### 2.2 Tool Registry (`backend/agent/tool_registry.py`)
- Provides an extensible registry for defining, documenting, validating, and executing tools.
- Auto-generates standard Gemini `FunctionDeclaration` schemas with required types, parameter descriptions, and enum constraints.
- Default registered tools:
  1. `calculator`: Safe AST evaluator.
  2. `date_time`: Real-time calendar and timestamp calculations.
  3. `weather`: Open-Meteo geocoding and forecast retrieval.
  4. `web_search`: DuckDuckGo real-time query interface.
  5. `document_search`: RAG vector knowledge base search.

### 2.3 Tool Execution Manager (`backend/agent/execution.py`)
- **Schema Validation**: Validates all incoming arguments against parameter schemas before triggering tool handlers.
- **Loop Prevention**: Detects consecutive duplicate invocations with identical arguments, interrupting infinite model loops immediately.
- **Execution Timeout**: Enforces a strict timeout per tool invocation (default 5.0s) to prevent blocking worker threads.
- **Audit Logging**: Maintains execution history containing timestamps, elapsed milliseconds, tool names, and outcomes without logging sensitive content.

---

## 3. Streaming Event Protocol (Server-Sent Events)

Communication between the Orchestrator and the frontend chat client uses Server-Sent Events (`text/event-stream`):

| Event Type | Payload Attributes | Purpose |
| :--- | :--- | :--- |
| `chunk` | `text`, `content`, `execution_id`, `mode` | Progressive streaming tokens for natural reading speed. |
| `tool_call` | `id`, `tool_name`, `arguments`, `step`, `mode` | Notifies UI that model initiated tool execution. |
| `tool_result` | `id`, `tool_name`, `output`, `success`, `execution_time_ms`, `step` | Delivers tool observation and latency back to client. |
| `done` | `conversation`, `message`, `meta`, `citations`, `steps_taken` | Finalizes turn; delivers persisted record and citations. |
| `error` | `error`, `message`, `execution_id` | Alerts frontend of unrecoverable exceptions or timeouts. |

---

## 4. Execution Limits & Failure Mitigations

1. **Maximum Step Ceiling**: Capped at 5 reasoning turns. If a model fails to arrive at a conclusion within 5 turns, the orchestrator terminates the loop gracefully and synthesizes an answer from intermediate observations.
2. **Deterministic Fallbacks**:
   - If internet connectivity is interrupted during web search or weather lookup, the tool returns a graceful descriptive error enabling the LLM to explain the situation to the user without crashing.
   - If the Gemini embedding API is unreachable or unconfigured, the system automatically switches to deterministic local L2-normalized dense embeddings.
