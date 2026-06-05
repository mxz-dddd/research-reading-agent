# Research-Agent

面向科研论文分析与创新点挖掘的多工具大语言模型 Agent 系统。

这是一个 FastAPI + SQLite 后端项目，目标是把“搜索论文、筛选论文、接收论文、深入阅读、知识树生成、创新点挖掘、完整研究闭环”串成一个可通过自然语言调用的 Research Agent。项目当前不是企业级平台，而是一个适合展示 Agent 工程能力、工具编排能力和科研场景理解能力的 MVP。

## 项目背景

科研论文阅读不是简单问答任务。普通聊天机器人通常只能根据用户输入生成一段回答，但科研工作流需要：

- 主动搜索候选论文，并记录搜索结果。
- 对论文做初筛，判断是否值得继续阅读。
- 将确认有价值的论文接收入库。
- 对论文做深入阅读和本地归档。
- 基于多篇论文生成知识树、学习路径和创新点。
- 用自然语言统一调用不同工具，而不是让用户记住每个接口。

因此，这个项目把 LLM 能力和后端工具链结合起来，构造成一个“单轮单工具”的科研 Agent：它先识别用户意图，再解析参数，再调用工具，最后组织统一回答。

## 项目目标

系统主要解决以下问题：

- 论文搜索：根据研究主题搜索 arXiv 论文，并在网络不可用时保留 mock fallback。
- 论文筛选：基于规则或 OpenAI-compatible LLM 生成中文初筛摘要、相关度和阅读建议。
- 论文入库：支持接收论文、保存状态、查看已接收论文。
- 深入阅读：支持从 arXiv URL 推断 PDF、下载 PDF、提取文本并生成 Markdown 总结；失败时降级为 abstract-only。
- 知识树生成：基于已接收论文生成知识树、学习路径和 Mermaid 图。
- 创新点挖掘：基于已接收论文和最近知识树生成候选研究 gap。
- Research Workflow 闭环：从论文搜索到创新点生成的一键复合工具。
- 自然语言统一调用：通过 `/api/agent/query` 统一调度论文、知识树、创新点等工具。

## 技术栈

- FastAPI：后端接口和 ASGI 应用入口。
- SQLite：本地数据存储，包括论文、搜索历史、知识树、创新点、RAG chunks、workflow 和会话状态。
- Pydantic：请求和响应 schema。
- arXiv API：论文搜索来源，当前通过 `urllib` 请求 Atom XML。
- OpenAI-compatible LLM：如果配置 `OPENAI_API_KEY`，部分模块会尝试调用 Responses API；未配置时使用 fallback 逻辑。
- pytest：路由、接口响应结构和参数解析测试。
- pypdf：PDF 文本提取。
- Feishu：已有 webhook 接口雏形，作为后续扩展能力，不是当前主线。

## 系统架构

FastAPI 入口在 `app.main:app`。核心 Agent 入口是：

```text
POST /api/agent/query
```

整体链路：

```mermaid
flowchart TD
  U[用户自然语言输入] --> A[/api/agent/query]
  A --> O[AgentOrchestrator]
  O --> R{路由方式}
  R -->|无 OPENAI_API_KEY 或 LLM 路由失败| F[fallback_router]
  R -->|配置 OPENAI_API_KEY| L[LLM router]
  F --> AR[argument_resolver]
  L --> AR
  AR --> T[ToolRegistry]
  T --> P[Papers tools/services]
  T --> K[Knowledge service]
  T --> I[Innovation service]
  T --> G[RAG service]
  T --> W[Research Workflow service]
  P --> B[answer_builder]
  K --> B
  I --> B
  G --> B
  W --> B
  B --> FA[final_answer + data]
```

核心 Agent 模块：

