# 核心接口验收清单

本文档基于当前代码中的真实 FastAPI 路由整理，用于本地验收、接口说明和后续测试补充。当前后端启动入口为 `app.main:app`，除 `/health` 外，业务接口都挂在 `/api` 前缀下。

## 1. 健康检查

### GET /health

- Method: `GET`
- URL: `/health`
- 请求体示例：无
- 返回字段说明：
  - `status`: 服务状态，当前成功时返回 `ok`
- 主流程作用：
  - 用于确认 FastAPI 服务已启动，并且应用可以正常响应请求。
- 对外说明：
  - 这是最小可用性检查接口，不依赖数据库写入或外部 API，适合做本地启动后的第一步验证。

## 2. Topics 研究方向接口

### POST /api/topics

- Method: `POST`
- URL: `/api/topics`
- 请求体示例：

```json
{
  "title": "large language model medical imaging",
  "description": "关注多模态大模型在医学影像中的研究"
}
```

- 返回字段说明：
  - `id`: 研究方向 ID
  - `title`: 研究方向标题
  - `description`: 研究方向补充说明
  - `created_at`: 创建时间
  - `updated_at`: 更新时间
- 主流程作用：
  - 保存一个研究主题，后续论文搜索可以通过 `topic_id` 关联到该主题。
- 对外说明：
  - topics 是研究任务的上层组织结构，帮助把论文搜索、归档和知识树结果按研究方向聚合。

### GET /api/topics

- Method: `GET`
- URL: `/api/topics`
- 请求体示例：无
- 返回字段说明：
  - 返回 `TopicRead` 列表，每项包含 `id`、`title`、`description`、`created_at`、`updated_at`
- 主流程作用：
  - 查看当前已保存的研究方向。
- 对外说明：
  - 这是研究方向列表接口，用于让前端或 Agent 选择已有研究主题。

## 3. Papers 论文接口

### POST /api/papers/search

- Method: `POST`
- URL: `/api/papers/search`
- 请求体示例：

```json
{
  "topic": "large language model medical imaging",
  "max_results": 3,
  "topic_id": 1
}
```

兼容旧字段：

```json
{
  "query": "large language model medical imaging",
  "limit": 3
}
```

- 返回字段说明：
  - 返回 `PaperRead` 列表
  - 主要字段包括 `id`、`topic_id`、`title`、`authors`、`abstract`、`url`、`source`、`published_at`
  - 初筛字段包括 `screening_summary`、`relevance_score`、`worth_reading`
  - 状态和归档字段包括 `is_accepted`、`status`、`ingest_status`、`local_pdf_path`、`local_text_path`、`local_summary_path`
- 主流程作用：
  - 根据研究主题搜索候选论文，当前优先 arXiv；arXiv 网络或解析失败时使用 mock fallback，保证接口可演示。
- 对外说明：
  - 这是 Research Agent 的论文发现入口，会把搜索结果落库，并为每篇论文生成一个中文初筛结果。

### GET /api/papers/search-history

- Method: `GET`
- URL: `/api/papers/search-history`
- 请求体示例：无
- 返回字段说明：
  - `id`: 搜索历史 ID
  - `topic`: 搜索主题
  - `source`: 搜索来源，例如 `arxiv` 或 `mock`
  - `result_count`: 返回论文数量
  - `query_text`: 查询摘要和 fallback 原因
  - `created_at`: 创建时间
- 主流程作用：
  - 查看论文搜索记录，方便排查搜索来源和 fallback 情况。
- 对外说明：
  - 这个接口让系统具备可追踪性，能说明每次搜索是来自真实 arXiv 还是 fallback。

### GET /api/papers

- Method: `GET`
- URL: `/api/papers`
- 请求体示例：无
- 可选查询参数：
  - `status`: 按论文状态过滤，例如 `found`、`accepted`、`ingested`
- 返回字段说明：
  - 返回 `PaperRead` 列表
- 主流程作用：
  - 查看当前入库论文，可按状态过滤。
- 对外说明：
  - 这是论文库的通用列表接口，适合做管理页或调试入口。

### POST /api/papers/accept

- Method: `POST`
- URL: `/api/papers/accept`
- 请求体示例：

```json
{
  "paper_id": 1
}
```

