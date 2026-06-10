from __future__ import annotations

from typing import Any


def build_final_answer(tool_name: str, data: Any) -> str:
    if tool_name == "search_papers":
        if not data:
            return "这次没有找到候选论文。可以换成英文关键词，或放宽主题后再搜索。"
        lines = [f"已找到 {len(data)} 篇候选论文："]
        for index, paper in enumerate(data[:5], start=1):
            lines.append(f"{index}. P{paper.get('id')} {paper.get('title')}")
        lines.append("你可以说“接收第 2 篇”或“对第 2 篇做深入阅读”。")
        return "\n".join(lines)
    if tool_name == "accept_paper":
        return f"已接收论文 P{data.get('id')}：{data.get('title')}"
    if tool_name == "ingest_paper":
        return (
            f"已完成深入阅读归档：P{data.get('id')}。\n"
            f"阅读模式：{data.get('ingest_status')}。\n"
            f"总结路径：{data.get('local_summary_path')}"
        )
    if tool_name == "list_accepted_papers":
        if not data:
            return "当前还没有已接收论文。"
        lines = [f"当前有 {len(data)} 篇已接收论文："]
        for paper in data[:10]:
            lines.append(f"- P{paper.get('id')} {paper.get('title')}")
        return "\n".join(lines)
    if tool_name == "get_paper_detail":
        return (
            f"P{data.get('id')}：{data.get('title')}\n"
            f"状态：{data.get('status')} / ingest_status：{data.get('ingest_status')}\n"
            f"阅读建议：{data.get('worth_reading')}\n"
            f"归档：{data.get('local_summary_path')}"
        )
    if tool_name == "generate_knowledge":
        return (
            f"知识树已生成，来源论文数：{data.get('source_paper_count')}。\n"
            f"生成方式：{data.get('generation_method')}。\n"
            f"归档路径：{data.get('local_markdown_path')}"
        )
    if tool_name == "generate_innovation":
        return (
            f"创新点分析已生成，来源论文数：{data.get('source_paper_count')}。\n"
            f"生成方式：{data.get('generation_method')}。\n"
            f"归档路径：{data.get('local_markdown_path')}"
        )
    if tool_name == "run_research_workflow":
        steps = data.get("steps", [])
        warnings = data.get("warnings") or []
        searched_count = len(data.get("searched_papers") or [])
        accepted_count = len(data.get("accepted_papers") or [])
        ingested_count = len(data.get("ingested_papers") or [])
        rag_indexed = data.get("rag_indexed_papers") or []
        rag_indexed_count = sum(1 for item in rag_indexed if item.get("success"))
        rag_chunk_count = sum(int(item.get("chunk_count") or 0) for item in rag_indexed)
        lines = [
            f"研究闭环 dry_run 演示已完成：{data.get('topic')}"
            if data.get("dry_run")
            else f"研究闭环已完成：{data.get('topic')}",
            f"搜索论文：{searched_count} 篇。",
            f"自动接收：{accepted_count} 篇。",
            f"深入阅读：{ingested_count} 篇。",
            f"RAG 索引：{rag_indexed_count} 篇，chunk 总数：{rag_chunk_count}。",
        ]
        if data.get("knowledge"):
            lines.append("知识树：已生成。")
        if data.get("innovation"):
            lines.append("创新点：已生成。")
        if warnings:
            lines.append(f"提醒：{warnings[0]}")
        lines.append(f"执行步骤数：{len(steps)}。")
        return "\n".join(lines)
    if tool_name == "get_latest_workflow":
        if not data.get("success") or not data.get("data"):
            return data.get("message") or "还没有 workflow run 记录。"
        run = data["data"]
        return _format_workflow_run("最近一次研究闭环结果", run)
    if tool_name == "list_workflow_history":
        items = data.get("items") or []
        if not items:
            return "还没有 workflow run 历史记录。"
        lines = [f"最近 {len(items)} 条 workflow 历史记录："]
        for item in items[:10]:
            mode = "dry_run" if item.get("dry_run") else "real"
            status = "成功" if item.get("success") else "失败"
            lines.append(
                f"- {item.get('run_id')} | {item.get('topic')} | {status} | {mode} | "
                f"搜索 {item.get('searched_count')} / 接收 {item.get('accepted_count')} / 深读 {item.get('ingested_count')}"
            )
        return "\n".join(lines)
    if tool_name == "get_workflow_detail":
        run = data.get("data")
        if not run:
            return "没有找到对应的 workflow run。"
        return _format_workflow_run("workflow 详情", run)
    if tool_name == "generate_workflow_report":
        if not data.get("success"):
            return f"研究报告生成失败：{data.get('error') or '未知错误'}"
        return (
            f"研究报告已生成：{data.get('run_id')}\n"
            f"归档路径：{data.get('report_path')}\n"
            "你可以继续查看报告内容，或基于这份报告整理项目说明 / 研究复盘。"
        )
    if tool_name == "get_workflow_report":
        if not data.get("success"):
            return f"研究报告读取失败：{data.get('error') or '未知错误'}"
        markdown = data.get("report_markdown") or ""
        preview = markdown.strip().splitlines()[0] if markdown.strip() else "报告内容为空"
        return (
            f"已读取研究报告：{data.get('run_id')}\n"
            f"归档路径：{data.get('report_path')}\n"
            f"内容预览：{preview}"
        )
    if tool_name == "index_paper_rag":
        if not data.get("success"):
            return f"RAG 索引建立失败：{data.get('error') or '未知错误'}"
        lines = [
            f"已为论文 P{data.get('paper_id')} 建立 RAG v1 索引。",
            f"chunk 数量：{data.get('chunk_count')}。",
        ]
        warnings = data.get("warnings") or []
        if warnings:
            lines.append(f"提醒：{warnings[0]}")
        return "\n".join(lines)
    if tool_name == "rag_search":
        if not data.get("success"):
            return data.get("message") or data.get("error") or "RAG 检索失败。"
        chunks = data.get("evidence_chunks") or []
        if not chunks:
            return data.get("message") or "当前已索引论文中没有找到足够依据。"
        lines = [f"检索到 {len(chunks)} 个 evidence chunks："]
        for chunk in chunks[:5]:
            matched_terms = ", ".join(chunk.get("matched_terms") or [])
            reason = chunk.get("score_reason") or f"score={chunk.get('score')}"
            lines.append(
                f"- P{chunk.get('paper_id')} / {chunk.get('chunk_id')} "
                f"({reason})"
                + (f"；命中词：{matched_terms}" if matched_terms else "")
                + f"：{chunk.get('content_preview')}"
            )
        return "\n".join(lines)
    if tool_name == "rag_answer":
        if not data.get("success"):
            return data.get("answer") or data.get("error") or "RAG 回答失败。"
        if data.get("no_evidence"):
            return data.get("answer") or "当前已索引论文中没有检索到足够证据，无法基于文档回答该问题。"
        return data.get("answer") or "当前已索引论文中没有找到足够依据。"
    if tool_name == "get_latest_rag_traces":
        return _format_rag_trace_list("最近的 RAG evidence traces", data.get("items") or [])
    if tool_name == "get_rag_traces_by_paper":
        return _format_rag_trace_list("这篇论文的 RAG evidence traces", data.get("items") or [])
    if tool_name == "get_rag_trace_detail":
        if not data.get("success") or not data.get("data"):
            return data.get("message") or "没有找到对应的 RAG trace。"
        trace = data["data"]
        lines = [
            f"RAG trace 详情：{trace.get('trace_id')}",
            f"模式：{trace.get('mode')}，query：{trace.get('query')}",
            f"paper_id：{trace.get('paper_id') or '未限定'}，top_k：{trace.get('top_k')}，命中：{trace.get('hit_count')}。",
            f"no_evidence：{trace.get('no_evidence')}",
        ]
        answer = trace.get("answer")
        if answer:
            lines.append(f"回答预览：{_preview_line(answer)}")
        evidence = trace.get("evidence") or []
        if evidence:
            first = evidence[0]
            lines.append(
                f"首条 evidence：P{first.get('paper_id')} / {first.get('chunk_id')} "
                f"({first.get('score_reason') or first.get('score')})"
            )
        return "\n".join(lines)
    if tool_name == "add_rag_trace_feedback":
        if not data.get("success") or not data.get("data"):
            return data.get("message") or data.get("error") or "RAG trace feedback 保存失败。"
        feedback = data["data"]
        return (
            f"已保存 RAG trace feedback：{feedback.get('feedback_id')}\n"
            f"trace_id：{feedback.get('trace_id')}\n"
            f"相关性标注：{feedback.get('relevance_label')}"
        )
    if tool_name == "get_rag_evaluation_summary":
        summary = data.get("summary") or {}
        return (
            "RAG 检索质量评估摘要：\n"
            f"traces：{summary.get('total_traces', 0)}，answer traces：{summary.get('answered_traces', 0)}，"
            f"no_evidence traces：{summary.get('no_evidence_traces', 0)}。\n"
            f"feedback：{summary.get('total_feedback', 0)}，relevance_rate：{summary.get('relevance_rate', 0)}，"
            f"no_evidence_accuracy：{summary.get('no_evidence_accuracy')}。\n"
            f"label_distribution：{summary.get('label_distribution', {})}"
        )
    if tool_name == "get_rag_trace_evaluation_detail":
        if not data.get("success") or not data.get("trace"):
            return data.get("message") or "没有找到对应的 RAG trace。"
        trace = data["trace"]
        feedback = data.get("latest_feedback")
        lines = [
            f"RAG trace 评估详情：{trace.get('trace_id')}",
            f"query：{trace.get('query')}",
            f"mode：{trace.get('mode')}，hit_count：{trace.get('hit_count')}，no_evidence：{trace.get('no_evidence')}",
        ]
        if feedback:
            lines.append(
                f"最新 feedback：{feedback.get('relevance_label')}，feedback_id：{feedback.get('feedback_id')}"
            )
        else:
            lines.append(data.get("message") or "该 trace 暂无人工 feedback。")
        return "\n".join(lines)
    if tool_name == "add_rag_evidence_feedback":
        if not data.get("success") or not data.get("data"):
            return data.get("message") or data.get("error") or "RAG evidence feedback 保存失败。"
        feedback = data["data"]
        return (
            f"已保存 evidence-level feedback：{feedback.get('evidence_feedback_id')}\n"
            f"trace_id：{feedback.get('trace_id')}，chunk_id：{feedback.get('chunk_id')}，rank：{feedback.get('rank')}\n"
            f"相关性：{feedback.get('relevance_label')}（score={feedback.get('relevance_score')}）"
        )
    if tool_name == "get_rag_evidence_evaluation_summary":
        summary = data.get("summary") or {}
        return (
            "RAG evidence-level 评估摘要：\n"
            f"已标注 traces：{summary.get('total_traces_with_evidence_feedback', 0)}，"
            f"evidence feedback：{summary.get('total_evidence_feedback', 0)}。\n"
            f"Recall@1：{summary.get('recall_at_1', 0)}，Recall@3：{summary.get('recall_at_3', 0)}，"
            f"Recall@5：{summary.get('recall_at_5', 0)}。\n"
            f"MRR：{summary.get('mrr', 0)}，nDCG@5：{summary.get('ndcg_at_5', 0)}。"
        )
    if tool_name == "get_rag_trace_evidence_evaluation":
        if not data.get("success"):
            return data.get("message") or data.get("error") or "没有找到对应的 evidence-level 评估详情。"
        evidence = data.get("evidence") or []
        if not evidence:
            return data.get("message") or "该 trace 没有 evidence 或暂无 evidence-level feedback。"
        lines = [f"trace {data.get('trace_id')} 的 evidence-level 评估详情："]
        for item in evidence[:5]:
            feedback = item.get("latest_feedback")
            label = feedback.get("relevance_label") if feedback else "未标注"
            lines.append(f"- rank {item.get('rank')} / {item.get('chunk_id')}：{label}")
        return "\n".join(lines)
    return "我现在支持：搜索论文、接收论文、深入阅读、查看已接收论文、查看详情、生成知识树、挖掘创新点。"


