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
PAGE_RAG_V2_DEBUGGER = "RAG v2 调试台"
PAGE_RAG_V2_EVAL_DASHBOARD = "RAG v2 评估看板"
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


def safe_api_get(path: str, params: dict | None = None) -> tuple[bool, dict | None, str | None]:
    base_url = normalize_base_url(st.session_state.get("api_base_url", DEFAULT_API_BASE_URL))
    try:
        response = requests.get(f"{base_url}{path}", params=params, timeout=15)
        if not response.ok:
            return False, None, f"请求失败，HTTP {response.status_code}：{response.text[:500]}"
        data = response.json()
        if not isinstance(data, dict):
            return False, None, "接口返回的 JSON 不是对象。"
        return True, data, None
    except requests.exceptions.RequestException:
        return False, None, BACKEND_HELP
    except ValueError as exc:
        return False, None, f"接口返回不是有效 JSON：{exc}"
    except Exception as exc:
        return False, None, f"请求异常：{exc}"


def safe_api_post(path: str, payload: dict) -> tuple[bool, dict | None, str | None]:
    base_url = normalize_base_url(st.session_state.get("api_base_url", DEFAULT_API_BASE_URL))
    try:
        response = requests.post(f"{base_url}{path}", json=payload, timeout=15)
        if not response.ok:
            return False, None, f"请求失败，HTTP {response.status_code}：{response.text[:500]}"
        data = response.json()
        if not isinstance(data, dict):
            return False, None, "接口返回的 JSON 不是对象。"
        return True, data, None
    except requests.exceptions.RequestException:
        return False, None, BACKEND_HELP
    except ValueError as exc:
        return False, None, f"接口返回不是有效 JSON：{exc}"
    except Exception as exc:
        return False, None, f"请求异常：{exc}"


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


def _short_text(value: object, max_len: int = 300) -> str:
    text = " ".join(str(value or "").split())
    return text[:max_len]


def _normalize_evidence_source(value: Any) -> list[dict]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        for key in ("chunks", "evidence_chunks", "evidence", "results", "items"):
            nested = value.get(key)
            if isinstance(nested, list) and nested:
                return [item for item in nested if isinstance(item, dict)]
        return [value]
    return []


def _extract_evidence_items(response: dict) -> list[dict]:
    candidates = [
        response.get("chunks"),
        response.get("evidence_chunks"),
        response.get("evidence"),
        response.get("results"),
        response.get("items"),
    ]

    answer = response.get("answer")
    if isinstance(answer, dict):
        candidates.append(answer.get("evidence"))

    data = response.get("data")
    if isinstance(data, dict):
        candidates.append(data.get("chunks"))

    for candidate in candidates:
        items = _normalize_evidence_source(candidate)
        if items:
            return items
    return []


def _extract_evidence_rows(response: dict) -> list[dict]:
    rows = []
    for rank, item in enumerate(_extract_evidence_items(response), start=1):
        retrieval_scores = item.get("retrieval_scores") or {}
        preview = item.get("content_preview") or item.get("content") or item.get("text") or ""
        rows.append(
            {
                "rank": rank,
                "paper_id": item.get("paper_id"),
                "section_title": item.get("section_title"),
                "chunk_index": item.get("chunk_index"),
                "score": item.get("score"),
                "sparse_score": retrieval_scores.get("sparse", 0.0),
                "dense_score": retrieval_scores.get("dense", 0.0),
                "rrf_score": retrieval_scores.get("rrf", 0.0),
                "rerank_score": item.get("rerank_score"),
                "score_reason": item.get("score_reason") or "",
                "content_preview": _short_text(preview),
            }
        )
    return rows


def _render_evidence_debugger(response: dict) -> None:
    st.subheader("Evidence Debugger")
    items = _extract_evidence_items(response)
    rows = _extract_evidence_rows(response)
    if not rows:
        st.info("暂无 evidence。")
        return

    st.dataframe(rows, use_container_width=True)
    for index, item in enumerate(items, start=1):
        title = f"Evidence #{index} | paper_id={item.get('paper_id') or '-'} | section={item.get('section_title') or '-'}"
        with st.expander(title, expanded=index == 1):
            if item.get("contextual_header"):
                st.markdown("**contextual_header**")
                st.text(item.get("contextual_header"))
            st.markdown("**content**")
            st.write(item.get("content") or item.get("text") or item.get("content_preview") or "")
            st.markdown("**raw JSON**")
            st.json(item)


