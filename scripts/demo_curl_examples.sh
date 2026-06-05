#!/usr/bin/env bash
#
# Research-Agent local demo curl examples.
#
# Usage:
# 1. Start the API server first:
#    .venv/bin/uvicorn app.main:app --reload
# 2. Open http://127.0.0.1:8000/docs if you want to inspect schemas.
# 3. Manually copy and run the curl commands below.
#
# This file is intentionally a cookbook. Commands are commented out so running
# this script will not automatically create workflow runs, reports, traces, or
# feedback records.
#
# Replace placeholders before use:
# - <RUN_ID>: a workflow run id returned by POST /api/workflow/run or latest.
# - <TRACE_ID>: a RAG trace id returned by /api/rag/answer or traces/latest.
# - <PAPER_ID>: an indexed paper id, for paper-scoped RAG examples.
# - <CHUNK_ID>: an evidence chunk id, for evidence-level feedback examples.

# Base URL used by all examples.
# BASE_URL="http://127.0.0.1:8000"

# 1. Health check: verify the FastAPI service is running.
# curl "${BASE_URL}/health"

# 2. Agent help: show the unified natural-language Agent entrypoint.
# curl -X POST "${BASE_URL}/api/agent/query" \
#   -H "Content-Type: application/json" \
#   -d '{"user_id":"demo","session_id":"local_demo","message":"你能做什么"}'

# 3. Research Workflow dry_run: demonstrate the full closed loop without network.
# curl -X POST "${BASE_URL}/api/workflow/run" \
#   -H "Content-Type: application/json" \
#   -d '{
#     "topic": "large language model agent",
#     "max_results": 3,
#     "accept_top_k": 2,
#     "dry_run": true,
#     "index_rag": true
#   }'

# 4. Latest workflow: inspect the most recent workflow run.
# curl "${BASE_URL}/api/workflow/latest"

# 5. Workflow history: list recent workflow runs.
# curl "${BASE_URL}/api/workflow/history?limit=5"

# 6. Generate workflow report: replace <RUN_ID> first.
# curl -X POST "${BASE_URL}/api/workflow/<RUN_ID>/report"

# 7. Read workflow report: replace <RUN_ID> first.
# curl "${BASE_URL}/api/workflow/<RUN_ID>/report"

# 8. RAG answer: ask a question over indexed local chunks.
# If there is no evidence, the service should return a no-evidence answer
# instead of inventing document-grounded claims.
# curl -X POST "${BASE_URL}/api/rag/answer" \
#   -H "Content-Type: application/json" \
#   -d '{
#     "query": "retrieval augmented generation",
#     "top_k": 3
#   }'

# 9. RAG answer scoped to one paper: replace <PAPER_ID> first.
# curl -X POST "${BASE_URL}/api/rag/answer" \
#   -H "Content-Type: application/json" \
#   -d '{
#     "query": "planning and retrieval",
#     "top_k": 3,
#     "paper_id": "<PAPER_ID>"
#   }'

# 10. Latest RAG traces: inspect recent search/answer evidence traces.
# curl "${BASE_URL}/api/rag/traces/latest?limit=5"

# 11. RAG trace detail: replace <TRACE_ID> first.
# curl "${BASE_URL}/api/rag/traces/<TRACE_ID>"

# 12. Add trace-level feedback: replace <TRACE_ID> first.
# curl -X POST "${BASE_URL}/api/rag/traces/<TRACE_ID>/feedback" \
#   -H "Content-Type: application/json" \
#   -d '{
#     "relevance_label": "partially_relevant",
#     "expected_terms": ["retrieval", "generation"],
#     "notes": "local demo feedback"
#   }'

# 13. RAG evaluation summary: aggregate trace-level feedback.
# curl "${BASE_URL}/api/rag/evaluation/summary"

# 14. RAG evidence-level evaluation summary: Recall@K / MRR / nDCG@5.
# curl "${BASE_URL}/api/rag/evaluation/evidence-summary"

# 15. Add evidence-level feedback: replace <TRACE_ID> and <CHUNK_ID> first.
# curl -X POST "${BASE_URL}/api/rag/traces/<TRACE_ID>/evidence-feedback" \
#   -H "Content-Type: application/json" \
#   -d '{
#     "chunk_id": "<CHUNK_ID>",
#     "rank": 1,
#     "relevance_score": 2,
#     "relevance_label": "relevant",
#     "notes": "top evidence is relevant for the demo query"
#   }'

# 16. Evidence evaluation for one trace: replace <TRACE_ID> first.
# curl "${BASE_URL}/api/rag/evaluation/traces/<TRACE_ID>/evidence"
