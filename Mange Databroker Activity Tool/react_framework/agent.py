"""Run configurable ReAct agents against a local Ollama chat endpoint."""

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from http.client import HTTPConnection, HTTPException
from typing import Callable, TypeAlias


# Keep the shared runtime bound to this computer rather than a remote service.
OLLAMA_HOST = "127.0.0.1"
OLLAMA_PORT = 11434

ActivityCallback: TypeAlias = Callable[["AgentActivity"], None]


@dataclass(frozen=True)
class AgentActivity:
    """Describe a user-visible agent action without storing prompts or content."""

    agent_name: str
    event: str
    detail: str
    timestamp: str

    @classmethod
    def create(cls, agent_name: str, event: str, detail: str) -> "AgentActivity":
        """Create an activity record with a UTC timestamp."""
        return cls(
            agent_name=agent_name,
            event=event,
            detail=detail,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )


@dataclass(frozen=True)
class AgentTool:
    """Pair an Ollama function schema with its application-side handler."""

    name: str
    description: str
    parameters: dict
    handler: Callable[[dict], object]

    def ollama_definition(self) -> dict:
        """Return the tool schema in the format expected by Ollama."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass(frozen=True)
class ToolResult:
    """Record one tool call and the value returned by its handler."""

    name: str
    arguments: dict
    output: object


@dataclass(frozen=True)
class AgentResponse:
    """Return the model's final text together with executed tool results."""

    content: str
    tool_results: tuple[ToolResult, ...]