- `app/agent/orchestrator.py`：统一编排入口，负责串联路由、参数解析、工具调用和响应结构。
- `app/agent/fallback_router.py`：无 LLM 或 LLM 路由失败时的关键词/正则路由。
- `app/agent/argument_resolver.py`：补齐工具参数，支持 `paper_id`、“第 N 篇”和 workflow `dry_run` 解析。
- `app/agent/tool_registry.py`：工具注册表，把工具名映射到具体 service 调用。
- `app/agent/answer_builder.py`：把工具返回结果整理成 `final_answer`。
- `app/agent/prompts.py`：LLM router 的系统提示词。
- `app/services/rag_service.py`：轻量 RAG v1，负责论文文本切分、SQLite chunk 索引、关键词检索和模板化保守回答。
- `app/services/research_workflow_service.py`：复用 papers、knowledge、innovation service，执行完整研究闭环。

## 核心功能

### Papers

对应路由：`/api/papers`

已实现：

- `POST /api/papers/search`：搜索论文并入库。
- `GET /api/papers/search-history`：查看搜索历史。
- `POST /api/papers/accept`：接收论文。
- `POST /api/papers/ingest`：深入阅读并归档。
- `GET /api/papers/accepted`：查看已接收论文。
- `GET /api/papers/{paper_id}`：查看论文详情。

主要代码：

- `app/services/paper_service.py`
- `app/tools/search_papers.py`
- `app/services/archive_service.py`
- `app/repositories/paper_repo.py`

### RAG v1

对应路由：`/api/rag`

已实现：

- `POST /api/rag/index`：为已 ingest 论文建立本地 chunk 索引。
- `POST /api/rag/search`：基于关键词 / token overlap 检索 evidence chunks。
- `POST /api/rag/answer`：基于 evidence chunks 生成模板化保守回答。
- `GET /api/rag/traces/latest`：查看最近 RAG evidence trace。
- `GET /api/rag/traces/{trace_id}`：查看单次 RAG trace 详情。
- `GET /api/rag/traces/by-paper/{paper_id}`：查看某篇论文相关 RAG trace。
- `POST /api/rag/traces/{trace_id}/feedback`：为 RAG trace 添加人工相关性标注。
- `GET /api/rag/evaluation/summary`：查看 RAG trace feedback 评估摘要。
- `GET /api/rag/evaluation/traces/{trace_id}`：查看单条 trace 的评估详情。
- `POST /api/rag/traces/{trace_id}/evidence-feedback`：为单条 evidence chunk 添加相关性标注。
- `GET /api/rag/evaluation/evidence-summary`：查看 evidence-level Recall@K / MRR / nDCG@5 摘要。
- `GET /api/rag/evaluation/traces/{trace_id}/evidence`：查看某条 trace 的 evidence-level 标注详情。

当前 RAG v1 不调用 OpenAI embedding，不接 Qdrant，不新增重型依赖。它优先读取论文的 `local_text_path`，缺失时兼容 `local_summary_path`、`deep_summary`、`abstract_summary` 或 `abstract`。

RAG search/answer 会返回 evidence chunks、`matched_terms` 和 `score_reason`，用于说明 chunk 为什么被召回。没有 evidence 时，RAG answer 不会编造答案，会明确提示“当前已索引论文中没有检索到足够证据”。质量边界详见 `docs/rag_v1_quality_boundary.md`。

每次 RAG search / answer 默认会保存 Evidence Trace，记录 query、mode、paper_id、top_k、evidence、answer、no_evidence 和轻量 metadata，方便后续人工复盘与评估。空 query 不保存 trace。

RAG trace feedback 支持人工标注 `relevant`、`partially_relevant`、`irrelevant`、`no_evidence_correct`、`no_evidence_incorrect`。评估摘要会统计 `relevance_rate`、`no_evidence_accuracy` 和 label distribution；当前是轻量人工标注闭环，不是自动 RAGAS。

Evidence-level feedback 支持对单个 evidence chunk 标注 `relevance_score=0/1/2`，并基于每个 trace/chunk 的最新标注计算轻量排序指标：Recall@1、Recall@3、Recall@5、MRR 和 nDCG@5。

