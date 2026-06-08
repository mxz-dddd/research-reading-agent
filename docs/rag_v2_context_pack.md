# RAG v2 与 Context Pack

本文说明当前本地 RAG v2 的第一阶段实现。它仍然是轻量本地方案，不依赖外部 API，不要求 OpenAI Key，也没有引入 Qdrant。

## RAG v2 Pipeline

`POST /api/rag/index` 会把论文文本切成 contextual chunks。每个 chunk 会保存：

- `contextual_header`：论文标题、章节、chunk 序号、来源类型。
- `section_title`：从 `Abstract`、`Introduction`、`Methods`、`Conclusion` 等标题中轻量识别。
- `content_for_embedding`：`contextual_header + content`，用于 dense retrieval。
- `token_count`、`chunker_version`、`index_version`。

`POST /api/rag/search` 和 `POST /api/rag/answer` 默认使用 hybrid 模式：

1. sparse retrieval：复用原 keyword / token overlap 检索。
2. dense retrieval：使用纯 Python hash embedding 计算 cosine similarity。
3. RRF fusion：用 Reciprocal Rank Fusion 合并 sparse / dense 排名。
4. deterministic rerank：综合 fused score、query token overlap、phrase match、section/header 命中。
5. trace metadata：记录 `retrieval_mode`、`pipeline`、`context_pack_id`。

keyword 模式仍然保留。请求中传 `retrieval_mode="keyword"` 即可走 RAG v1 fallback。

## Context Pack

每次 search / answer 会生成一条 Context Pack，保存到 SQLite `context_packs` 表。结构包括：

```json
{
  "context_pack_id": "ctx_xxx",
  "user_id": "default",
  "session_id": "default",
  "query": "问题",
  "mode": "search 或 answer",
  "paper_id": "可选论文 ID",
  "token_budget": 6000,
  "estimated_tokens": 123,
  "item_count": 2,
  "items": [
    {
      "item_type": "session_recent_search_results",
      "source_type": "session_state",
      "content": "[...]",
      "metadata": {"count": 3}
    },
    {
      "item_type": "rag_evidence",
      "source_type": "rag_chunk",
      "source_id": "chunk-id",
      "content": "Paper: ...\nSection: ...\nChunk: ...\n...",
      "score": 1.23,
      "metadata": {
        "paper_id": "12",
        "chunk_index": 0,
        "section_title": "Introduction",
        "retrieval_scores": {"sparse": 2.0, "dense": 0.4, "rrf": 0.03},
        "score_reason": "..."
      }
    }
  ]
}
```

当前 token 估算使用 `len(text) // 4` 的粗略方法。超出预算时优先保留 active paper 和靠前 evidence，recent search results 可以被截断。

## 环境变量

```bash
# keyword / hybrid
RAG_RETRIEVAL_MODE=hybrid

# 当前只实现 hash
RAG_EMBEDDING_PROVIDER=hash
RAG_EMBEDDING_DIM=256

# RRF 和 rerank
RAG_RRF_K=60
RAG_RERANK_ENABLED=true

# Context Pack 粗略 token 预算
RAG_CONTEXT_TOKEN_BUDGET=6000
```

## curl 示例

建立索引：

```bash
curl -X POST http://127.0.0.1:8000/api/rag/index \
  -H "Content-Type: application/json" \
  -d '{
    "paper_id": "12",
    "chunk_size": 800,
    "chunk_overlap": 120,
    "index_version": "hybrid_v2",
    "chunker_version": "contextual_v1"
  }'
```

hybrid 检索：

```bash
curl -X POST http://127.0.0.1:8000/api/rag/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "main contribution",
    "top_k": 5,
    "paper_id": "12",
    "user_id": "default",
    "session_id": "default",
    "retrieval_mode": "hybrid"
  }'
```

RAG 回答：

```bash
curl -X POST http://127.0.0.1:8000/api/rag/answer \
  -H "Content-Type: application/json" \
  -d '{
    "query": "这篇论文的主要贡献是什么？",
    "top_k": 5,
    "paper_id": "12",
    "user_id": "default",
    "session_id": "default"
  }'
```

## RAG v2 Debugger / 可观测性

### 前端 RAG v2 调试台

Streamlit 前端新增入口：`RAG v2 调试台`。这个页面用于调试 contextual hybrid RAG 的 evidence、Context Pack 和 pipeline，不改变后端检索算法本身。

页面支持：

- 运行 RAG Search。
- 运行 RAG Answer。
- 选择 `retrieval_mode`：`hybrid` / `keyword`。
- 指定 `user_id`、`session_id`、`paper_id`、`top_k`、`query`。
- 查看回答结果。
- 查看 Evidence Debugger。
- 查看 Context Pack Viewer。
- 查看 Pipeline Viewer。
- 查看 raw response JSON。

### Evidence Debugger

Evidence Debugger 会把返回的 evidence 整理成表格，并保留每条 evidence 的展开详情。展示字段包括：

- `rank`
- `paper_id`
- `section_title`
- `chunk_index`
- `score`
- `sparse_score`
- `dense_score`
- `rrf_score`
- `rerank_score`
- `score_reason`
- `content_preview`
- `contextual_header`
- raw JSON

它主要用于判断 sparse、dense、RRF、rerank 哪一阶段影响了最终 evidence，也可以排查检索命中是否来自正文、`section_title`、`contextual_header` 或 token overlap。

### Context Pack Viewer

Context Pack Viewer 展示一次 search / answer 构造出的上下文摘要，包括：