class ReActAgent:
    """Run a module-configured Reason-and-Act conversation using local Ollama.

    Each feature module supplies its own instructions and tools. This shared
    class manages only the model/tool loop; it does not coordinate modules.
    """

    def __init__(
        self,
        instructions: str,
        tools: tuple[AgentTool, ...] = (),
        model: str | None = None,
        max_tool_rounds: int = 4,
        timeout_seconds: int = 120,
        agent_name: str = "ReAct agent",
        activity_callback: ActivityCallback | None = None,
    ) -> None:
        """Create an agent with module-specific instructions and capabilities.

        Args:
            instructions: System instructions defining this module's scope.
            tools: Functions this agent alone may request from its application.
            model: Installed Ollama model name; defaults to OLLAMA_MODEL or
                ``mistral:7b``.
            max_tool_rounds: Maximum number of model/tool cycles per run.
            timeout_seconds: Maximum wait for each local Ollama response.
            agent_name: Short label shown in activity output.
            activity_callback: Optional receiver for visible/audited activity.

        Raises:
            ValueError: If instructions, tools, or limits are invalid.
        """
        if not instructions.strip():
            raise ValueError("Agent instructions must not be empty.")
        if max_tool_rounds < 1:
            raise ValueError("max_tool_rounds must be at least 1.")
        if timeout_seconds < 1:
            raise ValueError("timeout_seconds must be at least 1.")
        if not agent_name.strip():
            raise ValueError("agent_name must not be empty.")

        # Preserve module-defined tools and reject ambiguous duplicate names.
        tool_names = [tool.name for tool in tools]
        if len(tool_names) != len(set(tool_names)):
            raise ValueError("Tool names must be unique within an agent.")
        if any(not name.strip() for name in tool_names):
            raise ValueError("Tool names must not be empty.")

        # Keep the tool lookup local to this agent; modules do not share tools.
        self._tools = {tool.name: tool for tool in tools}
        self._instructions = instructions
        self._model = model or os.getenv("OLLAMA_MODEL", "mistral:7b")
        self._max_tool_rounds = max_tool_rounds
        self._timeout_seconds = timeout_seconds
        self._agent_name = agent_name
        self._activity_callback = activity_callback

    def run(self, user_message: str) -> AgentResponse:
        """Run one user request through the bounded local ReAct tool loop.

        Args:
            user_message: User input for this module's agent.

        Returns:
            Final model text and the outputs from tools actually executed.

        Raises:
            ValueError: If the user message is blank.
            RuntimeError: If Ollama or its response cannot be used.
        """
        if not user_message.strip():
            raise ValueError("User message must not be empty.")

        self._emit("agent.started", "Started a local Ollama session.")
        # Keep the conversation only in memory for the duration of this call.
        messages = [
            {"role": "system", "content": self._instructions},
            {"role": "user", "content": user_message},
        ]
        tool_results: list[ToolResult] = []

        # One final model response is allowed after the maximum tool rounds.
        for round_number in range(self._max_tool_rounds + 1):
            try:
                response = self._ollama_chat(messages)
            except RuntimeError as error:
                self._emit("agent.failed", f"Local Ollama request failed: {error}")
                raise
            assistant_message = response.get("message")
            if not isinstance(assistant_message, dict):
                error = RuntimeError("Ollama returned a response without a message.")
                self._emit("agent.failed", str(error))
                raise error
            messages.append(assistant_message)

            calls = assistant_message.get("tool_calls", [])
            if not isinstance(calls, list):
                raise RuntimeError("Ollama returned invalid tool calls.")
            if not calls:
                content = assistant_message.get("content", "")
                if not isinstance(content, str):
                    error = RuntimeError("Ollama returned invalid message content.")
                    self._emit("agent.failed", str(error))
                    raise error
                self._emit("agent.completed", "Received the agent's final response.")
                return AgentResponse(content=content, tool_results=tuple(tool_results))
            if round_number == self._max_tool_rounds:
                error = RuntimeError("The ReAct tool-call limit was reached.")
                self._emit("agent.failed", str(error))
                raise error

            # Each model call is checked against this agent's own tool registry.
            for call in calls:
                try:
                    tool, arguments = self._parse_tool_call(call)
                except RuntimeError as error:
                    self._emit("tool.rejected", str(error))
                    raise
                self._emit("tool.started", self._tool_activity_detail(tool.name, arguments))
                try:
                    output = tool.handler(arguments)
                except ValueError as error:
                    # Return expected input/lookup errors to the model and retain
                    # them in the result, so a module can inspect the failure.
                    output = {"error": str(error)}
                    self._emit("tool.failed", f"{tool.name} reported: {error}")
                except Exception as error:
                    self._emit("tool.failed", f"{tool.name} failed: {type(error).__name__}.")
                    raise
                else:
                    self._emit("tool.completed", f"Completed {tool.name}.")

                tool_results.append(
                    ToolResult(name=tool.name, arguments=arguments, output=output)
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_name": tool.name,
                        "content": json.dumps(output),
                    }
                )

        raise RuntimeError("The ReAct conversation ended without a final response.")

    def _emit(self, event: str, detail: str) -> None:
        """Send one event to the configured user-visible activity receiver."""
        activity = AgentActivity.create(self._agent_name, event, detail)
        if self._activity_callback is None:
            print(f"[{activity.timestamp}] {activity.agent_name}: {activity.detail}")
        else:
            self._activity_callback(activity)

    @staticmethod
    def _tool_activity_detail(tool_name: str, arguments: dict) -> str:
        """Summarize tool use without logging document text or full prompts."""
        # Relative filenames help the user identify reviewed evidence; private
        # search text, legal questions, and document content are never recorded.
        path_fields = (
            "path",
            "source_path",
            "destination_name",
            "file_name",
        )
        locations = [
            f"{field}={arguments[field]}"
            for field in path_fields
            if isinstance(arguments.get(field), str)
        ]
        if locations:
            return f"Running {tool_name} ({', '.join(locations)})."
        return (
            f"Running {tool_name}; query, prompt, and document contents "
            "are omitted from the activity log."
        )

    def _parse_tool_call(self, call: object) -> tuple[AgentTool, dict]:
        """Validate a model-produced tool call before running application code."""
        if not isinstance(call, dict):
            raise RuntimeError("Ollama returned an invalid tool call.")
        function = call.get("function")
        if not isinstance(function, dict):
            raise RuntimeError("Ollama returned an invalid tool function.")

        # Reject unregistered model requests; only configured module tools run.
        tool_name = function.get("name")
        if not isinstance(tool_name, str) or tool_name not in self._tools:
            raise RuntimeError(f"Ollama requested an unavailable tool: {tool_name!r}.")
        tool = self._tools[tool_name]
        arguments = function.get("arguments", {})
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError as error:
                raise RuntimeError("Ollama returned invalid tool argument JSON.") from error
        if not isinstance(arguments, dict):
            raise RuntimeError("Ollama tool arguments must be an object.")

        # Validate the basic JSON Schema fields used by module tool definitions.
        self._validate_arguments(tool, arguments)
        return tool, arguments

    @staticmethod
    def _validate_arguments(tool: AgentTool, arguments: dict) -> None:
        """Check required keys, extra keys, and primitive JSON value types."""
        schema = tool.parameters
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        if not isinstance(properties, dict) or not isinstance(required, list):
            raise RuntimeError(f"Tool {tool.name!r} has an invalid parameter schema.")
        if any(key not in arguments for key in required):
            raise RuntimeError(f"Tool {tool.name!r} is missing required arguments.")
        if schema.get("additionalProperties") is False:
            if any(key not in properties for key in arguments):
                raise RuntimeError(f"Tool {tool.name!r} received unexpected arguments.")

        # Match JSON types explicitly; in Python bool is also an int subclass.
        type_checks = {
            "string": lambda value: isinstance(value, str),
            "number": lambda value: isinstance(value, (int, float)) and not isinstance(value, bool),
            "integer": lambda value: isinstance(value, int) and not isinstance(value, bool),
            "boolean": lambda value: isinstance(value, bool),
            "object": lambda value: isinstance(value, dict),
            "array": lambda value: isinstance(value, list),
            "null": lambda value: value is None,
        }
        for key, value in arguments.items():
            property_schema = properties.get(key)
            if not isinstance(property_schema, dict):
                continue
            expected_type = property_schema.get("type")
            type_check = type_checks.get(expected_type)
            if type_check is not None and not type_check(value):
                raise RuntimeError(
                    f"Tool {tool.name!r} argument {key!r} must be {expected_type}."
                )

    def _ollama_chat(self, messages: list[dict]) -> dict:
        """Send one request to this computer's Ollama server and decode JSON."""
        # Include only the tools registered for this particular module agent.
        payload_data = {
            "model": self._model,
            "messages": messages,
            "tools": [
                tool.ollama_definition()
                for tool in self._tools.values()
            ],
            "stream": False,
        }
        payload = json.dumps(payload_data).encode("utf-8")

        # The host is fixed to loopback; no remote Ollama host can be configured.
        connection = HTTPConnection(
            OLLAMA_HOST,
            OLLAMA_PORT,
            timeout=self._timeout_seconds,
        )
        try:
            connection.request(
                "POST",
                "/api/chat",
                body=payload,
                headers={"Content-Type": "application/json"},
            )
            response = connection.getresponse()
            body = response.read()
            if response.status != 200:
                detail = body.decode("utf-8", errors="replace")
                raise RuntimeError(f"Ollama returned HTTP {response.status}: {detail}")
            result = json.loads(body.decode("utf-8"))
        except (ConnectionError, TimeoutError, OSError, HTTPException) as error:
            raise RuntimeError(
                f"Could not connect to local Ollama at {OLLAMA_HOST}:{OLLAMA_PORT}. "
                "Start Ollama and make sure the selected model is installed."
            ) from error
        except json.JSONDecodeError as error:
            raise RuntimeError("Ollama returned invalid JSON.") from error
        finally:
            connection.close()

        if not isinstance(result, dict):
            raise RuntimeError("Ollama returned an unexpected response.")
        return result