轻量评估脚本：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m app.evaluation.rag_eval
```

该脚本使用临时 SQLite 和内置测试 chunks，输出 `total_cases`、`hit_count`、`hit_at_k` 和每条 case 的 top results；它不是 RAGAS，也不是 embedding 语义检索评估。

主要代码：

- `app/api/routes_rag.py`
- `app/services/rag_service.py`
- `app/services/rag_evaluation_service.py`
- `app/repositories/rag_repo.py`
- `app/repositories/rag_trace_repo.py`
- `app/repositories/rag_feedback_repo.py`
- `app/repositories/rag_evidence_feedback_repo.py`

### Knowledge

对应路由：`/api/knowledge`

已实现：

- `POST /api/knowledge/generate`：基于已接收论文生成知识树和学习路径。
- `GET /api/knowledge/latest`：查看最近一次知识树。
- `GET /api/knowledge/history`：查看历史知识树。

生成结果会保存到 `data/archives/knowledge/`。当前至少需要 2 篇已接收论文。

### Innovation

对应路由：`/api/innovation`

已实现：

- `POST /api/innovation/generate`：基于已接收论文生成创新点分析。
- `GET /api/innovation/latest`：查看最近一次创新点分析。
- `GET /api/innovation/history`：查看历史创新点分析。

生成结果会保存到 `data/archives/innovation/`。当前至少需要 2 篇已接收论文；少于 4 篇时会提示覆盖不足。

### Agent

对应路由：`POST /api/agent/query`

Agent 当前支持：

- 搜索论文。
- 接收论文。
- 深入阅读论文。
- 查看已接收论文。
- 查看论文详情。
- 生成知识树。
- 生成创新点。
- 一键运行完整研究闭环。
- 帮助说明。

推荐请求：

```json
{
  "user_id": "demo",
  "session_id": "s1",
  "message": "搜索 large language model medical imaging 论文，给我 2 篇"
}
```

响应结构：

```text
success
intent
chosen_tool
tool_calls
final_answer
data
error
routing_method
answer
used_tool
```

其中 `answer` 和 `used_tool` 是兼容旧字段，当前分别等同于 `final_answer` 和 `chosen_tool`。

### Research Workflow

对应路由：`POST /api/workflow/run`

已实现一个复合科研闭环：

```text
输入研究方向
-> 搜索论文
-> 自动接收 top-k 篇
-> 对已接收论文执行 ingest
-> 为 ingested papers 自动建立 RAG v1 索引
-> 生成知识树
-> 生成创新点
-> 保存 workflow run
-> 生成 Markdown 研究报告
-> 返回 workflow summary
```

请求示例：

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

如果只是本地演示流程结构，可以设置 `dry_run=true`。该模式会返回明确标注为 `dry_run/mock` 的模拟数据，不访问 arXiv、不下载 PDF、不调用 OpenAI，也不写 papers / knowledge / innovation 业务表；但仍会保存一条带 `dry_run=true` 的 workflow run 记录，方便演示历史查询。结果只用于本地演示和调试，不代表真实论文检索或真实生成结果。

workflow 执行结果会保存到 `workflow_runs` 表，并返回 `run_id`。当前也支持查询：

- `GET /api/workflow/latest`：最近一次 workflow run。
- `GET /api/workflow/history?limit=10`：workflow 历史摘要列表。
- `GET /api/workflow/{run_id}`：单次 workflow 完整结果。
- `POST /api/workflow/{run_id}/report`：生成并保存 Markdown 研究报告。
- `GET /api/workflow/{run_id}/report`：读取已生成的 Markdown 研究报告。

报告会保存到 `data/archives/workflow_reports/`。当前报告是模板生成，不调用 LLM；如果基于 `dry_run` 结果生成，报告中会明确标注“仅用于演示流程结构”。

`index_rag=true` 时，workflow 会在 ingest 后对成功深入阅读的论文自动建立 RAG v1 索引，并在 response 与 report 中记录 `rag_indexed_papers`、chunk 数量、warnings 和 errors。`dry_run=true` 时不会写真实 `rag_chunks`，只返回模拟 RAG indexing 结果。

这个能力也注册进了 Agent 工具系统，工具名为 `run_research_workflow`。例如用户可以说：

```text
围绕 large language model agent 完整跑一遍研究流程
以 dry run 方式围绕 large language model agent 完整跑一遍研究流程
不联网演示一下研究闭环
查看最近一次研究闭环结果
列出最近的研究流程历史
把最近一次研究闭环生成报告
查看最近一次 workflow 的报告
```

当前 Agent 仍是单轮单工具 Agent；`run_research_workflow` 是一个复合工具，不等同于复杂多步自主 planner。

### Tests

当前已有轻量测试：

- `tests/test_agent_fallback_routing.py`：fallback 路由测试。
- `tests/test_agent_query_endpoint.py`：`/api/agent/query` 完整接口响应结构测试。
- `tests/test_agent_argument_resolver.py`：参数解析测试，覆盖 `paper_id` 和“第 N 篇”。
- `tests/test_research_workflow_service.py`：Research Workflow service 测试，覆盖 dry_run 不调用真实服务。
- `tests/test_workflow_endpoint.py`：Workflow endpoint 响应结构测试，覆盖 dry_run 请求。
- `tests/test_agent_workflow_tool.py`：Agent workflow 工具路由测试，覆盖“不联网/模拟/dry run”触发 dry_run。
- `tests/test_workflow_repo.py`：Workflow run 持久化 repository 测试，使用临时 SQLite。
- `tests/test_workflow_history_endpoint.py`：Workflow latest/history/detail 查询接口测试。
- `tests/test_agent_workflow_history_tool.py`：Agent workflow 历史查询工具路由测试。
- `tests/test_workflow_report_service.py`：Workflow Report 模板生成和临时目录归档测试。
- `tests/test_workflow_report_endpoint.py`：Workflow Report API 测试。
- `tests/test_agent_workflow_report_tool.py`：Agent workflow report 工具路由测试。
- `tests/test_research_workflow_closed_loop.py`：dry_run 闭环端到端验收测试，覆盖 workflow 执行、历史查询、详情、报告和 Agent 查询。
- `tests/test_rag_repo.py`：RAG chunk repository 测试，使用临时 SQLite。
- `tests/test_rag_service.py`：RAG 索引、检索和模板回答测试。
- `tests/test_rag_endpoint.py`：RAG API 测试。
- `tests/test_agent_rag_tool.py`：Agent RAG 工具路由测试。
- `tests/test_rag_eval.py`：轻量 RAG 检索评估脚本测试，使用临时 SQLite。
- `tests/test_rag_trace_repo.py`：RAG Evidence Trace repository 测试，使用临时 SQLite。
- `tests/test_rag_trace_endpoint.py`：RAG Evidence Trace API 测试。
- `tests/test_agent_rag_trace_tool.py`：Agent RAG trace 查询工具路由测试。
- `tests/test_rag_feedback_repo.py`：RAG trace feedback repository 测试，使用临时 SQLite。
- `tests/test_rag_evaluation_service.py`：RAG evaluation service 测试。
- `tests/test_rag_evaluation_endpoint.py`：RAG evaluation API 测试。
- `tests/test_agent_rag_evaluation_tool.py`：Agent RAG evaluation 工具路由测试。
- `tests/test_rag_evidence_feedback_repo.py`：RAG evidence-level feedback repository 测试。
- `tests/test_rag_evidence_evaluation_service.py`：RAG evidence-level evaluation service 测试。
- `tests/test_rag_evidence_evaluation_endpoint.py`：RAG evidence-level evaluation API 测试。
- `tests/test_agent_rag_evidence_evaluation_tool.py`：Agent evidence-level evaluation 工具路由测试。
- `tests/test_health.py`：健康检查测试。

当前全量轻量测试结果：

```text
132 passed
```

### Feishu Extension

对应路由：`POST /api/feishu/webhook`

当前状态：

- 已有飞书 webhook 接口雏形。
- 支持 URL challenge 和文本消息转 Agent。
- 作为后续扩展能力保留。
- 当前不作为项目主线，不支持完整飞书 Bot 能力、加密事件、卡片消息和异步长任务。

## Agent 工作流

`/api/agent/query` 的核心流程：

1. 意图识别：
   - 如果配置了 `OPENAI_API_KEY`，优先尝试 LLM function calling 路由。
   - 如果未配置或失败，使用 `fallback_router.py` 的关键词/正则规则。

2. 参数解析：
   - `argument_resolver.py` 负责补齐工具参数。
   - 支持直接解析 `P12` 为 `paper_id=12`。
   - 支持“第 2 篇”通过 `session_state` 最近搜索结果解析为具体 `paper_id`。

3. 工具调用：
   - `ToolRegistry` 根据 `tool_name` 调用对应 service。
   - 工具包括论文搜索、接收、ingest、详情、知识树、创新点、完整研究闭环。

4. 结果整合：
   - `answer_builder.py` 把工具返回数据整理为面向用户的 `final_answer`。

5. 统一响应：
   - 返回 `success / intent / chosen_tool / tool_calls / final_answer / data / error / routing_method` 等字段。

当前 Agent 是单轮单工具 Agent：每次请求只选择一个工具执行。这是为了保证 MVP 可控、可测试、易解释。多步规划是后续规划。

## 本地启动

创建虚拟环境：

```bash
python -m venv .venv
```

安装依赖：

```bash
.venv/bin/pip install -r requirements.txt
```

启动 FastAPI 后端：

```bash
source .venv/bin/activate
python -m uvicorn app.main:app --reload
```

启动 Streamlit 前端：

```bash
source .venv/bin/activate
python -m streamlit run frontend/streamlit_app.py
```

健康检查：

```text
http://127.0.0.1:8000/health
```

FastAPI 文档：

```text
http://127.0.0.1:8000/docs
```

前端访问地址：

```text
FastAPI docs: http://127.0.0.1:8000/docs
Streamlit 前端: http://localhost:8501
```

Swagger `/docs` 是开发者 API 调试页面；Streamlit 是中文产品原型页面，更适合演示和普通用户操作。第一次使用建议在 Streamlit 中进入“运行研究流程”，点击“运行演示流程”。

## 最小调用示例

Agent 查询：

```bash
curl -X POST http://127.0.0.1:8000/api/agent/query \
  -H "Content-Type: application/json" \
  -d '{"user_id":"demo","session_id":"s1","message":"搜索 large language model medical imaging 论文，给我 2 篇"}'