也支持按 URL 接收：

```json
{
  "url": "https://arxiv.org/abs/2604.19412v1"
}
```

- 返回字段说明：
  - 返回接收后的 `PaperRead`
  - 关键字段包括 `is_accepted`、`accepted_at`、`pdf_url`、`status`、`ingest_status`
- 主流程作用：
  - 把候选论文标记为已接收，表示它进入后续精读、归档、知识树和创新点分析流程。
- 对外说明：
  - accept 是从“候选论文”进入“研究材料库”的人工确认步骤，避免所有搜索结果都进入后续分析。

### POST /api/papers/ingest

- Method: `POST`
- URL: `/api/papers/ingest`
- 请求体示例：

```json
{
  "paper_id": 1
}
```

- 返回字段说明：
  - 返回 ingest 后的 `PaperRead`
  - `pdf_url`: 推断或保存的 PDF 地址
  - `local_pdf_path`: 本地 PDF 路径
  - `local_text_path`: 本地文本路径
  - `local_summary_path`: 深度总结 Markdown 路径
  - `abstract_summary`: 摘要级总结
  - `deep_summary`: 深度总结内容
  - `ingest_status`: `pdf_text` 或 `abstract_only`
  - `status`: 当前会更新为 `ingested`
- 主流程作用：
  - 对已接收论文做深入阅读归档，优先下载 PDF 并提取文本；失败时降级为 abstract-only。
- 对外说明：
  - ingest 是把论文从数据库记录转成可分析材料的步骤，为知识树和创新点挖掘提供更高质量输入。

### GET /api/papers/accepted

- Method: `GET`
- URL: `/api/papers/accepted`
- 请求体示例：无
- 返回字段说明：
  - 返回 `is_accepted = 1` 的 `PaperRead` 列表
- 主流程作用：
  - 查看当前已进入研究材料库的论文。
- 对外说明：
  - 知识树和创新点模块只基于已接收论文生成，accepted 列表就是这些下游模块的数据基础。

### GET /api/papers/{paper_id}

- Method: `GET`
- URL: `/api/papers/{paper_id}`
- 请求体示例：无
- 返回字段说明：
  - 返回单篇论文的 `PaperRead`
- 主流程作用：
  - 查看论文详情，包括初筛、接收状态、ingest 状态和本地归档路径。
- 对外说明：
  - 这是论文详情接口，适合前端详情页或 Agent 回答“某篇论文现在状态如何”。

### POST /api/papers/{paper_id}/save

- Method: `POST`
- URL: `/api/papers/{paper_id}/save`
- 请求体示例：无
- 返回字段说明：
  - 返回更新状态后的 `PaperRead`
  - 当前主要变化是 `status` 更新为 `saved`
- 主流程作用：
  - 当前是一个轻量状态更新接口。
- 对外说明：
  - 这个接口保留了论文保存状态能力，但主流程里更关键的是 accept 和 ingest。

## 4. Knowledge 知识树接口

### POST /api/knowledge/generate

- Method: `POST`
- URL: `/api/knowledge/generate`
- 请求体示例：

```json
{}
```

按主题过滤：

```json
{
  "topic": "medical imaging"
}
```

- 返回字段说明：
  - `id`: 知识树归档 ID
  - `topic`: 可选主题
  - `source_paper_count`: 来源论文数
  - `knowledge_tree_markdown`: 知识树 Markdown
  - `learning_roadmap_markdown`: 学习路径 Markdown
  - `mermaid_mindmap`: Mermaid mindmap
  - `mermaid_flowchart`: Mermaid flowchart
  - `local_markdown_path`: 本地归档路径
  - `generation_method`: `llm` 或 `fallback`
  - `created_at`: 创建时间
- 主流程作用：
  - 基于已接收论文生成知识结构和学习路径。当前至少需要 2 篇已接收论文。
- 对外说明：
  - 知识树模块把零散论文整理成可学习的结构，既能用 LLM，也有规则 fallback 保证可运行。

### GET /api/knowledge/latest

- Method: `GET`
- URL: `/api/knowledge/latest`
- 请求体示例：无
- 返回字段说明：
  - 返回最近一次 `KnowledgeArtifactRead`
- 主流程作用：
  - 查看最近生成的知识树。
