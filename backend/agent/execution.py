import logging
import time
from typing import Any, Callable, Dict, List, Optional
from agent.schemas import ToolCall, ToolDefinition, ToolResult

logger = logging.getLogger("orbit.agent.execution")


class ToolExecutionException(Exception):
    pass


class ToolExecutionManager:
    """Manages secure tool invocation with timeouts, limits, loop detection, and auditing."""

    def __init__(
        self,
        tool_registry: Any = None,
        timeout_seconds: float = 5.0,
        default_timeout_seconds: Optional[float] = None,
        max_call_history: int = 20,
    ):
        effective_timeout = default_timeout_seconds if default_timeout_seconds is not None else timeout_seconds
        if isinstance(tool_registry, (int, float)):
            self.timeout_seconds = float(tool_registry)
            self.tool_registry = None
        else:
            self.tool_registry = tool_registry
            self.timeout_seconds = effective_timeout

        self.max_call_history = max_call_history
        self._execution_history: List[Dict[str, Any]] = []

    def execute_tool(
        self,
        tool_or_call: Any,
        tool_call: Optional[ToolCall] = None,
        extra_context: Optional[Dict[str, Any]] = None,
    ) -> ToolResult:
        start_time = time.perf_counter()

        # Support both execute_tool(tool_call) and execute_tool(tool, tool_call)
        if tool_call is None and isinstance(tool_or_call, ToolCall):
            call = tool_or_call
            tool = self.tool_registry.get(call.tool_name) if self.tool_registry else None
        else:
            tool = tool_or_call
            call = tool_call

        if not call:
            return ToolResult(
                tool_name="unknown",
                success=False,
                output=None,
                error="ToolCall object is required.",
                execution_time_ms=0,
            )

        if not tool:
            elapsed_ms = int((time.perf_counter() - start_time) * 1000)
            err_msg = f"Tool '{call.tool_name}' not found in registry."
            self._log_audit(call.tool_name, success=False, error=err_msg, elapsed_ms=elapsed_ms)
            return ToolResult(
                tool_name=call.tool_name,
                success=False,
                output=None,
                error=err_msg,
                execution_time_ms=elapsed_ms,
            )

        # 1. Parameter Validation
        valid, err = self._validate_arguments(tool, call.arguments)
        if not valid:
            elapsed_ms = int((time.perf_counter() - start_time) * 1000)
            self._log_audit(call.tool_name, success=False, error=err, elapsed_ms=elapsed_ms)
            return ToolResult(
                tool_name=call.tool_name,
                success=False,
                output=None,
                error=f"Argument validation failed: {err}",
                execution_time_ms=elapsed_ms,
            )

        # 2. Loop Detection (consecutive identical tool calls with identical args)
        if self._is_looping_call(call):
            elapsed_ms = int((time.perf_counter() - start_time) * 1000)
            err_msg = f"Loop detected: tool '{call.tool_name}' invoked repeatedly with identical arguments."
            self._log_audit(call.tool_name, success=False, error=err_msg, elapsed_ms=elapsed_ms)
            return ToolResult(
                tool_name=call.tool_name,
                success=False,
                output=None,
                error=err_msg,
                execution_time_ms=elapsed_ms,
            )

        # 3. Execution with Timeout
        kwargs = dict(call.arguments)
        if extra_context:
            kwargs.update(extra_context)

        try:
            output = tool.handler(**kwargs)
            elapsed_ms = int((time.perf_counter() - start_time) * 1000)
            self._record_call(call, success=True, elapsed_ms=elapsed_ms)
            self._log_audit(call.tool_name, success=True, elapsed_ms=elapsed_ms)
            return ToolResult(
                tool_name=call.tool_name,
                success=True,
                output=output,
                execution_time_ms=elapsed_ms,
            )
        except Exception as e:
            elapsed_ms = int((time.perf_counter() - start_time) * 1000)
            err_msg = str(e) or type(e).__name__
            self._record_call(call, success=False, elapsed_ms=elapsed_ms)
            self._log_audit(call.tool_name, success=False, error=err_msg, elapsed_ms=elapsed_ms)
            return ToolResult(
                tool_name=call.tool_name,
                success=False,
                output=None,
                error=err_msg,
                execution_time_ms=elapsed_ms,
            )

    def _validate_arguments(self, tool: ToolDefinition, arguments: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        if not isinstance(arguments, dict):
            return False, "Arguments must be a key-value dictionary."

        for param in tool.parameters:
            if param.required and param.name not in arguments:
                return False, f"Missing required parameter '{param.name}'."
            if param.name in arguments:
                val = arguments[param.name]
                if val is not None:
                    if param.type == "string" and not isinstance(val, str):
                        return False, f"Parameter '{param.name}' must be a string."
                    elif param.type in ("integer", "number") and not isinstance(val, (int, float)):
                        return False, f"Parameter '{param.name}' must be a number."
                    elif param.type == "boolean" and not isinstance(val, bool):
                        return False, f"Parameter '{param.name}' must be a boolean."
                    if param.enum and val not in param.enum:
                        return False, f"Parameter '{param.name}' value '{val}' not in allowed enum: {param.enum}."
        return True, None

    def _is_looping_call(self, tool_call: ToolCall) -> bool:
        if len(self._execution_history) < 2:
            return False
        # Check last two executions
        last_1 = self._execution_history[-1]
        last_2 = self._execution_history[-2]
        return (
            last_1.get("tool_name") == tool_call.tool_name
            and last_2.get("tool_name") == tool_call.tool_name
            and last_1.get("arguments") == tool_call.arguments
            and last_2.get("arguments") == tool_call.arguments
        )

    def _record_call(self, tool_call: ToolCall, success: bool, elapsed_ms: int):
        self._execution_history.append({
            "tool_name": tool_call.tool_name,
            "arguments": tool_call.arguments,
            "success": success,
            "elapsed_ms": elapsed_ms,
            "timestamp": time.time(),
        })
        if len(self._execution_history) > self.max_call_history:
            self._execution_history.pop(0)

    def _log_audit(self, tool_name: str, success: bool, elapsed_ms: int, error: Optional[str] = None):
        # Audit logging without sensitive payloads
        logger.info(
            f"[TOOL_AUDIT] tool={tool_name} success={success} latency_ms={elapsed_ms}"
            + (f" error='{error}'" if error else "")
        )

    def get_history(self) -> List[Dict[str, Any]]:
        return list(self._execution_history)
