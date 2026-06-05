import re
from typing import Any


def route_with_fallback(message: str) -> dict[str, Any]:
    text = message.strip()
    lower = text.lower()

    if _has_any(lower, ["支持哪些", "能做什么", "help", "帮助", "下一步"]):
        return {"intent": "help", "tool_name": "help", "arguments": {}}

    if _is_generate_workflow_report_query(lower):
        return {
            "intent": "generate_workflow_report",
            "tool_name": "generate_workflow_report",
            "arguments": {"run_id": extract_workflow_run_id(text)},
        }

    if _is_get_workflow_report_query(lower):
        return {
            "intent": "get_workflow_report",
            "tool_name": "get_workflow_report",
            "arguments": {"run_id": extract_workflow_run_id(text)},
        }

    paper_ref = parse_paper_reference(text)

    if _is_rag_index_query(lower):
        return {
            "intent": "index_paper_rag",
            "tool_name": "index_paper_rag",
            "arguments": paper_ref,
        }

    trace_id = extract_rag_trace_id(text)
    if _is_add_rag_evidence_feedback_query(lower) and trace_id:
        return {
            "intent": "add_rag_evidence_feedback",
            "tool_name": "add_rag_evidence_feedback",
            "arguments": {
                "trace_id": trace_id,
                "chunk_id": extract_rag_chunk_id(text),
                "rank": extract_evidence_rank(text),
                "relevance_score": extract_evidence_relevance_score(text),
                "notes": extract_rag_feedback_notes(text),
            },
        }

    if _is_rag_trace_evidence_evaluation_query(lower) and trace_id:
        return {
            "intent": "get_rag_trace_evidence_evaluation",
            "tool_name": "get_rag_trace_evidence_evaluation",
            "arguments": {"trace_id": trace_id},
        }

    if _is_rag_evidence_evaluation_summary_query(lower):
        return {
            "intent": "get_rag_evidence_evaluation_summary",
            "tool_name": "get_rag_evidence_evaluation_summary",
            "arguments": {"trace_id": trace_id},
        }

    if _is_add_rag_feedback_query(lower) and trace_id:
        return {
            "intent": "add_rag_trace_feedback",
            "tool_name": "add_rag_trace_feedback",
            "arguments": {
                "trace_id": trace_id,
                "relevance_label": extract_rag_relevance_label(text),
                "notes": extract_rag_feedback_notes(text),
            },
        }

    if _is_rag_evaluation_summary_query(lower):
        return {
            "intent": "get_rag_evaluation_summary",
            "tool_name": "get_rag_evaluation_summary",
            "arguments": {},
        }

    if _is_rag_trace_evaluation_detail_query(lower) and trace_id:
        return {
            "intent": "get_rag_trace_evaluation_detail",
            "tool_name": "get_rag_trace_evaluation_detail",
            "arguments": {"trace_id": trace_id},
        }

    if _is_rag_trace_detail_query(lower) and trace_id:
        return {
            "intent": "get_rag_trace_detail",
            "tool_name": "get_rag_trace_detail",
            "arguments": {"trace_id": trace_id},
        }

    if _is_rag_trace_by_paper_query(lower):
        return {
            "intent": "get_rag_traces_by_paper",
            "tool_name": "get_rag_traces_by_paper",
            "arguments": {**paper_ref, "limit": extract_history_limit(text)},
        }

    if _is_latest_rag_traces_query(lower):
        return {
            "intent": "get_latest_rag_traces",
            "tool_name": "get_latest_rag_traces",
            "arguments": {"limit": extract_history_limit(text)},
        }

    if _is_rag_answer_query(lower):
        return {
            "intent": "rag_answer",
            "tool_name": "rag_answer",
            "arguments": {
                **paper_ref,
                "query": extract_rag_query(text),
                "top_k": extract_top_k(text),
            },
        }

    if _is_rag_search_query(lower):
        return {
            "intent": "rag_search",
            "tool_name": "rag_search",
            "arguments": {
                **paper_ref,
                "query": extract_rag_query(text),
                "top_k": extract_top_k(text),
            },
        }

    if _is_workflow_history_query(lower):
        return {
            "intent": "list_workflow_history",
            "tool_name": "list_workflow_history",
            "arguments": {"limit": extract_history_limit(text)},
        }

    if _is_latest_workflow_query(lower):
        return {"intent": "get_latest_workflow", "tool_name": "get_latest_workflow", "arguments": {}}

    run_id = extract_workflow_run_id(text)
    if run_id:
        return {
            "intent": "get_workflow_detail",
            "tool_name": "get_workflow_detail",
            "arguments": {"run_id": run_id},
        }

    if _has_any(lower, ["完整研究流程", "研究闭环", "完整执行", "完整跑一遍", "一键完成", "从论文搜索到创新点"]):
        return {
            "intent": "run_research_workflow",
            "tool_name": "run_research_workflow",
            "arguments": {
                "topic": extract_workflow_topic(text),
                "max_results": extract_max_results(text),
                "accept_top_k": extract_accept_top_k(text),
                "dry_run": extract_dry_run(text),
                "index_rag": extract_workflow_index_rag(text),
            },
        }

    if _has_any(lower, ["知识树", "学习路径", "roadmap", "knowledge"]):
        return {
            "intent": "generate_knowledge",
            "tool_name": "generate_knowledge",
            "arguments": {"topic": extract_optional_topic(text)},
        }

    if _has_any(lower, ["创新点", "创新方向", "挖掘", "innovation"]):
        return {
            "intent": "generate_innovation",
            "tool_name": "generate_innovation",
            "arguments": {"topic": extract_optional_topic(text)},
        }

    if _has_any(lower, ["有哪些已接收", "列出已接收", "已接收论文列表", "列出 accepted", "accepted papers", "可用论文"]):
        return {"intent": "list_accepted_papers", "tool_name": "list_accepted_papers", "arguments": {}}

    if _has_any(lower, ["接收", "标记为可用", "确认可用", "accept"]):
        return {"intent": "accept_paper", "tool_name": "accept_paper", "arguments": paper_ref}

    if _has_any(lower, ["深入阅读", "ingest", "归档", "精读"]):
        return {"intent": "ingest_paper", "tool_name": "ingest_paper", "arguments": paper_ref}

    if _has_any(lower, ["详情", "详细信息", "detail"]):
        return {"intent": "get_paper_detail", "tool_name": "get_paper_detail", "arguments": paper_ref}

    if _has_any(lower, ["搜索", "查找", "找", "论文", "paper", "search"]):
        return {
            "intent": "search_papers",
            "tool_name": "search_papers",
            "arguments": {
                "topic": extract_search_topic(text),
                "max_results": extract_max_results(text),
            },
        }

    return {"intent": "help", "tool_name": "help", "arguments": {}}