- 对外说明：
  - 用于前端或 Agent 快速获取最新知识树结果。

### GET /api/knowledge/history

- Method: `GET`
- URL: `/api/knowledge/history`
- 请求体示例：无
- 返回字段说明：
  - 返回知识树历史列表
- 主流程作用：
  - 查看过去生成的知识树归档。
- 对外说明：
  - 支持结果版本追踪，便于对比不同时间或不同 topic 的生成结果。

## 5. Innovation 创新点接口

### POST /api/innovation/generate

- Method: `POST`
- URL: `/api/innovation/generate`
- 请求体示例：

```json
{}
```

按主题过滤：

```json
{
  "topic": "medical imaging"
}
```

- 返回字段说明：
  - `id`: 创新点归档 ID
  - `topic`: 可选主题
  - `source_paper_count`: 来源论文数
  - `innovation_markdown`: 创新点分析 Markdown
  - `innovation_json`: 结构化创新点 JSON
  - `summary_markdown`: 简短总结 Markdown
  - `generation_method`: `llm` 或 `fallback`
  - `local_markdown_path`: Markdown 本地归档路径
  - `local_json_path`: JSON 本地归档路径
  - `created_at`: 创建时间
- 主流程作用：
  - 基于已接收论文和最近知识树挖掘 research gap 与候选创新方向。当前至少需要 2 篇已接收论文。
- 对外说明：
  - 创新点模块把“读过的论文”转成“下一步能做什么”的研究建议，并明确区分论文证据和模型推断。

### GET /api/innovation/latest

- Method: `GET`
- URL: `/api/innovation/latest`
- 请求体示例：无
- 返回字段说明：
  - 返回最近一次 `InnovationArtifactRead`
- 主流程作用：
  - 查看最近生成的创新点分析。
- 对外说明：
  - 用于快速获取当前最晚一次创新方向总结。

### GET /api/innovation/history

- Method: `GET`
- URL: `/api/innovation/history`
- 请求体示例：无
- 返回字段说明：
  - 返回创新点历史列表
- 主流程作用：
  - 查看过去生成的创新点归档。
- 对外说明：
  - 支持创新点分析结果留痕，方便复盘和比较。

## 6. RAG v1 检索增强接口

### POST /api/rag/index

- Method: `POST`
- URL: `/api/rag/index`
- 请求体示例：

```json
{
  "paper_id": "12",
  "chunk_size": 800,
  "chunk_overlap": 120
}
```

- 返回字段说明：
  - `success`: 是否索引成功
  - `paper_id`: 论文 ID
  - `chunk_count`: 生成 chunk 数量
  - `warnings`: 降级读取文本等提醒
  - `error`: 失败原因
- 主流程作用：
  - 读取已 ingest 论文的 `local_text_path`，切分为 chunks，并保存到 SQLite `rag_chunks` 表。
  - 如果本地文本不存在，会兼容使用 `local_summary_path`、`deep_summary`、`abstract_summary` 或 `abstract`。
- 对外说明：
  - 这是轻量 RAG v1 的索引入口，先用 SQLite 和本地文本跑通检索增强链路，不接 Qdrant，也不调用 embedding。

### POST /api/rag/search

- Method: `POST`
- URL: `/api/rag/search`
- 请求体示例：

```json
{
  "query": "propagation error",
  "top_k": 5,
  "paper_id": "12"
}
```

- 返回字段说明：
  - `success`: 是否检索成功
  - `query`: 原始查询
  - `evidence_chunks`: 命中的 evidence chunks，包含 `score`、`chunk_id`、`paper_id`、`chunk_index`、`matched_terms`、`content`、`content_preview`、`source_path`、`metadata`、`score_reason`
  - `message`: 没有命中时的提示
  - `no_evidence`: 是否没有找到证据
  - `error`: 结构化失败原因，例如空 query
  - `trace_id`: 本次检索保存的 RAG evidence trace ID；空 query 或关闭保存时为 `null`
  - `trace_warning`: trace 保存失败时的提示
- 主流程作用：
  - 在已索引 chunks 中做本地关键词 / token overlap 检索。
