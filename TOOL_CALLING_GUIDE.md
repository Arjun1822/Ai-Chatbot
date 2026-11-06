# Secure Tool Calling Guide

## 1. Overview

ORBIT AI features a secure, sandboxed tool calling framework. Tools provide deterministic computing, real-time external knowledge retrieval, and mathematical precision without granting the language model arbitrary shell or code execution privileges.

---

## 2. Default Registered Tools

### 2.1 Calculator (`calculator`)
- **Handler**: `SafeMathEvaluator` using Python's `ast` (Abstract Syntax Tree) module.
- **Safety**: Pure syntax tree traversal. Zero `eval()` or `exec()`.
- **Supported Operators**: `+`, `-`, `*`, `/`, `//`, `%`, `^`, `**`.
- **Supported Functions**: `sqrt()`, `abs()`, `round()`, `sin()`, `cos()`, `tan()`, `log()`, `exp()`, `pi`, `e`.
- **Compute Guard**: Exponent magnitudes exceeding $100$ or base numbers exceeding $10^{10}$ are rejected to prevent CPU denial-of-service.

### 2.2 Date and Time (`date_time`)
- **Handler**: Pure Python `datetime` module with timezone awareness.
- **Operations**:
  - `current_time`: Returns current UTC time in ISO 8601, Unix epoch, date, and time of day.
  - `day_of_week`: Computes the exact day of the week for any past or future date `YYYY-MM-DD`.
  - `days_between`: Computes the exact duration in days between two target dates.

### 2.3 Open-Meteo Weather (`weather`)
- **Handler**: Queries Open-Meteo free geocoding and weather APIs (`geocoding-api.open-meteo.com` and `api.open-meteo.com`).
- **Features**: Automatic geocoding (e.g. "Paris" -> latitude 48.85, longitude 2.35) and current temperature, weather code, and conditions retrieval.

### 2.4 Web Search (`web_search`)
- **Handler**: DuckDuckGo API integration (`api.duckduckgo.com`).
- **Features**: Safe instant answers, abstract text, related topics, and external citations.

### 2.5 Document Search (`document_search`)
- **Handler**: RAG vector similarity retrieval over user's uploaded documents via `RAGService`.
- **Features**: Cosine similarity top-$k$ retrieval with exact file attribution.

---

## 3. How to Register a New Tool

New tools can be registered into `ToolRegistry` without modifying the core orchestrator:

```python
from agent.schemas import ToolDefinition, ToolParameter
from agent.tool_registry import ToolRegistry

def my_custom_tool_handler(symbol: str) -> dict:
    # Perform deterministic lookups or calculations
    return {"symbol": symbol.upper(), "status": "active"}

registry = ToolRegistry()
registry.register(
    name="stock_ticker",
    description="Look up market status and exchange info for a given stock symbol.",
    parameters=[
        {
            "name": "symbol",
            "type": "string",
            "description": "Stock ticker symbol (e.g. 'GOOGL', 'AAPL').",
            "required": True,
        }
    ],
    handler=my_custom_tool_handler,
)
```

---

## 4. Safety & Defense in Depth

1. **Schema Validation**: Every argument is validated against parameter types (`string`, `number`, `integer`, `boolean`, `array`, `object`) before execution.
2. **Execution Timeout**: Tools are executed with an active timer (default 5.0s). If an external API hangs, the manager interrupts execution and reports a timeout.
3. **Loop Detection**: If an LLM attempts to execute the same tool with identical arguments repeatedly, the execution manager blocks subsequent calls with `"Loop detected"`.
4. **Audit Logging**: Structured metrics (tool name, execution time ms, success/error status) are recorded in `ToolExecutionManager._execution_history` without storing sensitive customer payload data.