```

论文搜索：

```bash
curl -X POST http://127.0.0.1:8000/api/papers/search \
  -H "Content-Type: application/json" \
  -d '{"topic":"large language model medical imaging","max_results":3}'
```

接收论文：

```bash
curl -X POST http://127.0.0.1:8000/api/papers/accept \
  -H "Content-Type: application/json" \
  -d '{"paper_id":1}'
```

深入阅读：

```bash
curl -X POST http://127.0.0.1:8000/api/papers/ingest \
  -H "Content-Type: application/json" \
  -d '{"paper_id":1}'
```

生成知识树：

```bash
curl -X POST http://127.0.0.1:8000/api/knowledge/generate \
  -H "Content-Type: application/json" \
  -d '{}'
```

生成创新点：

```bash
curl -X POST http://127.0.0.1:8000/api/innovation/generate \
  -H "Content-Type: application/json" \
  -d '{}'
```

运行完整研究闭环：

```bash
curl -X POST http://127.0.0.1:8000/api/workflow/run \
  -H "Content-Type: application/json" \
  -d '{"topic":"large language model agent","max_results":5,"accept_top_k":2}'
```

不联网演示完整研究闭环：

```bash
curl -X POST http://127.0.0.1:8000/api/workflow/run \
  -H "Content-Type: application/json" \
  -d '{"topic":"large language model agent","max_results":3,"accept_top_k":2,"dry_run":true}'
