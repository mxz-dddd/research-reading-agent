from __future__ import annotations

from typing import Any

import requests
import streamlit as st


DEFAULT_API_BASE_URL = "http://127.0.0.1:8000"
BACKEND_HELP = "后端未运行，请先启动 FastAPI 后端：\nuvicorn app.main:app --reload"

PAGE_DASHBOARD = "仪表盘"
PAGE_AGENT_CHAT = "智能体对话"
PAGE_RUN_WORKFLOW = "运行研究流程"
PAGE_WORKFLOW_HISTORY = "研究流程历史"
PAGE_WORKFLOW_REPORT = "研究报告"
PAGE_RAG_QA = "论文查询与复盘"
PAGE_RAG_EVALUATION = "检索质量评估"


st.set_page_config(page_title="科研阅读智能体工作台", layout="wide")


def normalize_base_url(url: str) -> str:
    return url.strip().rstrip("/")


def init_session_state() -> None:
    defaults = {
        "api_base_url": DEFAULT_API_BASE_URL,
        "latest_run_id": "",
        "latest_trace_id": "",
        "latest_report_path": "",
        "latest_agent_response": None,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def backend_health() -> bool:
    base_url = normalize_base_url(st.session_state.get("api_base_url", DEFAULT_API_BASE_URL))
    try:
        response = requests.get(f"{base_url}/health", timeout=5)
    except requests.RequestException:
        return False
    return response.status_code == 200


def api_request(method: str, path: str, *, json: dict[str, Any] | None = None) -> tuple[dict[str, Any] | None, str | None]:
    base_url = normalize_base_url(st.session_state.get("api_base_url", DEFAULT_API_BASE_URL))
    url = f"{base_url}{path}"
    try:
        response = requests.request(method, url, json=json, timeout=30)
    except requests.RequestException:
        return None, BACKEND_HELP

    try:
        payload = response.json()
    except ValueError:
        payload = {"raw_response": response.text}

    if response.status_code >= 400:
        return payload, f"请求失败，HTTP 状态码：{response.status_code}。请检查后端是否启动。"
    return payload, None


def render_error(error: str | None) -> None:
    if error:
        st.error(error)


def render_json_section(title: str, value: Any) -> None:
    with st.expander(title, expanded=False):
        st.json(value)


def render_steps(steps: list[dict[str, Any]]) -> None:
    if not steps:
        st.info("当前没有可展示的步骤。")
        return
    rows = [
        {
            "步骤": step.get("step"),
            "是否成功": step.get("success"),
            "摘要": step.get("summary"),
            "错误": step.get("error"),
        }
        for step in steps
    ]
    st.dataframe(rows, use_container_width=True)


def save_workflow_run_id(payload: dict[str, Any]) -> None:
    run_id = payload.get("run_id")
    if not run_id and isinstance(payload.get("data"), dict):
        run_id = payload["data"].get("run_id")
    if run_id:
        st.session_state["latest_run_id"] = run_id


def save_trace_id(payload: dict[str, Any]) -> None:
    trace_id = payload.get("trace_id")
    if trace_id:
        st.session_state["latest_trace_id"] = trace_id


def render_workflow_result(payload: dict[str, Any]) -> None:
    save_workflow_run_id(payload)
    if payload.get("success"):
        st.success("研究流程执行完成。")
    else:
        st.error(payload.get("error") or "研究流程执行失败。")

    col1, col2, col3 = st.columns(3)
    col1.metric("run_id（流程 ID）", payload.get("run_id") or "-")
    col2.metric("success（是否成功）", str(payload.get("success")))
    col3.metric("dry_run（演示模式）", str(payload.get("dry_run")))

    with st.expander("执行步骤", expanded=True):
        render_steps(payload.get("steps", []))

    warnings = payload.get("warnings") or []
    if warnings:
        st.warning("\n".join(str(item) for item in warnings))

    summary = {
        "searched_count": len(payload.get("searched_papers", [])),
        "accepted_count": len(payload.get("accepted_papers", [])),
        "ingested_count": len(payload.get("ingested_papers", [])),
        "rag_indexed_count": len(payload.get("rag_indexed_papers", [])),
        "knowledge_generated": bool(payload.get("knowledge")),
        "innovation_generated": bool(payload.get("innovation")),
    }
    st.markdown("### 流程摘要")
    st.json(summary)
    render_json_section("原始响应 JSON", payload)


def run_workflow_request(body: dict[str, Any]) -> None:
    payload, error = api_request("POST", "/api/workflow/run", json=body)
    render_error(error)
    if payload:
        render_workflow_result(payload)


def metric_value(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def dashboard_page() -> None:
    st.header("仪表盘")
    st.info("这里汇总展示当前研究流程、查询记录和评估指标。第一次使用时，可以先到“运行研究流程”页面点击“运行演示流程”。")
    connected = backend_health()
    if connected:
        st.success("后端已连接")
    else:
        st.error("后端未运行，请先启动 FastAPI 后端")
        st.code("uvicorn app.main:app --reload")
        st.info("启动后端后，刷新本页面即可查看研究状态。")
        return

    st.subheader("最近一次研究流程")
    latest_payload, latest_error = api_request("GET", "/api/workflow/latest")
    render_error(latest_error)
    if latest_payload and latest_payload.get("success") and latest_payload.get("data"):
        latest = latest_payload["data"]
        save_workflow_run_id(latest)
        cols = st.columns(5)
        cols[0].metric("run_id", latest.get("run_id") or "-")
        cols[1].metric("研究主题", latest.get("topic") or "-")
        cols[2].metric("success", str(latest.get("success")))
        cols[3].metric("dry_run", str(latest.get("dry_run")))
        cols[4].metric("创建时间", latest.get("created_at") or "-")
        render_json_section("最近一次研究流程原始 JSON", latest_payload)
    else:
        st.info("暂无 workflow 记录。")
        if latest_payload:
            render_json_section("最近一次研究流程原始 JSON", latest_payload)

    st.subheader("最近 5 条研究流程历史")
    history_payload, history_error = api_request("GET", "/api/workflow/history?limit=5")
    render_error(history_error)
    if history_payload:
        items = history_payload.get("items", [])
        if items:
            st.dataframe(
                [
                    {
                        "run_id": item.get("run_id"),
                        "研究主题": item.get("topic"),
                        "success": item.get("success"),
                        "dry_run": item.get("dry_run"),
                        "搜索数": item.get("searched_count"),
                        "接收数": item.get("accepted_count"),
                        "精读数": item.get("ingested_count"),
                        "创建时间": item.get("created_at"),
                    }
                    for item in items
                ],
                use_container_width=True,
            )
        else:
            st.info("暂无 workflow 历史记录。")
        render_json_section("研究流程历史原始 JSON", history_payload)

    st.subheader("最近查询 trace")
    traces_payload, traces_error = api_request("GET", "/api/rag/traces/latest?limit=5")
    render_error(traces_error)
    if traces_payload:
        traces = traces_payload.get("items", [])
        if traces:
            save_trace_id(traces[0])
            st.dataframe(
                [
                    {
                        "trace_id": item.get("trace_id"),
                        "问题": item.get("query"),
                        "模式": item.get("mode"),
                        "命中数": item.get("hit_count"),
                        "无证据": item.get("no_evidence"),
                        "创建时间": item.get("created_at"),
                    }
                    for item in traces
                ],
                use_container_width=True,
            )
        else:
            st.info("暂无查询 trace。")
        render_json_section("查询 trace 原始 JSON", traces_payload)

    st.subheader("检索评估摘要")
    eval_payload, eval_error = api_request("GET", "/api/rag/evaluation/summary")
    render_error(eval_error)
    if eval_payload:
        summary = eval_payload.get("summary", {})
        cols = st.columns(4)
        cols[0].metric("total_traces", metric_value(summary.get("total_traces")))
        cols[1].metric("total_feedback", metric_value(summary.get("total_feedback")))
        cols[2].metric("relevance_rate", metric_value(summary.get("relevance_rate")))
        cols[3].metric("no_evidence_accuracy", metric_value(summary.get("no_evidence_accuracy")))
        render_json_section("检索评估原始 JSON", eval_payload)

    st.subheader("证据级评估指标")
    evidence_payload, evidence_error = api_request("GET", "/api/rag/evaluation/evidence-summary")
    render_error(evidence_error)
    if evidence_payload:
        if evidence_payload.get("message"):
            st.info(evidence_payload["message"])
        summary = evidence_payload.get("summary", {})
        cols = st.columns(5)
        cols[0].metric("Recall@1", metric_value(summary.get("recall_at_1")))
        cols[1].metric("Recall@3", metric_value(summary.get("recall_at_3")))
        cols[2].metric("Recall@5", metric_value(summary.get("recall_at_5")))
        cols[3].metric("MRR", metric_value(summary.get("mrr")))
        cols[4].metric("nDCG@5", metric_value(summary.get("ndcg_at_5")))
        render_json_section("证据级评估原始 JSON", evidence_payload)

    st.subheader("快捷操作")
    st.info("请在左侧页面菜单中进入“运行研究流程”、“论文查询与复盘”或“研究报告”。")


def agent_chat_page() -> None:
    st.header("智能体对话")
    st.info("这里可以用自然语言调用后端 Agent。适合测试“你能做什么”、“帮我运行研究流程”、“查看最近一次研究结果”等指令。")
    message = st.text_area("自然语言请求", value="你能做什么", height=120)
    user_id = st.text_input("user_id（用户 ID）", value="streamlit-user")
    session_id = st.text_input("session_id（会话 ID）", value="streamlit-session")

    if st.button("发送给智能体", type="primary"):
        payload, error = api_request(
            "POST",
            "/api/agent/query",
            json={"user_id": user_id, "session_id": session_id, "message": message},
        )
        render_error(error)
        if payload:
            st.session_state["latest_agent_response"] = payload
            if payload.get("chosen_tool") == "run_research_workflow" and isinstance(payload.get("data"), dict):
                save_workflow_run_id(payload["data"])

            if payload.get("success"):
                st.success("智能体请求完成。")
            else:
                st.error(payload.get("error") or "智能体请求失败。")

            st.subheader("最终回答")
            st.markdown(payload.get("final_answer") or payload.get("answer") or "")
            col1, col2 = st.columns(2)
            col1.metric("chosen_tool（选择的工具）", payload.get("chosen_tool") or "-")
            col2.metric("routing_method（路由方式）", payload.get("routing_method") or "-")
            render_json_section("工具调用记录", payload.get("tool_calls", []))
            render_json_section("返回数据", payload.get("data"))
            render_json_section("原始响应 JSON", payload)


def run_workflow_page() -> None:
    st.header("运行研究流程")
    st.info("这里用于从研究方向出发，执行论文搜索、接收、ingest、本地检索索引、知识树和创新点生成。没有网络或 API Key 时建议使用 dry_run 演示模式。")
    topic = st.text_input("研究主题", value="large language model agent")
    col1, col2 = st.columns(2)
    max_results = col1.number_input("max_results（搜索论文数量）", min_value=1, max_value=20, value=3, step=1)
    accept_top_k = col2.number_input("accept_top_k（自动接收前 K 篇）", min_value=1, max_value=20, value=2, step=1)
    dry_run = st.checkbox("dry_run（演示模式）", value=True, help="使用模拟数据演示完整流程，适合无网络演示。")
    index_rag = st.checkbox("index_rag（自动建立 RAG 索引）", value=True, help="流程 ingest 后，为论文建立本地 RAG v1 索引。")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("运行研究流程", type="primary"):
            run_workflow_request(
                {
                    "topic": topic,
                    "max_results": int(max_results),
                    "accept_top_k": int(accept_top_k),
                    "dry_run": dry_run,
                    "index_rag": index_rag,
                }
            )

    with col2:
        if st.button("运行演示流程"):
            run_workflow_request(
                {
                    "topic": "large language model agent",
                    "max_results": 3,
                    "accept_top_k": 2,
                    "dry_run": True,
                    "index_rag": True,
                }
            )

    if st.session_state.get("latest_run_id"):
        st.caption(f"最近保存的 run_id：{st.session_state['latest_run_id']}")


def workflow_history_page() -> None:
    st.header("研究流程历史")
    st.info("这里可以查看最近运行过的 workflow 记录。每条记录都有 run_id，可用于生成报告或复盘结果。")
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("最近一次研究流程")
        if st.button("加载最近一次"):
            payload, error = api_request("GET", "/api/workflow/latest")
            render_error(error)
            if payload:
                data = payload.get("data") or {}
                save_workflow_run_id(data)
                if payload.get("success"):
                    st.success("已加载最近一次研究流程。")
                else:
                    st.info(payload.get("message") or "暂无 workflow 记录。")
                st.json(payload)

    with col2:
        st.subheader("最近历史列表")
        limit = st.number_input("limit（返回条数）", min_value=1, max_value=100, value=5, step=1)
        if st.button("加载历史列表"):
            payload, error = api_request("GET", f"/api/workflow/history?limit={int(limit)}")
            render_error(error)
            if payload:
                items = payload.get("items", [])
                if items:
                    first_run = items[0].get("run_id")
                    if first_run:
                        st.session_state["latest_run_id"] = first_run
                    st.dataframe(items, use_container_width=True)
                else:
                    st.info("暂无 workflow 历史记录。")
                render_json_section("原始响应 JSON", payload)


def workflow_report_page() -> None:
    st.header("研究报告")
    st.info("这里可以根据 workflow 的 run_id 生成或读取 Markdown 研究报告。如果刚运行过流程，系统会自动填入最近的 run_id。")
    run_id = st.text_input(
        "run_id（研究流程 ID）",
        value=st.session_state.get("latest_run_id", ""),
        placeholder="请输入或粘贴 workflow run_id",
    )
    if st.session_state.get("latest_report_path"):
        st.caption(f"最近报告路径：{st.session_state['latest_report_path']}")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("生成报告", type="primary", disabled=not run_id.strip()):
            payload, error = api_request("POST", f"/api/workflow/{run_id.strip()}/report")
            render_error(error)
            if payload:
                if payload.get("report_path"):
                    st.session_state["latest_report_path"] = payload["report_path"]
                if payload.get("success"):
                    st.success("报告已生成。")
                else:
                    st.error(payload.get("error") or "报告生成失败。")
                st.caption(payload.get("report_path") or "")
                st.markdown(payload.get("report_markdown") or "")
                render_json_section("原始响应 JSON", payload)

    with col2:
        if st.button("读取报告", disabled=not run_id.strip()):
            payload, error = api_request("GET", f"/api/workflow/{run_id.strip()}/report")
            render_error(error)
            if payload:
                if payload.get("report_path"):
                    st.session_state["latest_report_path"] = payload["report_path"]
                if payload.get("success"):
                    st.success("报告已读取。")
                else:
                    st.error(payload.get("error") or "没有找到报告。")
                st.caption(payload.get("report_path") or "")
                st.markdown(payload.get("report_markdown") or "")
                render_json_section("原始响应 JSON", payload)


def rag_qa_page() -> None:
    st.header("论文查询与复盘")
    st.info("这里用于基于已索引论文片段进行查询和复盘。底层 RAG v1 使用关键词/token overlap 检索，如果没有证据，系统不会编造答案。")
    query = st.text_area("问题", value="retrieval augmented generation", height=100)
    paper_id = st.text_input("paper_id（可选论文 ID）", value="")
    top_k = st.number_input("top_k（返回证据数量）", min_value=1, max_value=20, value=5, step=1)

    if st.button("提交查询", type="primary"):
        request_body: dict[str, Any] = {"query": query, "top_k": int(top_k)}
        if paper_id.strip():
            request_body["paper_id"] = paper_id.strip()
        payload, error = api_request("POST", "/api/rag/answer", json=request_body)
        render_error(error)
        if payload:
            save_trace_id(payload)
            if payload.get("success"):
                st.success("查询完成。")
            else:
                st.error(payload.get("error") or "查询失败。")

            st.subheader("回答")
            st.markdown(payload.get("answer") or "")
            if payload.get("warning"):
                st.warning(payload["warning"])
            col1, col2 = st.columns(2)
            col1.metric("trace_id（证据追踪 ID）", payload.get("trace_id") or "-")
            col2.metric("no_evidence（是否无证据）", str(payload.get("no_evidence")))

            evidence = payload.get("evidence_chunks", [])
            st.markdown("### 证据片段")
            if evidence:
                for index, chunk in enumerate(evidence, start=1):
                    with st.expander(f"证据 {index}: {chunk.get('chunk_id')}", expanded=index == 1):
                        st.write(chunk.get("content_preview") or chunk.get("content") or "")
                        st.json(
                            {
                                "paper_id": chunk.get("paper_id"),
                                "chunk_index": chunk.get("chunk_index"),
                                "score": chunk.get("score"),
                                "matched_terms": chunk.get("matched_terms"),
                                "score_reason": chunk.get("score_reason"),
                                "source_path": chunk.get("source_path"),
                            }
                        )
            else:
                st.info("暂无证据片段。")
            render_json_section("原始响应 JSON", payload)


def rag_evaluation_page() -> None:
    st.header("检索质量评估")
    st.info("这里用于查看查询 trace、人工反馈和 evidence-level 评估指标。适合分析检索质量和后续优化方向。")
    if st.session_state.get("latest_trace_id"):
        st.caption(f"最近保存的 trace_id：{st.session_state['latest_trace_id']}")

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Trace 级评估摘要")
        if st.button("加载检索评估摘要"):
            payload, error = api_request("GET", "/api/rag/evaluation/summary")
            render_error(error)
            if payload:
                summary = payload.get("summary", {})
                st.success("Trace 级评估摘要已加载。")
                st.metric("relevance_rate（相关率）", metric_value(summary.get("relevance_rate")))
                st.metric("no_evidence_accuracy（无证据判断准确率）", metric_value(summary.get("no_evidence_accuracy")))
                st.json(summary)

    with col2:
        st.subheader("证据级评估摘要")
        if st.button("加载证据级评估摘要"):
            payload, error = api_request("GET", "/api/rag/evaluation/evidence-summary")
            render_error(error)
            if payload:
                if payload.get("message"):
                    st.info(payload["message"])
                summary = payload.get("summary", {})
                metric_cols = st.columns(3)
                st.success("证据级评估摘要已加载。")
                metric_cols[0].metric("Recall@K", metric_value(summary.get("recall_at_k", summary.get("recall_at_5"))))
                metric_cols[1].metric("MRR", metric_value(summary.get("mrr")))
                metric_cols[2].metric("nDCG@5", metric_value(summary.get("ndcg_at_5")))
                st.json(summary)

    st.subheader("单条 Trace 的证据级详情")
    trace_id = st.text_input(
        "trace_id（RAG 证据追踪 ID）",
        value=st.session_state.get("latest_trace_id", ""),
        placeholder="使用最近保存的 trace_id，或手动输入",
    )
    if st.button("加载 Trace 证据级详情", disabled=not trace_id.strip()):
        payload, error = api_request("GET", f"/api/rag/evaluation/traces/{trace_id.strip()}/evidence")
        render_error(error)
        if payload:
            if payload.get("success"):
                st.success("Trace 证据级详情已加载。")
            else:
                st.error(payload.get("error") or payload.get("message") or "Trace 证据级详情加载失败。")
            evidence = payload.get("evidence", [])
            if evidence:
                st.dataframe(evidence, use_container_width=True)
            else:
                st.info("当前没有可展示的证据级详情。")
            render_json_section("原始响应 JSON", payload)


def main() -> None:
    init_session_state()
    st.title("科研阅读智能体工作台")
    st.caption("基于 FastAPI 后端的科研阅读与整理产品原型。")

    with st.sidebar:
        st.text_input("API Base URL（后端地址）", value=DEFAULT_API_BASE_URL, key="api_base_url")

        st.markdown("### 后端状态")
        if backend_health():
            st.success("后端已连接")
        else:
            st.error("后端未运行")
            st.code("uvicorn app.main:app --reload")

        st.markdown("### 已保存 ID")
        st.caption(f"latest_run_id：{st.session_state.get('latest_run_id') or '-'}")
        st.caption(f"latest_trace_id：{st.session_state.get('latest_trace_id') or '-'}")

        page = st.radio(
            "页面",
            [
                PAGE_DASHBOARD,
                PAGE_AGENT_CHAT,
                PAGE_RUN_WORKFLOW,
                PAGE_WORKFLOW_HISTORY,
                PAGE_WORKFLOW_REPORT,
                PAGE_RAG_QA,
                PAGE_RAG_EVALUATION,
            ],
        )
        st.info("无网络演示建议使用 dry_run。")
        with st.expander("新手使用顺序", expanded=False):
            st.markdown(
                """
                1. 到“运行研究流程”点击“运行演示流程”
                2. 回到“仪表盘”查看 latest workflow
                3. 到“研究报告”生成报告
                4. 到“论文查询与复盘”测试查询
                5. 到“检索质量评估”查看 trace 和指标
                """
            )

    if page == PAGE_DASHBOARD:
        dashboard_page()
    elif page == PAGE_AGENT_CHAT:
        agent_chat_page()
    elif page == PAGE_RUN_WORKFLOW:
        run_workflow_page()
    elif page == PAGE_WORKFLOW_HISTORY:
        workflow_history_page()
    elif page == PAGE_WORKFLOW_REPORT:
        workflow_report_page()
    elif page == PAGE_RAG_QA:
        rag_qa_page()
    elif page == PAGE_RAG_EVALUATION:
        rag_evaluation_page()


if __name__ == "__main__":
    main()