- 对外说明：
  - 当前是可控的本地检索版本，适合先验证 evidence retrieval 链路；`matched_terms` 和 `score_reason` 用来解释为什么召回某个 chunk，后续可以替换为 embedding 或 hybrid retrieval。

### POST /api/rag/answer

- Method: `POST`
- URL: `/api/rag/answer`
- 请求体示例：

```json
{
  "query": "What is the main contribution?",
  "top_k": 5,
  "paper_id": "12"
}
```

- 返回字段说明：
  - `success`: 是否成功
  - `query`: 原始问题
  - `answer`: 基于 evidence chunks 的模板化保守回答
  - `evidence_chunks`: 用于回答的证据片段
  - `warning`: 当前 RAG v1 的能力边界提示
  - `no_evidence`: 没有 evidence 时为 `true`
  - `error`: 结构化失败原因，例如空 query
  - `trace_id`: 本次问答保存的 RAG evidence trace ID；空 query 或关闭保存时为 `null`
  - `trace_warning`: trace 保存失败时的提示
- 主流程作用：
  - 先检索 evidence chunks，再基于 evidence 生成保守回答。
  - 默认保存 RAG evidence trace，便于后续复盘 query、evidence 和 answer。
- 对外说明：
  - 这个接口不调用 LLM，先用模板保证回答不会越过证据；有 evidence 时展示 `[Evidence 1]` 编号，没有 evidence 时明确不回答，后续可接 LLM 做证据融合生成。

### GET /api/rag/traces/latest

- Method: `GET`
- URL: `/api/rag/traces/latest`
- 请求体示例：无
- 可选查询参数：
  - `limit`: 返回条数，默认 10
- 返回字段说明：
  - `success`: 查询是否成功
  - `items`: 最近 RAG traces，包含 `trace_id`、`query`、`mode`、`paper_id`、`top_k`、`hit_count`、`no_evidence`、`created_at`
- 主流程作用：
  - 查看最近 RAG search / answer 的证据记录。
- 对外说明：
  - 这个接口让 RAG 不只是返回一次结果，还能把 evidence retrieval 过程保存下来，方便人工复盘。

### GET /api/rag/traces/{trace_id}

- Method: `GET`
- URL: `/api/rag/traces/{trace_id}`
- 请求体示例：无
- 返回字段说明：
  - `success`: 查询是否成功
  - `data`: 单次 RAG trace 详情，包含 query、answer、evidence、metadata
- 主流程作用：
  - 根据 trace_id 查看某次 RAG 检索或问答的完整证据。
- 对外说明：
  - 这个接口适合做 RAG 复盘页，能看到当时召回了哪些 chunks，以及为什么回答或拒答。

### GET /api/rag/traces/by-paper/{paper_id}

- Method: `GET`
- URL: `/api/rag/traces/by-paper/{paper_id}`
- 请求体示例：无
- 可选查询参数：
  - `limit`: 返回条数，默认 10
- 返回字段说明：
  - `success`: 查询是否成功
  - `items`: 该论文相关 RAG traces
- 主流程作用：
  - 查看某篇论文被检索或问答引用过的记录。
- 对外说明：
  - 这个接口可以帮助分析某篇论文在 RAG 问答中的使用情况，为后续人工标注和评估做准备。

### POST /api/rag/traces/{trace_id}/feedback

- Method: `POST`
- URL: `/api/rag/traces/{trace_id}/feedback`
- 请求体示例：

```json
{
  "relevance_label": "relevant",
  "expected_terms": ["retrieval", "agent"],
  "notes": "Top evidence contains the expected concept."
}
```

- 返回字段说明：
  - `success`: 是否保存成功
  - `data`: feedback 详情，包含 `feedback_id`、`trace_id`、`relevance_label`、`expected_terms`、`notes`、`created_at`
  - `message`: trace 不存在或无 feedback 时的提示
  - `error`: label 非法或 trace 不存在等错误
- 主流程作用：
  - 为某次 RAG trace 添加人工相关性标注。
- 对外说明：
  - 这是 trace-based RAG 评估闭环的人工标注入口。允许同一 trace 多次标注，评估默认使用最新一条 feedback。

### GET /api/rag/evaluation/summary