def _format_workflow_run(title: str, run: dict[str, Any]) -> str:
    mode = "dry_run 演示" if run.get("dry_run") else "真实执行"
    status = "成功" if run.get("success") else "失败"
    lines = [
        f"{title}：{run.get('topic')}",
        f"run_id：{run.get('run_id')}",
        f"状态：{status}，模式：{mode}。",
        f"搜索论文：{run.get('searched_count')} 篇；接收：{run.get('accepted_count')} 篇；深入阅读：{run.get('ingested_count')} 篇。",
    ]
    warnings = run.get("warnings") or []
    if warnings:
        lines.append(f"提醒：{warnings[0]}")
    if run.get("error"):
        lines.append(f"错误：{run.get('error')}")
    return "\n".join(lines)


def _format_rag_trace_list(title: str, items: list[dict[str, Any]]) -> str:
    if not items:
        return f"{title}：暂无记录。"
    lines = [f"{title}（{len(items)} 条）："]
    for item in items[:10]:
        mode = item.get("mode")
        no_evidence = "no evidence" if item.get("no_evidence") else f"命中 {item.get('hit_count')} 条"
        paper = item.get("paper_id") or "all"
        lines.append(
            f"- {item.get('trace_id')} | {mode} | paper={paper} | {no_evidence} | query={_preview_line(item.get('query') or '')}"
        )
    return "\n".join(lines)


def _preview_line(text: str, max_chars: int = 80) -> str:
    line = " ".join(str(text).split())
    return line[:max_chars] + ("..." if len(line) > max_chars else "")
