from frontend.streamlit_app import (
    LONG_REQUEST_TIMEOUT,
    WORKFLOW_REQUEST_TIMEOUT,
    request_timeout_for_path,
    response_payload_or_error,
)


class FakeResponse:
    def __init__(self, status_code: int, payload=None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if isinstance(self._payload, BaseException):
            raise self._payload
        return self._payload


def test_workflow_timeout_is_at_least_600_seconds() -> None:
    assert request_timeout_for_path("/api/workflow/run") == WORKFLOW_REQUEST_TIMEOUT
    assert WORKFLOW_REQUEST_TIMEOUT >= 600


def test_long_generation_paths_use_long_timeout() -> None:
    assert request_timeout_for_path("/api/rag/answer") == LONG_REQUEST_TIMEOUT
    assert request_timeout_for_path("/api/knowledge/generate") == LONG_REQUEST_TIMEOUT
    assert request_timeout_for_path("/api/innovation/generate") == LONG_REQUEST_TIMEOUT
    assert LONG_REQUEST_TIMEOUT >= 180


def test_http_error_includes_backend_detail() -> None:
    payload, error = response_payload_or_error(
        FakeResponse(422, {"detail": "bad payload"}),
    )

    assert payload == {"detail": "bad payload"}
    assert error == "请求失败，HTTP 422：bad payload"


def test_non_json_response_is_reported() -> None:
    payload, error = response_payload_or_error(
        FakeResponse(502, ValueError("no json"), "gateway down"),
    )

    assert payload == {"raw_response": "gateway down"}
    assert "非 JSON" in error
