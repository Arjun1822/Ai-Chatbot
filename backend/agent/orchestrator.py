from datetime import datetime, timezone
import json
import logging
import re
import time
from typing import Any, Dict, Generator, List, Optional
import uuid

from agent.execution import ToolExecutionManager
from agent.schemas import AgentMode, AgentStep, ToolCall, ToolResult
from agent.tool_registry import ToolRegistry
from memory.memory_manager import MemoryManager
from rag.rag_service import RAGService
from services.llm_service import LLMService

logger = logging.getLogger(__name__)


class AgentOrchestrator:
    """Coordinates user requests, intent classification, persistent memory,

    RAG retrieval, and secure multi-step tool execution.
    """

    MAX_AGENT_STEPS = 5

    def __init__(
        self,
        llm_service: LLMService,
        tool_registry: Optional[ToolRegistry] = None,
        rag_service: Optional[RAGService] = None,
        memory_manager: Optional[MemoryManager] = None,
        execution_manager: Optional[ToolExecutionManager] = None,
    ):
        self.llm_service = llm_service
        self.tool_registry = tool_registry or ToolRegistry()
        self.rag_service = rag_service or RAGService()
        self.memory_manager = memory_manager or MemoryManager()
        self.execution_manager = execution_manager or ToolExecutionManager(self.tool_registry)

        # Wire RAG search into the tool registry
        self._wire_rag_tool()

    def _wire_rag_tool(self):
        """Wire RAGService query into the tool registry's document_search tool."""
        rag = self.rag_service

        def search_docs(query: str, top_k: int = 3, user_id: Optional[str] = None) -> Dict[str, Any]:
            if not user_id:
                return {"message": "No matching documents found for query.", "documents": []}
            res = rag.query_documents(query, top_k=top_k, user_id=user_id)
            if not res["citations"]:
                return {"message": "No matching documents found for query.", "documents": []}
            return {
                "message": f"Found {len(res['citations'])} relevant document chunks.",
                "context": res["context"],
                "citations": res["citations"],
            }

        self.tool_registry.register(
            name="document_search",
            description="Search uploaded knowledge base documents using semantic RAG vector retrieval.",
            parameters=[
                {
                    "name": "query",
                    "type": "string",
                    "description": "Keywords or question to search within indexed documents.",
                    "required": True,
                },
                {
                    "name": "top_k",
                    "type": "integer",
                    "description": "Maximum number of document chunks to retrieve (default 3).",
                    "required": False,
                },
            ],
            handler=search_docs,
        )

    def execute_stream(
        self,
        messages: List[Dict[str, Any]],
        mode: str = "chat",
        user_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
    ) -> Generator[Dict[str, Any], None, None]:
        """Generator yielding SSE event dictionaries."""
        start_time = time.time()
        agent_exec_id = f"exec_{uuid.uuid4().hex[:10]}"
        eff_uid = user_id or f"guest_{uuid.uuid4().hex[:12]}"

        # Normalize mode
        clean_mode = mode.lower().strip() if mode else "chat"
        if clean_mode not in ("chat", "agent", "document"):
            clean_mode = "chat"

        # Auto-extract preferences from the last user message
        last_user_msg = next((m.get("content", "") for m in reversed(messages) if m.get("role") == "user"), "")
        if last_user_msg:
            try:
                self.memory_manager.auto_extract_memories(eff_uid, last_user_msg)
            except Exception as e:
                logger.debug(f"Auto-extraction error: {e}")

        # Retrieve user memory context
        memory_context = self.memory_manager.format_system_memory_context(eff_uid, last_user_msg)

        citations: List[Dict[str, Any]] = []

        if clean_mode == "document":
            yield from self._stream_document_mode(
                messages=messages,
                user_id=eff_uid,
                memory_context=memory_context,
                start_time=start_time,
                agent_exec_id=agent_exec_id,
            )
        elif clean_mode == "agent":
            yield from self._stream_agent_mode(
                messages=messages,
                user_id=eff_uid,
                memory_context=memory_context,
                start_time=start_time,
                agent_exec_id=agent_exec_id,
            )
        else:  # Standard chat mode
            yield from self._stream_chat_mode(
                messages=messages,
                memory_context=memory_context,
                start_time=start_time,
                agent_exec_id=agent_exec_id,
            )

    def _stream_chat_mode(
        self,
        messages: List[Dict[str, Any]],
        memory_context: str,
        start_time: float,
        agent_exec_id: str,
    ) -> Generator[Dict[str, Any], None, None]:
        """Standard direct chat streaming with persistent memory."""
        system_instruction = self.llm_service.SYSTEM_INSTRUCTION
        if memory_context:
            system_instruction = f"{system_instruction}\n\n{memory_context}"

        stream = self.llm_service.stream_response(messages, system_instruction=system_instruction)
        for event in stream:
            event["execution_id"] = agent_exec_id
            event["mode"] = "chat"
            yield event

    def _stream_document_mode(
        self,
        messages: List[Dict[str, Any]],
        user_id: str,
        memory_context: str,
        start_time: float,
        agent_exec_id: str,
    ) -> Generator[Dict[str, Any], None, None]:
        """RAG-augmented document QA mode."""
        last_user_msg = next((m.get("content", "") for m in reversed(messages) if m.get("role") == "user"), "")
        rag_res = self.rag_service.query_documents(last_user_msg, top_k=4, user_id=user_id)
        citations = rag_res.get("citations", [])

        system_instruction = (
            "You are ORBIT AI in DOCUMENT RETRIEVAL MODE.\n"
            "Answer the user's inquiry accurately based on the provided document sources.\n"
            "Cite sources explicitly using [Source N] bracket notation where relevant.\n"
            "If the answer cannot be determined from the documents, state so clearly."
        )

        if rag_res.get("context"):
            system_instruction += f"\n\n[RETRIEVED KNOWLEDGE BASE CONTEXT]\n{rag_res['context']}"
        else:
            system_instruction += "\n\n[NO RETRIEVED DOCUMENTS FOUND FOR THIS QUERY - Answer with general knowledge and inform user no documents matched.]"

        if memory_context:
            system_instruction += f"\n\n{memory_context}"

        stream = self.llm_service.stream_response(messages, system_instruction=system_instruction)
        for event in stream:
            event["execution_id"] = agent_exec_id
            event["mode"] = "document"
            if event.get("type") == "done":
                event["citations"] = citations
            yield event

    def _stream_agent_mode(
        self,
        messages: List[Dict[str, Any]],
        user_id: str,
        memory_context: str,
        start_time: float,
        agent_exec_id: str,
    ) -> Generator[Dict[str, Any], None, None]:
        """Autonomous agent mode with multi-step reasoning and tool execution."""
        tool_schemas = self.tool_registry.get_schemas()
        tool_descriptions = json.dumps(tool_schemas, indent=2)

        agent_prompt = (
            "You are ORBIT AI ADVANCED AGENT, an autonomous multi-step reasoning AI system.\n"
            "You have access to the following registered tools:\n"
            f"{tool_descriptions}\n\n"
            "INSTRUCTIONS FOR TOOL USE:\n"
            "1. When you need to calculate math, get current date/time, search documents, get weather, or search the web, trigger a tool call.\n"
            "2. To call a tool, output ONLY a JSON object in the exact format:\n"
            '```json\n{"tool": "<tool_name>", "arguments": {<arguments>}}\n```\n'
            "3. Do not include extra conversational text when outputting a tool call block.\n"
            "4. When you receive the tool output observation, reason over the result and provide the final answer to the user.\n"
            "5. If no tools are required, answer the user directly."
        )

        if memory_context:
            agent_prompt += f"\n\n{memory_context}"

        working_messages = [dict(m) for m in messages]
        steps_taken = 0
        all_tool_calls = []

        while steps_taken < self.MAX_AGENT_STEPS:
            steps_taken += 1

            # Generate step response
            full_step_text = ""
            try:
                # We consume the generator to inspect tool calls
                step_stream = self.llm_service.stream_response(
                    working_messages,
                    system_instruction=agent_prompt,
                )
                for chunk_event in step_stream:
                    if chunk_event.get("type") == "chunk":
                        full_step_text += chunk_event.get("content", "")
            except Exception as e:
                logger.error(f"Agent step generation failed: {e}")
                yield {
                    "type": "error",
                    "message": f"Agent reasoning step failed: {str(e)}",
                    "execution_id": agent_exec_id,
                    "mode": "agent",
                }
                return

            # Check if model wants to call a tool
            parsed_tool = self._parse_tool_call(full_step_text)
            if not parsed_tool:
                # No tool call; this is the final answer! Stream it in chunks to user
                yield from self._yield_text_chunks(full_step_text, agent_exec_id)
                elapsed_ms = int((time.time() - start_time) * 1000)
                yield {
                    "type": "done",
                    "mode": "agent",
                    "execution_id": agent_exec_id,
                    "steps_taken": steps_taken,
                    "tool_calls": all_tool_calls,
                    "latency_ms": elapsed_ms,
                    "usage": {
                        "prompt_tokens": len(str(working_messages)) // 4,
                        "completion_tokens": len(full_step_text) // 4,
                        "total_tokens": (len(str(working_messages)) + len(full_step_text)) // 4,
                    },
                }
                return

            # Tool call detected!
            tool_name = parsed_tool["tool"]
            tool_args = parsed_tool.get("arguments", {})
            # Inject user_id if needed by tool
            if tool_name == "document_search" and "user_id" not in tool_args:
                tool_args["user_id"] = user_id

            call_id = f"call_{uuid.uuid4().hex[:8]}"
            tool_call_obj = ToolCall(id=call_id, tool_name=tool_name, arguments=tool_args)

            # Inform frontend about the tool call
            yield {
                "type": "tool_call",
                "id": call_id,
                "tool_name": tool_name,
                "arguments": tool_args,
                "step": steps_taken,
                "execution_id": agent_exec_id,
                "mode": "agent",
            }

            # Execute tool safely
            result: ToolResult = self.execution_manager.execute_tool(tool_call_obj)
            all_tool_calls.append({
                "tool": tool_name,
                "arguments": tool_args,
                "success": result.success,
                "output": result.output,
                "execution_time_ms": result.execution_time_ms,
            })

            # Inform frontend about the tool result
            yield {
                "type": "tool_result",
                "id": call_id,
                "tool_name": tool_name,
                "success": result.success,
                "output": result.output,
                "error": result.error,
                "execution_time_ms": result.execution_time_ms,
                "step": steps_taken,
                "execution_id": agent_exec_id,
                "mode": "agent",
            }

            # Append to working history
            observation_str = json.dumps(result.output) if not isinstance(result.output, str) else result.output
            working_messages.append({"role": "model", "content": full_step_text})
            working_messages.append({
                "role": "user",
                "content": f"[Tool Observation for '{tool_name}']\n{observation_str}\n\nNow continue your reasoning to answer the user request.",
            })

        # Max steps reached fallback
        fallback_msg = "Reached maximum reasoning steps (5). Based on intermediate steps:\n"
        yield {
            "type": "chunk",
            "content": fallback_msg,
            "execution_id": agent_exec_id,
            "mode": "agent",
        }
        elapsed_ms = int((time.time() - start_time) * 1000)
        yield {
            "type": "done",
            "mode": "agent",
            "execution_id": agent_exec_id,
            "steps_taken": steps_taken,
            "tool_calls": all_tool_calls,
            "latency_ms": elapsed_ms,
        }

    def _parse_tool_call(self, text: str) -> Optional[Dict[str, Any]]:
        """Extract tool call json from model generation text."""
        # Check ```json ... ``` blocks
        json_matches = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        for m in json_matches:
            try:
                data = json.loads(m.strip())
                if isinstance(data, dict) and "tool" in data:
                    return data
            except Exception:
                continue

        # Check raw json object with "tool" key
        raw_match = re.search(r'(\{\s*"tool"\s*:\s*"[^"]+".*?\})', text, re.DOTALL)
        if raw_match:
            try:
                data = json.loads(raw_match.group(1))
                if isinstance(data, dict) and "tool" in data:
                    return data
            except Exception:
                pass

        return None

    @staticmethod
    def _yield_text_chunks(text: str, exec_id: str, chunk_size: int = 15) -> Generator[Dict[str, Any], None, None]:
        """Stream final text in progressive increments for natural UI streaming."""
        for i in range(0, len(text), chunk_size):
            yield {
                "type": "chunk",
                "content": text[i : i + chunk_size],
                "execution_id": exec_id,
                "mode": "agent",
            }