- `context_pack_id`
- `estimated_tokens` / `token_budget` / `item_count`
- 按 `item_type` 分组查看 items
- 根据 `context_pack_id` 加载历史 Context Pack
- raw JSON，用于复现某次回答上下文

`item_type` 可能包括：

- `rag_evidence`
- `active_paper`
- `session_recent_search_results`

这些不是唯一取值，后续可以继续增加新的上下文来源。

### Pipeline Viewer

Pipeline Viewer 展示当前 response 中的 pipeline 字段，主要包括：

- `retrieval_mode`
- `sparse_candidate_count`
- `dense_candidate_count`
- `fused_candidate_count`
- `rerank_enabled`
- `embedding_provider`
- `rrf_k`

它用于快速确认当前回答实际走的是 `keyword` 还是 `hybrid`，也用于确认 candidate 数量、RRF、rerank 和 embedding provider 配置。

### Context Pack 查询 API

读取单个 Context Pack：

```text
GET /api/rag/context-packs/{context_pack_id}
```

返回单个 Context Pack。不存在时返回 404，`detail` 包含 `context_pack_id not found`。

查看指定用户和会话最近生成的 Context Packs：

```text
GET /api/rag/context-packs?user_id=default&session_id=default&limit=10
```

返回结构：

```json
{
  "items": [],
  "count": 0
}
```

`limit` 范围是 1 到 50。这个接口主要用于调试最近生成的 Context Packs。

### API smoke test 脚本

本地 smoke 脚本路径：

```text
scripts/smoke_rag_v2.py
```

支持参数：

- `--base-url`
- `--paper-id`
- `--query`
- `--top-k`
- `--retrieval-mode`
- `--user-id`
- `--session-id`

执行链路：

- `GET /health`
- 可选 `POST /api/rag/index`
- `POST /api/rag/search`
- `POST /api/rag/answer`
- 如果返回 `context_pack_id`，则 `GET /api/rag/context-packs/{context_pack_id}`

示例命令：

```bash
.venv/bin/python scripts/smoke_rag_v2.py \
  --base-url http://127.0.0.1:8000 \
  --paper-id 1 \
  --query "这篇论文的方法和实验结论是什么？" \
  --retrieval-mode hybrid
```

### 当前边界

- 当前没有接入 Qdrant。
- 当前没有接入 sentence-transformers。
- 当前没有接入外部 reranker。
- 当前没有实现 GraphRAG。
- 尚未接入 Qdrant，尚未接入 sentence-transformers，尚未实现 GraphRAG。
- 当前 hash embedding 是为了本地可测、可回归、无外部依赖。
- 当前 Debugger 是可观测性工具，不改变 RAG 检索算法本身。

## RAG v2 Golden Queries / 质量评估

Golden queries 是一组本地 JSONL 测试问题，用来比较 `hybrid` / `keyword` 等 `retrieval_mode` 的检索质量，并为后续替换 embedding、Qdrant、reranker 前建立可回归基线。

示例文件：

```text
eval/golden_queries.example.jsonl
```

每行是一个 JSON object，字段包括：

```json
{
  "query_id": "gq-001",
  "query": "这篇论文的核心方法是什么？",
  "paper_id": null,
  "expected_terms": ["method", "approach"],
  "expected_chunk_ids": [],
  "expected_paper_ids": [],
  "must_contain_any": ["方法", "method", "approach"],
  "notes": "示例问题，用于测试方法类问题的检索。"
}
```

字段说明：

- `query_id`：唯一 ID。
- `query`：用户问题。
- `paper_id`：可选论文 ID；为空时不限定论文。
- `expected_terms`：期望 evidence 中出现的关键词。
- `expected_chunk_ids`：期望命中的 chunk id，可为空。
- `expected_paper_ids`：期望命中的 paper id，可为空。
- `must_contain_any`：用于 answer 文本的轻量命中检查，可为空。
- `notes`：备注。

本地私有评估集建议从 example 复制：

```bash
cp eval/golden_queries.example.jsonl eval/golden_queries.local.jsonl
```

`eval/golden_queries.local.jsonl`、`eval/*.local.jsonl` 和 `eval/rag_eval_runs/` 已被 git ignore，避免把本地评估数据和运行结果提交到仓库。

运行 search 评估：

```bash
.venv/bin/python scripts/eval_rag_v2.py \
  --base-url http://127.0.0.1:8000 \
  --golden-file eval/golden_queries.example.jsonl \
  --retrieval-modes hybrid,keyword \
  --top-k 5
```

同时运行 answer 并检查 `must_contain_any`：

```bash
.venv/bin/python scripts/eval_rag_v2.py \
  --base-url http://127.0.0.1:8000 \
  --golden-file eval/golden_queries.example.jsonl \
  --retrieval-modes hybrid,keyword \
  --top-k 5 \
  --run-answer
```

输出 JSON 包含：

- `summary`：整体指标摘要。
- `results`：每个 query / retrieval mode 的详细结果。

当前指标包括：

- `expected_terms` recall。
- `expected_chunk_ids` recall。
- `expected_paper_ids` recall。
- `answer_contains_any_rate`。

这些指标可以用于比较 `hybrid` / `keyword`，也可以作为后续版本对比的基础。

当前边界：

- 不是 LLM-as-judge。
- 不调用外部 API。
- 不替代人工评估。
- 这是后续更换 embedding、Qdrant、reranker 前的基线机制。

## 尚未实现

- 真实 sentence-transformers embedding。
- Qdrant 或其他生产级向量库。
- 外部 reranker。
- GraphRAG。
- 多轮 autonomous agent 规划。
