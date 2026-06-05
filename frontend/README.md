# Research Agent Streamlit 前端原型

这个目录存放 Research-Agent 的最小 Streamlit Web UI。它用于把现有 FastAPI 后端能力包装成更容易演示和使用的中文产品原型，不是最终生产级前端。

## 1. 前端用途

Streamlit 前端会调用已有 FastAPI 接口，帮助用户完成：

- 查看仪表盘状态。
- 和科研智能体对话。
- 运行 Research Workflow。
- 查看研究流程历史。
- 生成和读取 workflow Markdown 报告。
- 使用本地 RAG v1 做论文内容问答。
- 查看 RAG trace 和评估摘要。

前端不会修改后端业务逻辑，也不会新增后端 API。

## 2. 启动 FastAPI 后端

在项目根目录运行：

```bash
.venv/bin/uvicorn app.main:app --reload
```

后端默认地址：

```text
http://127.0.0.1:8000
```

FastAPI 文档地址：

```text
http://127.0.0.1:8000/docs
```

## 3. 启动 Streamlit 前端

如果还没有安装依赖，先运行：

```bash
.venv/bin/pip install -r requirements.txt
```

启动前端：

```bash
.venv/bin/streamlit run frontend/streamlit_app.py
```

也可以使用系统里的 Streamlit：

```bash
streamlit run frontend/streamlit_app.py
```

## 4. 页面功能说明

每个页面顶部都有 1 到 2 行中文使用引导，说明这个页面适合做什么，以及第一次使用时应该从哪里开始。

- 仪表盘：只读状态页，展示后端连接状态、最近 workflow、workflow 历史、最近 RAG trace、RAG 评估摘要和证据级指标。
- 智能体对话：输入自然语言请求，调用 `POST /api/agent/query`。
- 运行研究流程：调用 `POST /api/workflow/run`，支持 topic、max_results、accept_top_k、dry_run 和 index_rag。
- 研究流程历史：调用 `GET /api/workflow/latest` 和 `GET /api/workflow/history?limit=5`。
- 研究报告：通过 `/api/workflow/{run_id}/report` 生成或读取 Markdown 报告。
- RAG 问答：调用 `POST /api/rag/answer`，展示回答、证据片段和 trace_id。
- RAG 评估：展示 trace 级评估、证据级评估和单条 trace 的证据详情。

侧边栏可以修改 `API Base URL`。默认值是：

```text
http://127.0.0.1:8000
```

## 5. 后端状态

侧边栏会显示后端连接状态：

- 后端已连接：`GET /health` 请求成功。
- 后端未运行：前端无法连接 FastAPI，请先启动后端：

```bash
uvicorn app.main:app --reload
```

## 6. 自动保存的 ID

前端会使用 `st.session_state` 保存一些关键 ID，减少复制粘贴：

- `latest_run_id`：workflow 执行成功后保存，也会在加载 latest/history 时更新。
- `latest_trace_id`：RAG 问答返回 trace_id 后保存。
- `latest_report_path`：生成或读取研究报告后保存。
- `latest_agent_response`：智能体对话返回后保存。

## 7. 一键 dry_run 演示流程

“运行研究流程”页面提供“运行演示流程”按钮，会发送：

```json
{
  "topic": "large language model agent",
  "max_results": 3,
  "accept_top_k": 2,
  "dry_run": true,
  "index_rag": true
}
```

这个按钮适合无网络演示和首次产品走查。

推荐新手先运行 dry_run 演示流程，再回到“仪表盘”查看 latest workflow 和历史记录。

注意：`dry_run` 仅用于演示完整流程结构，不代表真实论文检索结果或真实研究结论。

## 8. 重要边界

- `dry_run=true` 是演示模式。它使用模拟数据展示流程结构，不代表真实论文检索或真实研究结论。
- RAG v1 是基于本地 SQLite chunks 的 keyword/token overlap 检索，不是 embedding 检索，不是 Qdrant，也不是 hybrid retrieval。
- 飞书是后续扩展方向，不是当前前端主线。
- 当前 Streamlit 只是产品原型，不是最终生产级前端。
- 前端只调用已有 FastAPI API，不修改 schemas、数据库或业务逻辑。

## 9. 没有历史数据怎么办

- 如果仪表盘没有 workflow 记录，请进入“运行研究流程”页面，点击“运行演示流程”。
- 如果仪表盘没有 RAG trace，请进入“RAG 问答”页面，提交一次问题。
- 如果研究报告页面没有 run_id，请先运行一次 workflow，前端会自动保存最新的 `latest_run_id`。