def parse_paper_reference(text: str) -> dict[str, Any]:
    paper_id_match = re.search(r"(?:paper_id|P|p)\s*(?:为|=|是)?\s*(\d+)", text)
    if paper_id_match:
        return {"paper_id": int(paper_id_match.group(1))}

    ordinal_match = re.search(r"第\s*(\d+)\s*篇", text)
    if ordinal_match:
        return {"ordinal": int(ordinal_match.group(1))}

    number_match = re.search(r"\b(\d+)\b", text)
    if number_match:
        return {"paper_id": int(number_match.group(1))}
    return {}


def extract_max_results(text: str) -> int:
    match = re.search(r"(\d+)\s*篇", text)
    if match:
        return max(1, min(20, int(match.group(1))))
    return 5


def extract_accept_top_k(text: str) -> int:
    match = re.search(r"(?:接收|accept|top|前)\s*(\d+)\s*篇", text, flags=re.I)
    if match:
        return max(1, min(20, int(match.group(1))))
    return 2


def extract_search_topic(text: str) -> str:
    topic = re.sub(r"(帮我|请|搜索|查找|找|论文|paper|papers|search|给我|篇|的)", " ", text, flags=re.I)
    topic = re.sub(r"\d+", " ", topic)
    topic = re.sub(r"[，,。.!！?？]", " ", topic)
    topic = " ".join(topic.split())
    return topic or text


def extract_workflow_topic(text: str) -> str:
    topic = re.sub(
        r"(dry run|dry_run|mock|模拟|不联网|演示|围绕|请对|帮我|请|做一个|做一次|跑一遍|完整跑一遍|完整研究流程|研究流程|研究闭环|完整执行一遍|完整执行|一键完成|这个方向|论文搜索|搜索|接收|知识树|创新点|生成|从|到)",
        " ",
        text,
        flags=re.I,
    )
    topic = re.sub(r"(的|和|、|，|,|。|!|！|\?|？)", " ", topic)
    topic = re.sub(r"\d+\s*篇", " ", topic)
    topic = " ".join(topic.split())
    return topic or text


def extract_optional_topic(text: str) -> str | None:
    cleaned = re.sub(r"(根据|当前|已接收|论文|生成|知识树|学习路径|创新点|创新方向|总结|挖掘)", " ", text)
    cleaned = " ".join(cleaned.split())
    return cleaned or None


