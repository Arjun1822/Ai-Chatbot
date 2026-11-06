import pytest
from agent.schemas import ToolDefinition, ToolParameter, ToolCall, ToolResult
from agent.tool_registry import ToolRegistry, SafeMathEvaluator
from agent.execution import ToolExecutionManager
from agent.orchestrator import AgentOrchestrator


class MockLLMForAgent:
    def __init__(self, responses=None):
        self.responses = responses or ["Direct answer."]
        self.call_idx = 0
        self.SYSTEM_INSTRUCTION = "Test instruction"

    def stream_response(self, messages, system_instruction=None):
        resp = self.responses[min(self.call_idx, len(self.responses) - 1)]
        self.call_idx += 1
        yield {"type": "chunk", "content": resp}


def test_safe_math_evaluator_valid():
    assert SafeMathEvaluator.evaluate("2 + 2") == 4
    assert SafeMathEvaluator.evaluate("10 - 3 * 2") == 4
    assert SafeMathEvaluator.evaluate("(48 / 6) + (12 * 7)") == 92.0
    assert SafeMathEvaluator.evaluate("2 ^ 3") == 8
    assert SafeMathEvaluator.evaluate("sqrt(144) + 10") == 22.0
    assert SafeMathEvaluator.evaluate("abs(-42)") == 42
    assert SafeMathEvaluator.evaluate("round(3.14159, 2)") == 3.14


def test_safe_math_evaluator_security_and_errors():
    with pytest.raises(ValueError):
        SafeMathEvaluator.evaluate("__import__('os').system('ls')")

    with pytest.raises(ValueError):
        SafeMathEvaluator.evaluate("eval('1+1')")

    with pytest.raises(ValueError, match="Exponentiation magnitude exceeds safe compute limits"):
        SafeMathEvaluator.evaluate("99999999999 ^ 99999999999")

    with pytest.raises(ValueError):
        SafeMathEvaluator.evaluate("")


def test_tool_registry():
    registry = ToolRegistry()
    tools = registry.list_tools()
    tool_names = [t.name for t in tools]
    assert "calculator" in tool_names
    assert "date_time" in tool_names
    assert "weather" in tool_names
    assert "web_search" in tool_names

    calc_def = registry.get("calculator")
    assert calc_def is not None
    gemini_schemas = registry.get_gemini_declarations()
    assert len(gemini_schemas) >= 4


def test_execution_manager():
    registry = ToolRegistry()
    manager = ToolExecutionManager(registry, default_timeout_seconds=2)

    # Valid calculator call
    call = ToolCall(id="c1", tool_name="calculator", arguments={"expression": "15 * 4"})
    result = manager.execute_tool(call)
    assert result.success is True
    assert result.output["result"] == 60

    # Unknown tool call
    call_unknown = ToolCall(id="c2", tool_name="nonexistent_tool", arguments={})
    res_unknown = manager.execute_tool(call_unknown)
    assert res_unknown.success is False
    assert "not found" in res_unknown.error

    # Consecutive loop detection
    for _ in range(3):
        res = manager.execute_tool(call)
    assert "loop detected" in res.error.lower()


def test_agent_orchestrator_chat_and_tool_flow():
    registry = ToolRegistry()
    # Mock LLM calls: first call triggers calculator, second provides final answer
    mock_responses = [
        '```json\n{"tool": "calculator", "arguments": {"expression": "25 * 4"}}\n```',
        "The calculated total is 100.",
    ]
    mock_llm = MockLLMForAgent(responses=mock_responses)
    orchestrator = AgentOrchestrator(
        llm_service=mock_llm,
        tool_registry=registry,
    )

    events = list(orchestrator.execute_stream(
        messages=[{"role": "user", "content": "What is 25 * 4?"}],
        mode="agent",
        user_id="test_user"
    ))

    event_types = [e["type"] for e in events]
    assert "tool_call" in event_types
    assert "tool_result" in event_types
    assert "chunk" in event_types
    assert "done" in event_types

    tool_call_evt = next(e for e in events if e["type"] == "tool_call")
    assert tool_call_evt["tool_name"] == "calculator"
    assert tool_call_evt["arguments"]["expression"] == "25 * 4"

    tool_res_evt = next(e for e in events if e["type"] == "tool_result")
    assert tool_res_evt["success"] is True
    assert tool_res_evt["output"]["result"] == 100
