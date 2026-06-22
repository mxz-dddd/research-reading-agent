import json

from app.agent.multi_step import MultiStepOrchestrator, _to_chat_tools
from app.core.llm_client import LLMClientError, OpenAICompatibleClient
from app.schemas.agent import AgentQueryRequest

TOOL_SCHEMAS = [
    {
        "type": "function",
        "name": "get_latest_workflow",
        "description": "调用 get_latest_workflow 工具",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "type": "function",
        "name": "list_workflow_history",
        "description": "调用 list_workflow_history 工具",
        "parameters": {
            "type": "object",
            "properties": {"limit": {"type": "integer"}},
            "additionalProperties": False,
        },
    },
]


def _tool_call_response(name: str, arguments: dict, call_id: str = "call_1") -> dict:
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {"name": name, "arguments": json.dumps(arguments)},
                        }
                    ],
                }
            }
        ]
    }


def _text_response(text: str) -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": text}}]}


class ScriptedClient(OpenAICompatibleClient):
    def __init__(self, responses: list) -> None:
        super().__init__(
            api_key="fake-key", model="fake-model", base_url="https://example.invalid/v1"
        )
        self._responses = list(responses)
        self.requests: list[list[dict]] = []

    def chat(self, messages, *, tools=None, tool_choice=None, temperature=0.2) -> dict:
        self.requests.append(list(messages))
        if not self._responses:
            raise LLMClientError("script exhausted")
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def chat_text(self, messages, *, temperature: float = 0.2) -> str:
        data = self.chat(messages)
        text = self.extract_text(data)
        if not text:
            raise LLMClientError("empty")
        return text


class FakeRegistry:
    def __init__(self, results: dict | None = None, error_tools: set | None = None) -> None:
        self.results = results or {}
        self.error_tools = error_tools or set()
        self.calls: list[tuple[str, dict]] = []

    def call(self, tool_name: str, **kwargs):
        self.calls.append((tool_name, kwargs))
        if tool_name in self.error_tools:
            raise ValueError(f"{tool_name} failed")
        return self.results.get(tool_name, {"success": True, "tool": tool_name})


class FakeSessionRepo:
    def resolve_recent_position(self, user_id, session_id, ordinal):
        return None


def _payload(message: str = "查看最近一次研究流程并总结") -> AgentQueryRequest:
    return AgentQueryRequest(message=message)


def test_to_chat_tools_wraps_function_schema() -> None:
    chat_tools = _to_chat_tools(TOOL_SCHEMAS)
    assert chat_tools[0]["type"] == "function"
    assert chat_tools[0]["function"]["name"] == "get_latest_workflow"
    assert "parameters" in chat_tools[0]["function"]


def test_multi_step_executes_tools_then_returns_final_answer() -> None:
    client = ScriptedClient(
        [
            _tool_call_response("get_latest_workflow", {}),
            _tool_call_response("list_workflow_history", {"limit": 3}, call_id="call_2"),
            _text_response("最近一次 workflow 成功，历史共 3 条。"),
        ]
    )
    registry = FakeRegistry(results={"get_latest_workflow": {"run_id": "run_1"}})
    orchestrator = MultiStepOrchestrator(
        registry=registry,
        session_repo=FakeSessionRepo(),
        client=client,
        max_steps=4,
    )

    response = orchestrator.run(_payload(), TOOL_SCHEMAS)

    assert response is not None
    assert response.success is True
    assert response.routing_method == "multi_step"
    assert [call.tool_name for call in response.tool_calls] == [
        "get_latest_workflow",
        "list_workflow_history",
    ]
    assert registry.calls[0][0] == "get_latest_workflow"
    assert registry.calls[1][1] == {"limit": 3}
    assert "最近一次 workflow 成功" in response.final_answer
    # 工具结果应回填到后续请求里
    tool_messages = [m for m in client.requests[-1] if m.get("role") == "tool"]
    assert len(tool_messages) == 2