def extract_dry_run(text: str) -> bool:
    lower = text.lower()
    return _has_any(lower, ["dry run", "dry_run", "mock"]) or _has_any(text, ["模拟", "不联网", "演示"])


def extract_workflow_index_rag(text: str) -> bool:
    lower = text.lower()
    return _has_any(lower, ["rag", "检索索引", "检索增强"]) or _has_any(text, ["建立 RAG 索引", "建立检索索引"])


def extract_history_limit(text: str) -> int:
    match = re.search(r"(?:最近|前|limit)\s*(\d+)\s*(?:条|次|个|)", text, flags=re.I)
    if match:
        return max(1, min(100, int(match.group(1))))
    return 10


def extract_top_k(text: str) -> int:
    match = re.search(r"(?:top|前|返回|检索)\s*(\d+)\s*(?:条|个|段|chunks?)?", text, flags=re.I)
    if match:
        return max(1, min(20, int(match.group(1))))
    return 5


def extract_rag_query(text: str) -> str:
    query = re.sub(
        r"(把|为|给|请|帮我|基于|使用|用|在|已索引论文中|已索引|论文|这篇论文|RAG|rag|检索增强|建立|创建|生成|索引|检索|搜索|回答|内容|P\s*\d+|p\s*\d+|第\s*\d+\s*篇)",
        " ",
        text,
        flags=re.I,
    )
    query = re.sub(r"(的问题|是什么|是啥|一下|中|里|的)", " ", query)
    query = re.sub(r"[，,。.!！?？:：]", " ", query)
    query = " ".join(query.split())
    return query or text


def extract_workflow_run_id(text: str) -> str | None:
    direct_match = re.search(r"\b(run[_-][a-zA-Z0-9_-]{1,120})\b", text, flags=re.I)
    if direct_match:
        return direct_match.group(1)
    match = re.search(
        r"(?:workflow|run_id|研究闭环|run)\s*(?:详情|结果|记录|报告|run)?\s*[:：#=的 ]+\s*([a-zA-Z0-9_-]{3,128})",
        text,
        flags=re.I,
    )
    if match:
        return match.group(1)
    return None


def extract_rag_trace_id(text: str) -> str | None:
    direct_match = re.search(r"\b(trace[_-][a-zA-Z0-9_-]{3,120})\b", text, flags=re.I)
    if direct_match:
        return direct_match.group(1)
    match = re.search(
        r"(?:trace_id|rag trace|trace|证据详情)\s*[:：#=的 ]+\s*([a-zA-Z0-9_-]{6,128})",
        text,
        flags=re.I,
    )
    if match:
        return match.group(1)
    return None


def extract_rag_chunk_id(text: str) -> str | None:
    match = re.search(r"\b(chunk[_-][a-zA-Z0-9_-]{1,120})\b", text, flags=re.I)
    if match:
        return match.group(1)
    return None


def extract_evidence_rank(text: str) -> int | None:
    match = re.search(r"第\s*(\d+)\s*(?:条|个)?\s*(?:证据|evidence)", text, flags=re.I)
    if match:
        return int(match.group(1))
    match = re.search(r"(?:rank|第)\s*[:：#= ]?\s*(\d+)", text, flags=re.I)
    if match:
        return int(match.group(1))
    return None


def extract_rag_relevance_label(text: str) -> str:
    lower = text.lower()
    if _has_any(lower, ["partially_relevant", "partial", "部分相关"]) or _has_any(text, ["部分相关"]):
        return "partially_relevant"
    if _has_any(lower, ["irrelevant", "不相关", "无关"]) or _has_any(text, ["不相关", "无关"]):
        return "irrelevant"
    if _has_any(lower, ["no_evidence_incorrect"]) or _has_any(text, ["无证据错误", "拒答错误"]):
        return "no_evidence_incorrect"
    if _has_any(lower, ["no_evidence_correct"]) or _has_any(text, ["无证据正确", "拒答正确"]):
        return "no_evidence_correct"
    if _has_any(lower, ["relevant", "相关"]) or _has_any(text, ["相关"]):
        return "relevant"
    return "relevant"


def extract_evidence_relevance_score(text: str) -> int:
    lower = text.lower()
    if _has_any(lower, ["partially_relevant", "partial"]) or _has_any(text, ["部分相关"]):
        return 1
    if _has_any(lower, ["irrelevant"]) or _has_any(text, ["不相关", "无关"]):
        return 0
    if _has_any(lower, ["relevant"]) or _has_any(text, ["相关"]):
        return 2
    return 2


