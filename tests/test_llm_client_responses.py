import json

from app.core.llm_client import OpenAICompatibleClient


def test_responses_url_uses_configured_base_url() -> None:
    client = OpenAICompatibleClient(
        api_key="key",
        model="model",
        base_url="https://example.invalid/v1/",
    )

    assert client.responses_url == "https://example.invalid/v1/responses"


def test_extract_text_reads_responses_output_content() -> None:
    data = {
        "output": [
            {
                "type": "message",
                "content": [
                    {"type": "output_text", "text": "hello"},
                    {"type": "output_text", "text": " world"},
                ],
            }
        ]
    }

    assert OpenAICompatibleClient.extract_text(data) == "hello world"


def test_extract_tool_calls_reads_responses_function_call() -> None:
    data = {
        "output": [
            {
                "type": "function_call",
                "call_id": "call_1",
                "name": "run_research_workflow",
                "arguments": json.dumps({"dry_run": False}),
            }
        ]
    }

    assert OpenAICompatibleClient.extract_tool_calls(data) == [
        {
            "id": "call_1",
            "name": "run_research_workflow",
            "arguments": {"dry_run": False},
        }
    ]