- Method: `GET`
- URL: `/api/rag/evaluation/summary`
- 请求体示例：无
- 返回字段说明：
  - `success`: 查询是否成功
  - `summary.total_traces`: trace 总数
  - `summary.answered_traces`: answer trace 数量
  - `summary.no_evidence_traces`: no evidence trace 数量
  - `summary.total_feedback`: 使用最新 feedback 统计的 trace 数量
  - `summary.relevance_rate`: `relevant + partially_relevant` 占比
  - `summary.no_evidence_accuracy`: no evidence 标注正确率；无法计算时为 `null`
  - `summary.label_distribution`: label 分布
- 主流程作用：
  - 汇总 RAG trace feedback，形成轻量检索质量统计。
- 对外说明：
  - 这个接口不是自动评估模型，而是基于人工 feedback 统计检索质量，用于后续评估集和 RAGAS 升级。

### GET /api/rag/evaluation/traces/{trace_id}

- Method: `GET`
- URL: `/api/rag/evaluation/traces/{trace_id}`
- 请求体示例：无
- 返回字段说明：
  - `success`: 查询是否成功
  - `trace`: RAG trace 详情
  - `latest_feedback`: 最新人工 feedback；没有时为 `null`
  - `message`: 没有 feedback 或 trace 不存在时的提示
- 主流程作用：
  - 查看单条 trace 的证据和最新人工标注。
- 对外说明：
  - 这个接口把“检索证据”和“人工评价”放在一起，适合做 RAG 误召回分析和复盘。

### POST /api/rag/traces/{trace_id}/evidence-feedback

- Method: `POST`
- URL: `/api/rag/traces/{trace_id}/evidence-feedback`
- 请求体示例：

```json
{
  "chunk_id": "chunk_abc",
  "rank": 1,
  "relevance_score": 2,
  "notes": "This chunk directly answers the query."
}
```

- 返回字段说明：
  - `success`: 是否保存成功
  - `data`: evidence feedback 详情，包含 `evidence_feedback_id`、`trace_id`、`chunk_id`、`rank`、`relevance_score`、`relevance_label`
  - `message`: trace 不存在、chunk 不属于 trace 或 rank 越界时的提示
  - `error`: 结构化错误
- 主流程作用：
  - 对单条 evidence chunk 做精细相关性标注。
- 对外说明：
  - trace-level feedback 评价整次 RAG 结果，evidence-level feedback 评价每个召回片段，为 Recall@K、MRR 和 nDCG 做准备。

### GET /api/rag/evaluation/evidence-summary

- Method: `GET`
- URL: `/api/rag/evaluation/evidence-summary`
- 可选查询参数：
  - `trace_id`: 只统计某条 trace
- 返回字段说明：
  - `total_traces_with_evidence_feedback`: 有 evidence 标注的 trace 数
  - `total_evidence_feedback`: 使用最新标注统计的 evidence 数
  - `relevant_evidence_count`: 相关 evidence 数
  - `partially_relevant_evidence_count`: 部分相关 evidence 数
  - `irrelevant_evidence_count`: 不相关 evidence 数
  - `recall_at_1` / `recall_at_3` / `recall_at_5`: top-K 中是否至少有一个相关 evidence
  - `mrr`: 第一个相关 evidence 的平均 reciprocal rank
  - `ndcg_at_5`: 基于 `relevance_score` 的轻量 nDCG@5
- 主流程作用：
  - 基于人工 evidence feedback 统计轻量排序指标。
- 对外说明：
  - 当前不是自动语义评估，而是先用人工标注构建可解释的排序评估闭环。

### GET /api/rag/evaluation/traces/{trace_id}/evidence

- Method: `GET`
- URL: `/api/rag/evaluation/traces/{trace_id}/evidence`
- 请求体示例：无
- 返回字段说明：
  - `success`: 查询是否成功
  - `trace_id`: trace ID
  - `evidence`: evidence 列表，每项包含 `rank`、`chunk_id`、`score`、`content_preview`、`latest_feedback`
  - `message`: 暂无 evidence feedback 或 trace 不存在时的提示
- 主流程作用：
  - 查看某条 trace 的证据级标注详情。
- 对外说明：
  - 这个接口能展示每个 evidence chunk 的人工相关性，是后续可视化和排序评估的基础。

## 7. Agent 统一查询接口

### POST /api/agent/query

