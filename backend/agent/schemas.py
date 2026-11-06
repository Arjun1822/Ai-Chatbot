from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


class AgentMode(str, Enum):
    CHAT = "chat"
    AGENT = "agent"
    DOCUMENT = "document"


@dataclass
class ToolParameter:
    name: str
    type: str  # "string", "number", "integer", "boolean", "array", "object"
    description: str
    required: bool = True
    enum: Optional[List[str]] = None


@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: List[ToolParameter]
    handler: Callable[..., Any]
    requires_confirmation: bool = False

    def to_gemini_schema(self) -> Dict[str, Any]:
        """Convert to Gemini FunctionDeclaration schema format."""
        properties = {}
        required_fields = []
        for param in self.parameters:
            prop_def: Dict[str, Any] = {
                "type": param.type.upper(),
                "description": param.description,
            }
            if param.enum:
                prop_def["enum"] = param.enum
            properties[param.name] = prop_def
            if param.required:
                required_fields.append(param.name)

        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "OBJECT",
                "properties": properties,
                "required": required_fields,
            },
        }


@dataclass
class ToolCall:
    id: str
    tool_name: str
    arguments: Dict[str, Any]


@dataclass
class ToolResult:
    tool_name: str
    success: bool
    output: Any
    error: Optional[str] = None
    execution_time_ms: int = 0
    requires_confirmation: bool = False


@dataclass
class AgentStep:
    step_number: int
    thought: str
    tool_call: Optional[ToolCall] = None
    tool_result: Optional[ToolResult] = None