def test_multi_step_returns_none_when_llm_unavailable() -> None:
    client = ScriptedClient([LLMClientError("connection refused")])
    orchestrator = MultiStepOrchestrator(
        registry=FakeRegistry(),
        session_repo=FakeSessionRepo(),
        client=client,
        max_steps=2,
    )

    assert orchestrator.run(_payload(), TOOL_SCHEMAS) is None


def test_multi_step_returns_none_when_client_not_configured() -> None:
    client = OpenAICompatibleClient(api_key=None, model="m", base_url="https://example.invalid/v1")
    orchestrator = MultiStepOrchestrator(
        registry=FakeRegistry(),
        session_repo=FakeSessionRepo(),
        client=client,
    )

    assert orchestrator.run(_payload(), TOOL_SCHEMAS) is None


def test_multi_step_tool_error_is_reported_to_llm_and_recorded() -> None:
    client = ScriptedClient(
        [
            _tool_call_response("get_workflow_detail", {}),
            _text_response("缺少 run_id，无法查询详情。"),
        ]
    )
    orchestrator = MultiStepOrchestrator(
        registry=FakeRegistry(),
        session_repo=FakeSessionRepo(),
        client=client,
        max_steps=3,
    )

    response = orchestrator.run(_payload(), TOOL_SCHEMAS)

    assert response is not None
    assert response.success is False
    assert response.tool_calls[0].success is False
    tool_messages = [m for m in client.requests[-1] if m.get("role") == "tool"]
    assert "error" in tool_messages[0]["content"]


def test_multi_step_summarizes_when_steps_exhausted() -> None:
    client = ScriptedClient(
        [
            _tool_call_response("get_latest_workflow", {}),
            _tool_call_response("get_latest_workflow", {}, call_id="call_2"),
            _text_response("总结：最近一次 workflow 成功。"),
        ]
    )
    orchestrator = MultiStepOrchestrator(
        registry=FakeRegistry(results={"get_latest_workflow": {"run_id": "run_1"}}),
        session_repo=FakeSessionRepo(),
        client=client,
        max_steps=2,
    )

    response = orchestrator.run(_payload(), TOOL_SCHEMAS)

    assert response is not None
    assert response.routing_method == "multi_step"
    assert "总结" in response.final_answer


def test_multi_step_clamps_max_steps() -> None:
    orchestrator = MultiStepOrchestrator(
        registry=FakeRegistry(),
        session_repo=FakeSessionRepo(),
        client=ScriptedClient([]),
        max_steps=100,
    )

    assert orchestrator.max_steps == 8


def test_multi_step_blocks_write_without_explicit_intent() -> None:
    client = ScriptedClient(
        [
            _tool_call_response("accept_paper", {"paper_id": 1}),
            _text_response("没有执行写操作。"),
        ]
    )
    registry = FakeRegistry()
    orchestrator = MultiStepOrchestrator(
        registry=registry,
        session_repo=FakeSessionRepo(),
        client=client,
        max_steps=2,
    )

    response = orchestrator.run(_payload("查看第 1 篇论文"), TOOL_SCHEMAS)

    assert response is not None
    assert response.tool_calls[0].success is False
    assert "明确表达执行意图" in response.tool_calls[0].error
    assert registry.calls == []


def test_multi_step_allows_explicit_write_once() -> None:
    client = ScriptedClient(
        [
            _tool_call_response("accept_paper", {"paper_id": 1}),
            _text_response("已接收论文。"),
        ]
    )
    registry = FakeRegistry(results={"accept_paper": {"paper_id": 1}})
    orchestrator = MultiStepOrchestrator(
        registry=registry,
        session_repo=FakeSessionRepo(),
        client=client,
        max_steps=2,
    )

    response = orchestrator.run(_payload("请接收 paper_id 1"), TOOL_SCHEMAS)

    assert response is not None
    assert response.tool_calls[0].success is True
    assert registry.calls == [("accept_paper", {"paper_id": 1})]