def extract_rag_feedback_notes(text: str) -> str | None:
    match = re.search(r"(?:反馈|备注|notes?)\s*[:：]\s*(.+)$", text, flags=re.I)
    if match:
        return match.group(1).strip()
    return None


def _is_latest_workflow_query(lower: str) -> bool:
    return _has_any(
        lower,
        [
            "查看最近一次研究闭环",
            "最近一次研究闭环结果",
            "上一次研究闭环",
            "上一次 workflow",
            "最近一次 workflow",
            "latest workflow",
            "last workflow",
        ],
    )


def _is_workflow_history_query(lower: str) -> bool:
    return ("workflow" in lower or "研究流程" in lower or "研究闭环" in lower) and _has_any(
        lower,
        ["历史", "历史记录", "history", "记录列表"],
    )


def _is_generate_workflow_report_query(lower: str) -> bool:
    return _has_any(lower, ["报告", "report"]) and _has_any(
        lower,
        ["生成", "产出", "写", "整理", "归档", "generate"],
    ) and _has_any(lower, ["workflow", "研究闭环", "研究流程", "run_"])


def _is_get_workflow_report_query(lower: str) -> bool:
    return _has_any(lower, ["报告", "report"]) and _has_any(
        lower,
        ["查看", "读取", "打开", "看", "get"],
    ) and _has_any(lower, ["workflow", "研究闭环", "研究流程", "run_"])


def _is_rag_index_query(lower: str) -> bool:
    return _has_any(lower, ["rag", "检索索引", "检索增强", "索引"]) and _has_any(
        lower,
        ["建立", "创建"],
    ) and _has_any(lower, ["论文", "p"])


def _is_add_rag_feedback_query(lower: str) -> bool:
    return _has_any(lower, ["标注", "反馈", "label", "feedback"]) and _has_any(
        lower,
        ["trace", "rag"],
    )


def _is_add_rag_evidence_feedback_query(lower: str) -> bool:
    return _has_any(lower, ["标注", "反馈", "label", "feedback"]) and _has_any(
        lower,
        ["证据", "evidence", "chunk"],
    ) and _has_any(lower, ["trace", "rag"])


def _is_rag_evidence_evaluation_summary_query(lower: str) -> bool:
    return _has_any(lower, ["evidence", "证据", "recall@k", "mrr", "ndcg"]) and _has_any(
        lower,
        ["评估", "统计", "summary", "质量", "recall@k", "mrr", "ndcg"],
    )


def _is_rag_trace_evidence_evaluation_query(lower: str) -> bool:
    return _has_any(lower, ["trace", "rag"]) and _has_any(lower, ["证据级", "evidence-level", "evidence"]) and _has_any(
        lower,
        ["评估详情", "详情", "evaluation"],
    )


def _is_rag_evaluation_summary_query(lower: str) -> bool:
    return _has_any(lower, ["rag", "检索质量", "评估", "evaluation"]) and _has_any(
        lower,
        ["摘要", "统计", "summary", "质量"],
    )


def _is_rag_trace_evaluation_detail_query(lower: str) -> bool:
    return _has_any(lower, ["trace", "rag"]) and _has_any(lower, ["评估详情", "evaluation", "标注详情"])


def _is_latest_rag_traces_query(lower: str) -> bool:
    return _has_any(lower, ["rag", "trace", "证据", "检索记录", "问答记录"]) and _has_any(
        lower,
        ["最近", "latest", "记录", "历史"],
    ) and not _has_any(lower, ["论文 p", "paper p"])


def _is_rag_trace_detail_query(lower: str) -> bool:
    return _has_any(lower, ["trace", "证据详情", "rag 证据", "rag trace"]) and _has_any(
        lower,
        ["查看", "详情", "detail", "证据"],
    )


def _is_rag_trace_by_paper_query(lower: str) -> bool:
    return _has_any(lower, ["rag", "检索记录", "查询记录", "问答记录", "trace"]) and _has_any(
        lower,
        ["论文", "paper", "p"],
    ) and _has_any(lower, ["记录", "历史", "查询", "trace"])


def _is_rag_search_query(lower: str) -> bool:
    return _has_any(lower, ["rag", "已索引", "检索增强"]) and _has_any(
        lower,
        ["搜索", "检索", "查找"],
    )


def _is_rag_answer_query(lower: str) -> bool:
    return _has_any(lower, ["rag", "论文内容", "已索引论文", "检索增强"]) and _has_any(
        lower,
        ["回答", "问答", "是什么", "方法", "贡献", "main contribution"],
    )


def _has_any(text: str, keywords: list[str]) -> bool:
    return any(keyword.lower() in text for keyword in keywords)