def _count_context_item_types(items: list) -> dict:
    counts: dict[str, int] = {}
    for item in items:
        if isinstance(item, dict):
            item_type = item.get("item_type")
        else:
            item_type = getattr(item, "item_type", None)
        if item_type:
            counts[item_type] = counts.get(item_type, 0) + 1
    return counts


def _render_single_context_pack(context_pack: dict, title: str = "Context Pack") -> None:
    st.markdown(f"### {title}")
    items = context_pack.get("items") or []
    item_count = context_pack.get("item_count")
    if item_count is None:
        item_count = len(items)
    summary = {
        "context_pack_id": context_pack.get("context_pack_id"),
        "estimated_tokens": context_pack.get("estimated_tokens", 0),
        "token_budget": context_pack.get("token_budget", 0),
        "item_count": item_count,
        "item_type_counts": _count_context_item_types(items),
    }
    st.json(summary)

    grouped: dict[str, list[dict]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        item_type = item.get("item_type") or "unknown"
        grouped.setdefault(item_type, []).append(item)

    for item_type, group_items in grouped.items():
        with st.expander(f"{item_type} ({len(group_items)})", expanded=False):
            for index, item in enumerate(group_items, start=1):
                st.markdown(f"**Item {index}**")
                st.write(item.get("content") or "")
                st.caption(f"score: {item.get('score')} | reason: {item.get('reason') or ''}")
                if item.get("metadata"):
                    st.json(item.get("metadata"))

    with st.expander("raw context_pack JSON", expanded=False):
        st.json(context_pack)


def _render_context_pack_viewer(response: dict) -> None:
    st.subheader("Context Pack Viewer")
    has_context_pack = False
    context_pack = response.get("context_pack")
    context_pack_id = response.get("context_pack_id")

    if isinstance(context_pack, dict):
        _render_single_context_pack(context_pack, "当前响应中的 Context Pack")
        has_context_pack = True
    elif context_pack_id:
        st.info(f"当前响应包含 context_pack_id：{context_pack_id}。可在下方手动加载。")

    manual_context_pack_id = st.text_input("context_pack_id", value=str(context_pack_id or ""), key="rag_v2_context_pack_id")
    if st.button("加载 Context Pack", disabled=not manual_context_pack_id.strip()):
        ok, data, error = safe_api_get(f"/api/rag/context-packs/{manual_context_pack_id.strip()}")
        if ok and data:
            st.session_state["rag_v2_loaded_context_pack"] = data
        else:
            st.error(error or "Context Pack 加载失败。")

    loaded_context_pack = st.session_state.get("rag_v2_loaded_context_pack")
    if isinstance(loaded_context_pack, dict):
        _render_single_context_pack(loaded_context_pack, "手动加载的 Context Pack")
        has_context_pack = True

    if not has_context_pack and not context_pack_id:
        st.info("暂无 Context Pack。")


def _render_pipeline_viewer(response: dict) -> None:
    st.subheader("Pipeline Viewer")
    pipeline = response.get("pipeline")
    if not isinstance(pipeline, dict) or not pipeline:
        st.info("暂无 pipeline 信息。")
        return

    summary = {
        "retrieval_mode": pipeline.get("retrieval_mode"),
        "sparse_candidate_count": pipeline.get("sparse_candidate_count", 0),
        "dense_candidate_count": pipeline.get("dense_candidate_count", 0),
        "fused_candidate_count": pipeline.get("fused_candidate_count", 0),
        "rerank_enabled": pipeline.get("rerank_enabled", False),
        "embedding_provider": pipeline.get("embedding_provider"),
        "rrf_k": pipeline.get("rrf_k"),
    }
    st.table(summary)
    with st.expander("raw pipeline JSON", expanded=False):
        st.json(pipeline)


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


def render_rag_v2_debugger() -> None:
    st.header("RAG v2 调试台")
    st.info("用于查看 contextual hybrid RAG 的 evidence、Context Pack 和 pipeline，便于调试检索结果。")

    st.subheader("查询控制区")
    col1, col2 = st.columns(2)
    user_id = col1.text_input("user_id", value="default", key="rag_v2_user_id")
    session_id = col2.text_input("session_id", value="default", key="rag_v2_session_id")

    col1, col2, col3 = st.columns(3)
    retrieval_mode = col1.selectbox("retrieval_mode", ["hybrid", "keyword"], key="rag_v2_retrieval_mode")
    paper_id = col2.text_input("paper_id（可选）", value="", key="rag_v2_paper_id")
    top_k = col3.number_input("top_k", min_value=1, max_value=20, value=5, step=1, key="rag_v2_top_k")
    query = st.text_area("query", value="这篇论文的方法和实验结论是什么？", height=120, key="rag_v2_query")

    payload: dict[str, Any] = {
        "query": query,
        "top_k": int(top_k),
        "user_id": user_id,
        "session_id": session_id,
        "retrieval_mode": retrieval_mode,
    }
    if paper_id.strip():
        payload["paper_id"] = paper_id.strip()

    col1, col2 = st.columns(2)
    with col1:
        if st.button("运行 RAG Search", type="primary"):
            ok, data, error = safe_api_post("/api/rag/search", payload)
            if ok and data:
                st.session_state["rag_v2_debug_response"] = data
                save_trace_id(data)
            else:
                st.error(error or "RAG Search 请求失败。")

    with col2:
        if st.button("运行 RAG Answer"):
            ok, data, error = safe_api_post("/api/rag/answer", payload)
            if ok and data:
                st.session_state["rag_v2_debug_response"] = data
                save_trace_id(data)
            else:
                st.error(error or "RAG Answer 请求失败。")

    response = st.session_state.get("rag_v2_debug_response")
    if not isinstance(response, dict):
        st.info("请先运行 RAG Search 或 RAG Answer。")
        return

    answer = response.get("answer") or response.get("final_answer")
    if answer:
        st.subheader("回答结果")
        st.markdown(str(answer))

    _render_evidence_debugger(response)
    _render_context_pack_viewer(response)
    _render_pipeline_viewer(response)
    render_json_section("查看原始响应 JSON", response)


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


def _render_eval_summary(summary: dict) -> None:
    st.subheader("Summary 指标")
    cols = st.columns(6)
    cols[0].metric("total", metric_value(summary.get("total")))
    cols[1].metric("error_count", metric_value(summary.get("error_count")))
    cols[2].metric("terms recall", metric_value(summary.get("avg_recall_expected_terms")))
    cols[3].metric("chunk recall", metric_value(summary.get("avg_recall_expected_chunk_ids")))
    cols[4].metric("paper recall", metric_value(summary.get("avg_recall_expected_paper_ids")))
    cols[5].metric("answer hit", metric_value(summary.get("answer_contains_any_rate")))


def _render_eval_mode_table(summary: dict) -> None:
    st.subheader("by_retrieval_mode")
    by_mode = summary.get("by_retrieval_mode") or {}
    if not isinstance(by_mode, dict) or not by_mode:
        st.info("暂无分组指标。")
        return
    rows = [{"retrieval_mode": mode, **metrics} for mode, metrics in by_mode.items() if isinstance(metrics, dict)]
    st.dataframe(rows, use_container_width=True)


def _render_eval_results_table(results: list[dict]) -> None:
    st.subheader("Results 明细")
    if not results:
        st.info("暂无 results 明细。")
        return

    modes = sorted({str(item.get("retrieval_mode")) for item in results if item.get("retrieval_mode")})
    selected_modes = st.multiselect("retrieval_mode 过滤", options=modes, default=modes)
    only_errors = st.checkbox("只看错误", value=False)
    keyword = st.text_input("query_id / query 关键词", value="")

    filtered = []
    for item in results:
        if selected_modes and item.get("retrieval_mode") not in selected_modes:
            continue
        if only_errors and not item.get("error"):
            continue
        if keyword.strip():
            haystack = f"{item.get('query_id') or ''} {item.get('query') or ''}".lower()
            if keyword.strip().lower() not in haystack:
                continue
        filtered.append(item)

    rows = [
        {
            "query_id": item.get("query_id"),
            "query": item.get("query"),
            "retrieval_mode": item.get("retrieval_mode"),
            "top_k": item.get("top_k"),
            "evidence_count": item.get("evidence_count"),
            "recall_expected_terms": item.get("recall_expected_terms"),
            "recall_expected_chunk_ids": item.get("recall_expected_chunk_ids"),
            "recall_expected_paper_ids": item.get("recall_expected_paper_ids"),
            "answer_contains_any": item.get("answer_contains_any"),
            "context_pack_id": item.get("context_pack_id"),
            "error": item.get("error"),
        }
        for item in filtered
    ]
    st.dataframe(rows, use_container_width=True)

    with st.expander("Result 详情", expanded=False):
        for index, item in enumerate(filtered, start=1):
            with st.expander(
                f"{index}. {item.get('query_id') or '-'} | {item.get('retrieval_mode') or '-'}",
                expanded=False,
            ):
                st.json(
                    {
                        "matched_expected_terms": item.get("matched_expected_terms"),
                        "missing_expected_terms": item.get("missing_expected_terms"),
                        "matched_expected_chunk_ids": item.get("matched_expected_chunk_ids"),
                        "missing_expected_chunk_ids": item.get("missing_expected_chunk_ids"),
                        "pipeline": item.get("pipeline"),
                        "error": item.get("error"),
                    }
                )


def render_rag_v2_eval_dashboard() -> None:
    st.header("RAG v2 评估看板")
    st.info("用于查看 golden queries 评估结果，比较不同 retrieval_mode 的检索效果，为后续替换 embedding、Qdrant 或 reranker 提供基线。")

    limit = st.number_input("limit（评估运行数量）", min_value=1, max_value=100, value=20, step=1)
    if st.button("刷新评估结果列表", type="primary"):
        ok, data, error = safe_api_get("/api/rag/eval-runs", params={"limit": int(limit)})
        if ok and data is not None:
            st.session_state["rag_v2_eval_runs"] = data
        else:
            st.error(error or "评估结果列表加载失败。")

    runs_payload = st.session_state.get("rag_v2_eval_runs")
    if not isinstance(runs_payload, dict):
        ok, data, error = safe_api_get("/api/rag/eval-runs", params={"limit": int(limit)})
        if ok and data is not None:
            runs_payload = data
            st.session_state["rag_v2_eval_runs"] = data
        else:
            st.error(error or "评估结果列表加载失败。")
            return

    runs = runs_payload.get("items") or []
    if not runs:
        st.info("暂无评估结果。请先运行 scripts/eval_rag_v2.py 生成 eval/rag_eval_runs/*.json。")
        st.code(
            ".venv/bin/python scripts/eval_rag_v2.py \\\n"
            "  --base-url http://127.0.0.1:8000 \\\n"
            "  --golden-file eval/golden_queries.example.jsonl \\\n"
            "  --retrieval-modes hybrid,keyword \\\n"
            "  --top-k 5 \\\n"
            "  --run-answer",
            language="bash",
        )
        return

    st.subheader("Eval Run 列表")
    st.dataframe(
        [
            {
                "run_id": item.get("run_id"),
                "created_at": item.get("created_at"),
                "retrieval_modes": ", ".join(item.get("retrieval_modes") or []),
                "top_k": item.get("top_k"),
                "run_answer": item.get("run_answer"),
                "total": item.get("total"),
                "error_count": item.get("error_count"),
                "avg_recall_expected_terms": item.get("avg_recall_expected_terms"),
                "avg_recall_expected_chunk_ids": item.get("avg_recall_expected_chunk_ids"),
                "avg_recall_expected_paper_ids": item.get("avg_recall_expected_paper_ids"),
                "answer_contains_any_rate": item.get("answer_contains_any_rate"),
            }
            for item in runs
        ],
        use_container_width=True,
    )

    run_ids = [item.get("run_id") for item in runs if item.get("run_id")]
    selected_run_id = st.selectbox("选择 run_id", options=run_ids)
    if st.button("加载评估详情", disabled=not selected_run_id):
        ok, data, error = safe_api_get(f"/api/rag/eval-runs/{selected_run_id}")
        if ok and data is not None:
            st.session_state["rag_v2_eval_run_detail"] = data
        else:
            st.error(error or "评估详情加载失败。")

    detail = st.session_state.get("rag_v2_eval_run_detail")
    if not isinstance(detail, dict):
        return

    _render_eval_summary(detail.get("summary") or {})
    _render_eval_mode_table(detail.get("summary") or {})
    _render_eval_results_table(detail.get("results") or [])
    render_json_section("查看原始评估 JSON", detail)


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
                PAGE_RAG_V2_DEBUGGER,
                PAGE_RAG_V2_EVAL_DASHBOARD,
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
    elif page == PAGE_RAG_V2_DEBUGGER:
        render_rag_v2_debugger()
    elif page == PAGE_RAG_V2_EVAL_DASHBOARD:
        render_rag_v2_eval_dashboard()
    elif page == PAGE_RAG_EVALUATION:
        rag_evaluation_page()


if __name__ == "__main__":
    main()
