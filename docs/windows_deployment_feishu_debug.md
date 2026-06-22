# Windows Deployment and Feishu Debug Log

Updated: 2026-06-16

## Environment Check

- Project root: `C:\Users\lenovo\Documents\codex-work\research-reading-agent-main`
- Python: `.venv\Scripts\python.exe`
- Python version: `Python 3.14.3`
- Python bits: `64`
- `pip check`: no broken requirements
- Core imports: `fastapi`, `uvicorn`, `streamlit`, `requests`, `httpx`, `pydantic`, `certifi`, `pypdf`, `pandas`

## Workspace Protection

- Confirmed directories:
  - `data\logs`
  - `data\debug_backups`
  - `scripts\windows`
- Git status: no `.git` directory exists in this project copy.
- Timestamped backups before edits:
  - `data\debug_backups\20260616-233816`
- `.env` was not modified and secrets were not printed.

## Changes Made

- Streamlit workflow request handling:
  - `/api/workflow/run` timeout is `600` seconds.
  - Long generation calls use `180` seconds.
  - Connection errors are the only case shown as "后端未运行".
  - Timeout, HTTP 4xx, HTTP 5xx, non-JSON responses, and generic request exceptions are handled separately.
  - The real "运行研究流程" path defaults to `dry_run=False`; the demo button still sends `dry_run=True`.
  - A running flag, spinner, and status message prevent duplicate submissions while a request is in flight.

- LLM client:
  - Centralized LLM calls in `app\core\llm_client.py`.
  - Requests use `settings.openai_base_url.rstrip("/") + "/responses"`.
  - Payloads use the Responses API `instructions` and `input[].content[].type=input_text` shape.
  - JSON bodies use `ensure_ascii=False`.
  - Response text parsing reads `output_text` and `output[].content[].text`.
  - Removed source-level `/chat/completions` usage.

- Feishu webhook:
  - URL challenge verification is preserved.
  - Verification token and optional signature checks are preserved.
  - `im.message.receive_v1` text events are acknowledged quickly and processed in `BackgroundTasks`.
  - Dedupe uses `event_id`, `uuid`, or `message_id`.
  - Duplicate events do not rerun the agent or send another reply.
  - Background exceptions are logged with `message_id`, not full message text.

## Verification Notes

Use the project venv for all commands:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_llm_client_responses.py tests\test_streamlit_request_helpers.py tests\test_feishu_webhook.py
```

Current verification results:

- Focused and nearby tests:
  - `47 passed, 1 warning`
  - Warning: `StarletteDeprecationWarning` from FastAPI TestClient dependency.
- Source scan:
  - No source-level `/chat/completions` or `/chat` API calls remain outside generated cache files.
- Backend:
  - `GET /health`: `200`, `{"status":"ok"}`
  - `GET /docs`: `200`
  - `GET /openapi.json`: `200`
  - `GET /api/papers/accepted`: `200`, 10 accepted papers observed during verification.
  - `POST /api/workflow/run` dry-run: `200`
  - Low-cost real workflow smoke test: `200`, `success=true`, `dry_run=false`, run id `f57dda4f00a142e3a331b40ca40f5410`.
  - `POST /api/knowledge/generate`: `200`, `generation_method=llm`, about 142 seconds after increasing LLM timeout to 300 seconds.
  - `POST /api/innovation/generate`: `200`, `generation_method=llm`, 8 innovation ideas, non-empty `model_inference`.
  - PaperWeave:
    - `POST /api/rag/index`: `200`, `paper_id="14"`, `chunk_count=74`.
    - `POST /api/rag/search`: `200`.
    - `POST /api/rag/answer`: `200`.
    - `GET /api/rag/traces/latest?limit=3`: `200`.
    - `GET /api/rag/context-packs`: `200`.
- Frontend:
  - Streamlit URL: `http://127.0.0.1:8501`
  - `GET http://127.0.0.1:8501`: `200`
  - Fresh frontend logs: no `Traceback`, `Exception`, `Error`, or stack dump text found.
  - Backend health stayed `200` while frontend was running.

Backend logs should be written to:

- `data\logs\backend.stdout.log`
- `data\logs\backend.stderr.log`
- `data\logs\backend.pid`

Frontend logs should be written to:

- `data\logs\frontend.stdout.log`
- `data\logs\frontend.stderr.log`
- `data\logs\frontend.pid`
