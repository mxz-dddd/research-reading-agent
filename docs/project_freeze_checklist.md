# Project Freeze Checklist

本文档用于 Research-Agent 冻结前的交付检查，重点说明当前已经完成的能力、尚未实现的规划能力、核心接口入口、测试命令和提交风险。

## 1. 当前已实现能力清单

### Research Workflow 闭环

- 论文搜索：通过 `/api/papers/search` 或 Agent 工具搜索论文。
- 自动接收：workflow 可按 `accept_top_k` 接收 top-k 论文。
- ingest / 深入阅读：支持下载与文本提取失败时的降级处理。
- 自动建立 RAG v1 索引：workflow ingest 后可按 `index_rag` 为论文建立本地 chunk 索引。
- 知识树生成：基于已接收论文生成知识树与学习路径。
- 创新点挖掘：基于已接收论文和知识树生成候选研究 gap。
- workflow run 持久化：保存 `run_id`、topic、dry_run、summary、warnings、完整结果等信息。
- workflow 查询：支持 latest、history、detail。
- workflow report：支持生成和读取 Markdown 报告，归档到 `data/archives/workflow_reports/`。
- dry_run 演示模式：不访问 arXiv、OpenAI、PDF 下载或真实 RAG 索引，返回明确标注的模拟结果。

### Agent 编排

- `/api/agent/query` 统一自然语言入口。
- fallback 关键词 / 正则路由。
- OpenAI-compatible LLM router 入口保留。
- 参数解析模块 `argument_resolver.py`。
- 工具注册模块 `tool_registry.py`。
- final answer 构造模块 `answer_builder.py`。
- 支持论文、knowledge、innovation、workflow、RAG、RAG trace 和 RAG evaluation 相关工具。

### RAG v1

- SQLite `rag_chunks` 本地 chunk 存储。
- keyword / token overlap 检索。
- evidence chunks 展示。
- `matched_terms` 和 `score_reason` 说明召回原因。
- no evidence 防幻觉策略：无证据时不编造文档答案。
- 模板化 RAG answer，不调用 LLM。

### RAG Trace 与评估

- SQLite `rag_traces` 记录每次 RAG search / answer。
- trace-level feedback：人工标注 trace 是否相关。
- evidence-level feedback：人工标注单条 evidence chunk 相关性。
- 轻量评估指标：Recall@K、MRR、nDCG@5。
- Agent 可自然语言查询 RAG trace 和 RAG 评估摘要。

### 测试保护

- fallback 路由测试。
- `/api/agent/query` 响应结构测试。
- 参数解析测试。
- workflow service / endpoint / closed loop 测试。
- workflow history / report 测试。
- RAG repo / service / endpoint 测试。
- RAG trace / feedback / evaluation 测试。
- 当前全量轻量测试基线：`132 passed`。

## 2. 当前未实现但规划能力清单

以下能力是后续规划，不能在公开文档中说成已经完成：

- Qdrant 向量数据库。
- OpenAI embedding 或其他 embedding 语义检索。
- BM25 + dense hybrid retrieval。
- reranker。
- LLM evidence fusion。
- RAGAS 自动评估。
- 长期 Memory 研究状态记忆。
- 多步自主 Agent planner。
- LLM router 模块化拆分。
- Feishu Bot 完整接入。
- 前端可视化审核页。

## 3. 核心 API 清单入口

服务入口：

```bash
.venv/bin/uvicorn app.main:app --reload
```

OpenAPI 文档：

```text
http://127.0.0.1:8000/docs
```

核心路由：

- `GET /health`：健康检查。
- `/api/topics`：研究 topic 管理。
- `/api/papers/*`：论文搜索、接收、ingest、详情和已接收列表。
- `/api/knowledge/*`：知识树生成和查询。
- `/api/innovation/*`：创新点生成和查询。
- `POST /api/agent/query`：Agent 统一自然语言入口。
- `POST /api/workflow/run`：运行 Research Workflow。
- `GET /api/workflow/latest`：最近一次 workflow。
- `GET /api/workflow/history`：workflow 历史。
- `GET /api/workflow/{run_id}`：workflow 详情。
- `POST /api/workflow/{run_id}/report`：生成 workflow report。
- `GET /api/workflow/{run_id}/report`：读取 workflow report。
- `POST /api/rag/index`：建立 RAG v1 索引。
- `POST /api/rag/search`：RAG evidence 检索。
- `POST /api/rag/answer`：基于 evidence 的模板化回答。
- `/api/rag/traces/*`：RAG trace 查询和 feedback。
- `/api/rag/evaluation/*`：RAG 轻量评估摘要和详情。
- `/api/feishu/*`：已有接口雏形，当前不是主线。