```

## 运行测试

运行全量轻量测试：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest -p no:cacheprovider tests
```

运行 Agent 相关测试：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest -p no:cacheprovider \
  tests/test_agent_argument_resolver.py \
  tests/test_agent_query_endpoint.py \
  tests/test_agent_fallback_routing.py
```

## 环境变量

可选 LLM 配置：

```bash
export OPENAI_API_KEY="你的 key"
export OPENAI_MODEL="gpt-5.4-mini"
```

未设置 `OPENAI_API_KEY` 时，系统会走规则版 fallback，不影响本地基础演示。

可选飞书配置仅用于后续扩展：

```bash
export FEISHU_APP_ID="cli_xxx"
export FEISHU_APP_SECRET="xxx"
export FEISHU_VERIFICATION_TOKEN="xxx"
export FEISHU_ENCRYPT_KEY="xxx"
export FEISHU_BOT_NAME="Research Agent"
export FEISHU_ENABLE_SIGNATURE_CHECK=false
```

## 已实现功能

- 论文搜索。
- 论文接收。
- 论文 ingest / 深入阅读 / 归档。
- 论文详情查看。
- 知识树生成。
- 创新点挖掘。
- 轻量 RAG v1：本地 chunk 索引、关键词检索和保守问答。
- Research Workflow 闭环服务和 `/api/workflow/run`。
- Research Workflow `dry_run` 演示模式。
- Workflow run 结果保存与历史查询。
- Workflow Report 生成与 Markdown 归档。
- Workflow 自动 RAG v1 indexing。
- Workflow dry_run 闭环端到端验收测试。
- Agent 复合工具 `run_research_workflow`。
- Agent 查询最近 workflow 结果和历史记录。
- Agent 生成或查看 workflow report。
- Agent 调用 RAG 索引、检索和问答。
- RAG Evidence Trace：保存 search / answer 的 query、evidence、answer 和 no_evidence 状态。
- RAG trace feedback：支持人工相关性标注和 evaluation summary。
- RAG evidence-level feedback：支持单条 evidence chunk 标注和 Recall@K / MRR / nDCG@5 轻量评估。
- Agent 查询最近 RAG trace、trace 详情和某篇论文的 RAG 查询记录。
- Agent 查询 RAG 检索质量统计和 trace 评估详情。
- Agent 查询 evidence-level RAG 评估摘要和 trace 证据级详情。
- RAG v1 quality boundary 文档和轻量检索评估脚本。
- Agent 统一入口 `/api/agent/query`。
- Agent 编排层模块化重构：
  - `answer_builder.py`
  - `fallback_router.py`
  - `argument_resolver.py`
- 核心接口验收文档。
- 路由、接口响应结构、参数解析、workflow service 和 workflow endpoint 测试。

## 后续规划

- Qdrant 向量数据库和 embedding 语义检索。
- BM25 + dense hybrid retrieval。
- LLM 证据融合生成、RAGAS 和更完整的离线评估报表。
- evidence-level 可视化、自动相关性判断、RAGAS 和更完整的评估报表。
- Memory 研究状态记忆：记录长期研究方向、已读论文、用户偏好和待办事项。
- Feishu Bot 完整接入：支持卡片消息、异步任务、加密事件和主动推送。
- LLM router 单元测试与模块化：先测试 `_extract_function_call()`，再拆 LLM router。
- Agent 多步规划：支持“搜索 -> 接收 -> ingest -> 生成知识树”的多工具链式执行。
- LLM 增强版报告润色：在模板报告基础上做结构化改写和摘要压缩。
- 更强 PDF 解析：按章节提取方法、实验、局限和启发。
- 人工反馈闭环：支持对论文、知识树和创新点进行评分、修订和版本管理。

## 更多文档

- 核心接口验收清单：[docs/core_api_checklist.md](docs/core_api_checklist.md)
- Agent 架构说明：[docs/agent_architecture.md](docs/agent_architecture.md)
- RAG v1 质量边界：[docs/rag_v1_quality_boundary.md](docs/rag_v1_quality_boundary.md)
- 项目冻结交付清单：[docs/project_freeze_checklist.md](docs/project_freeze_checklist.md)
- Streamlit 前端说明：[frontend/README.md](frontend/README.md)
- 本地 curl 演示脚本：[scripts/demo_curl_examples.sh](scripts/demo_curl_examples.sh)
