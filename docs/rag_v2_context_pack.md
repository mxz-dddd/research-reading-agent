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

## 尚未实现

- 真实 sentence-transformers embedding。
- Qdrant 或其他生产级向量库。
- 外部 reranker。
- GraphRAG。
- 多轮 autonomous agent 规划。