- Method: `POST`
- URL: `/api/agent/query`
- 请求体示例：

```json
{
  "user_id": "demo",
  "session_id": "s1",
  "message": "搜索 large language model medical imaging 论文，给我 2 篇",
  "topic_id": 1
}
```

兼容旧字段：

```json
{
  "query": "帮我搜索多模态大模型在医学影像中的论文"
}
```

- 返回字段说明：
  - `success`: 是否成功
  - `intent`: 识别出的意图
  - `chosen_tool`: 实际选择的工具
  - `tool_calls`: 工具调用记录
  - `final_answer`: 给用户看的最终回答
  - `data`: 工具返回的结构化数据
  - `error`: 错误信息
  - `routing_method`: `llm` 或 `fallback`
  - `answer`: 兼容旧字段，当前等同于 `final_answer`
  - `used_tool`: 兼容旧字段，当前等同于 `chosen_tool`
- 主流程作用：
  - 统一承接自然语言请求，把请求路由到搜索、接收、精读、查看详情、知识树或创新点工具。
- 对外说明：
  - 当前 Agent 是“单轮单工具编排层”：先识别意图，再解析参数，调用工具，最后用模板生成 `final_answer`。没有 OpenAI key 时会走关键词和正则 fallback。

## 8. Research Workflow 闭环接口

### POST /api/workflow/run

- Method: `POST`
- URL: `/api/workflow/run`
- 请求体示例：

```json
{
  "topic": "large language model agent",
  "max_results": 5,
  "accept_top_k": 2,
  "ingest": true,
  "index_rag": true,
  "rag_chunk_size": 800,
  "rag_chunk_overlap": 120,
  "generate_knowledge": true,
  "generate_innovation": true,
  "dry_run": false
}
```

无网络演示模式：

```json
{
  "topic": "large language model agent",
  "max_results": 3,
  "accept_top_k": 2,
  "dry_run": true
}
```

- 返回字段说明：
  - `run_id`: 本次 workflow run 的唯一 ID，可用于后续查询详情
  - `success`: workflow 是否整体成功
  - `topic`: 研究方向
  - `dry_run`: 是否使用模拟数据演示模式
  - `steps`: 每一步执行结果，包括 `step`、`success`、`summary`、`data`、`error`
  - `searched_papers`: 搜索到的论文摘要列表
  - `accepted_papers`: 自动接收的论文摘要列表
  - `ingested_papers`: 深入阅读成功的论文摘要列表
  - `rag_indexed_papers`: RAG v1 索引结果列表，包含 `paper_id`、`success`、`chunk_count`、`warnings`、`error`
  - `knowledge`: 知识树生成结果摘要；跳过或失败时为 `null`
  - `innovation`: 创新点生成结果摘要；跳过或失败时为 `null`
  - `warnings`: 单步失败或覆盖不足等提醒
  - `error`: 整体失败原因
- 主流程作用：
  - 把论文搜索、自动接收、ingest、RAG v1 索引、知识树生成和创新点挖掘串成一个固定科研闭环。
  - `index_rag=true` 时，workflow 会在 ingest 后为成功深入阅读的论文建立本地 SQLite RAG chunks；单篇索引失败只进入 warnings，不中断整体 workflow。
  - 执行结束后会把 workflow 结果保存到 `workflow_runs`，用于查询最近一次结果、历史记录和单次详情。
  - `dry_run=true` 时返回明确标注为 `dry_run/mock` 的模拟结果，包括模拟 RAG 索引结果；不代表真实论文检索、真实 RAG chunks 或真实生成结果。
- 对外说明：
  - 这是 Research Agent 的复合工具接口。它不是开放式多步 planner，而是一个可控、可测试的固定 workflow，用于完整演示从研究方向到创新点的闭环。
  - 为了方便验收，接口提供 dry_run 演示模式，能在不调用 arXiv、OpenAI、PDF 下载、不写 papers / knowledge / innovation 业务表的情况下展示完整响应结构；dry_run run 本身仍会保存到 `workflow_runs`，并带有 `dry_run=true` 标记。
  - 现在 workflow 不只是一次性返回结果，还会保存 run_id、统计信息、warnings 和完整 result，方便复盘研究过程。
  - RAG v1 已接入 workflow 主链路，但仍是本地关键词 / token overlap 检索增强，不是 Qdrant 或 embedding 语义检索。