更细接口说明见 `docs/core_api_checklist.md`。

## 4. 核心测试清单

推荐冻结前至少运行：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest -p no:cacheprovider tests
```

重点测试文件包括：

- `tests/test_agent_fallback_routing.py`
- `tests/test_agent_query_endpoint.py`
- `tests/test_agent_argument_resolver.py`
- `tests/test_research_workflow_service.py`
- `tests/test_workflow_endpoint.py`
- `tests/test_research_workflow_closed_loop.py`
- `tests/test_workflow_report_endpoint.py`
- `tests/test_rag_service.py`
- `tests/test_rag_endpoint.py`
- `tests/test_rag_trace_repo.py`
- `tests/test_rag_trace_endpoint.py`
- `tests/test_rag_evaluation_service.py`
- `tests/test_rag_evidence_evaluation_service.py`
- `tests/test_agent_rag_evaluation_tool.py`

## 5. 如何运行全量轻量测试

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest -p no:cacheprovider tests
```

该测试集应避免真实 OpenAI、arXiv、PDF 下载和正式 data 数据库写入。冻结前基线为 `132 passed`，如测试数量变化，以实际 pytest 输出为准。

## 6. 如何启动服务

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload
```

启动后访问：

```text
http://127.0.0.1:8000/docs
```

常用演示请求：

```json
{
  "topic": "large language model agent",
  "max_results": 3,
  "accept_top_k": 2,
  "dry_run": true,
  "index_rag": true
}
```

对应接口：

```text
POST /api/workflow/run
```

## 7. 本地演示建议顺序

1. 用 30 秒说明项目：这是面向科研论文分析与创新点挖掘的多工具 Research Agent。
2. 先展示 `/api/agent/query`：说明自然语言如何映射到工具调用。
3. 展示 Research Workflow：从搜索、接收、ingest、RAG 索引、知识树到创新点的一键闭环。
4. 展示 `dry_run=true`：说明无网络、无 Key 时也能稳定验收流程结构。
5. 展示 workflow history / detail / report：说明结果可以持久化和复盘。
6. 展示 RAG v1：说明 evidence chunks、matched terms、score reason 和 no evidence 防幻觉。
7. 展示 RAG trace 和 feedback：说明如何记录检索过程并做人类标注评估。
8. 展示测试：说明当前有端到端闭环测试和模块级测试保护。
9. 最后主动说明边界：RAG v1 不是 embedding 检索，后续会升级 Qdrant、hybrid retrieval、reranker 和多步 Agent。

## 8. 风险点

- RAG v1 不是 embedding 语义检索：当前是关键词 / token overlap，适合 evidence 定位，不适合复杂语义召回。
- dry_run 是模拟流程：适合演示和测试，不代表真实论文检索、真实生成或真实 RAG 索引结果。
- 飞书不是当前主线：已有接口雏形，但没有完成 Bot 级联调。
- LLM router 尚未模块化：当前 fallback、参数解析和 answer builder 已拆分，LLM router 仍保留在现有编排链路中。
- workflow report 是模板化报告：不调用 LLM，不代表高质量自动综述。
- RAG evaluation 依赖人工 feedback：Recall@K、MRR、nDCG@5 是基于已标注 evidence 的轻量指标，不是自动 RAGAS。

## 9. 交付前检查

- 不提交 `.env`。
- 不提交 `.venv/`。
- 不提交正式 SQLite 数据库，例如 `data/*.db`。
- 不提交真实下载 PDF，例如 `data/papers/pdfs/*`。
- 不提交真实提取文本和正式归档产物，除非明确用于样例且已确认无敏感内容。
- 不提交 `__pycache__/` 或 `.pytest_cache/`。
- 确认 `.gitignore` 覆盖本地数据库、PDF、归档报告和缓存目录。
- 确认 `PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest -p no:cacheprovider tests` 通过。
- 确认 README、Agent 架构文档、RAG 质量边界文档中已实现能力和后续规划没有混写。