### GET /api/workflow/latest

- Method: `GET`
- URL: `/api/workflow/latest`
- 请求体示例：无
- 返回字段说明：
  - `success`: 是否找到最近一次记录
  - `data`: 最近一次 `WorkflowRunDetail`，没有记录时为 `null`
  - `message`: 没有记录时的结构化提示
- 主流程作用：
  - 查看最近一次研究闭环运行结果。
- 对外说明：
  - 这个接口让 workflow 有了“可复盘”的状态，不需要用户记住上一次返回内容。

### GET /api/workflow/history

- Method: `GET`
- URL: `/api/workflow/history`
- 请求体示例：无
- 可选查询参数：
  - `limit`: 返回条数，默认 10，范围 1 到 100
- 返回字段说明：
  - `success`: 查询是否成功
  - `items`: `WorkflowRunSummary` 列表，包含 `run_id`、`topic`、`success`、`dry_run`、数量统计、`warnings`、`error`、`created_at`
  - 历史列表不返回完整 `result`，避免响应过大
- 主流程作用：
  - 查看最近的 workflow run 摘要列表。
- 对外说明：
  - 这个接口适合做历史页或调试页，能快速看每次研究闭环是否成功、处理了多少论文。

### GET /api/workflow/{run_id}

- Method: `GET`
- URL: `/api/workflow/{run_id}`
- 请求体示例：无
- 返回字段说明：
  - `success`: 查询是否成功
  - `data`: `WorkflowRunDetail`，除摘要字段外还包含完整 `result`
- 主流程作用：
  - 根据 run_id 查看某一次 workflow 的完整结果。
- 对外说明：
  - 这是 workflow 的详情接口，支持从历史记录进一步展开完整执行结果，便于后续做前端详情页或 Agent 复盘。

### POST /api/workflow/{run_id}/report

- Method: `POST`
- URL: `/api/workflow/{run_id}/report`
- 请求体示例：无
- 返回字段说明：
  - `success`: 报告是否生成成功
  - `run_id`: 对应 workflow run ID
  - `report_path`: Markdown 报告归档路径
  - `report_markdown`: 报告正文
  - `error`: 失败原因
- 主流程作用：
  - 根据已保存的 workflow run 结果生成可归档 Markdown 研究报告。
  - 报告保存到 `data/archives/workflow_reports/`。
  - 报告会展示 RAG 索引结果，包括是否启用、每篇论文 chunk 数量、warnings 和 errors。
- 对外说明：
  - 这是 workflow 的最终产物接口，把一次研究闭环从“执行结果”整理成“可阅读、可归档、可复盘”的研究报告。
  - 当前报告由模板生成，不调用 LLM；dry_run 报告会明确标注只用于演示，不代表真实检索或真实生成。

### GET /api/workflow/{run_id}/report

- Method: `GET`
- URL: `/api/workflow/{run_id}/report`
- 请求体示例：无
- 返回字段说明：
  - `success`: 是否读取成功
  - `run_id`: 对应 workflow run ID
  - `report_path`: Markdown 报告归档路径
  - `report_markdown`: 报告正文
  - `error`: 失败原因
- 主流程作用：
  - 读取已经生成的 workflow report。
- 对外说明：
  - 这个接口让报告不只是生成一次就丢失，而是可以通过 run_id 重新查看，适合前端展示或本地演示。

## 9. Feishu 飞书接口

### POST /api/feishu/webhook

- Method: `POST`
- URL: `/api/feishu/webhook`
- 请求体示例：

```json
{
  "type": "url_verification",
  "challenge": "local-challenge",
  "token": "demo-token"
}
```

- 返回字段说明：
  - URL verification 时返回 `challenge`
  - 文本消息事件时返回处理状态、Agent 响应和发送结果
  - 不支持事件时返回友好说明
- 主流程作用：
  - 当前已有飞书自建应用 webhook 入口，可把飞书文本消息转给 Agent。
- 对外说明：
  - 飞书模块已存在，但当前不作为主线继续接入；它支持文本消息和 challenge，占位了 token/signature 校验，暂不支持加密事件、卡片消息和异步长任务。
