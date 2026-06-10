from __future__ import annotations

from typing import Any

from app.schemas.paper import PaperRead


GAP_CATEGORIES = [
    "problem gap",
    "method gap",
    "data gap",
    "evaluation gap",
    "engineering gap",
]


def build_fallback_innovations(
    papers: list[PaperRead],
    knowledge_context: str | None = None,
) -> dict[str, Any]:
    warning = None
    if len(papers) < 4:
        warning = "当前已接收论文少于 4 篇，创新点覆盖可能不足，建议继续补充论文后再复核。"

    ideas = [
        _problem_gap(papers),
        _method_gap(papers),
        _evaluation_gap(papers),
        _engineering_gap(papers),
    ]
    if any(_has_data_signal(paper) for paper in papers):
        ideas.insert(2, _data_gap(papers))
    else:
        ideas.append(_data_gap(papers))

    return {
        "warning": warning,
        "evidence_based_findings": _evidence_findings(papers),
        "model_inference": "规则版 fallback 基于 deep_summary、screening_summary、标题和摘要做关键词归纳；它是研究线索，不是确定事实。",
        "innovation_ideas": ideas,
        "knowledge_context_used": bool(knowledge_context),
    }


def _evidence_findings(papers: list[PaperRead]) -> list[dict[str, Any]]:
    findings = []
    for paper in papers:
        evidence = paper.deep_summary or paper.screening_summary or paper.abstract or "暂无可用文本"
        findings.append(
            {
                "paper_id": paper.id,
                "title": paper.title,
                "finding": evidence[:300],
                "source_field": _source_field(paper),
            }
        )
    return findings


def _problem_gap(papers: list[PaperRead]) -> dict[str, Any]:
    evidence = _paper_evidence(papers, ["problem", "challenge", "问题", "局限"])
    return _idea(
        title="从真实应用场景重新定义核心问题",
        category="problem gap",
        why="现有论文常围绕单点任务或模型现象展开，真实场景中的问题边界、失败条件和用户约束可能还没有被充分定义。",
        evidence=evidence,
        direction="选择一个具体应用场景，重新定义任务边界、失败类型和约束条件，再设计针对性方法。",
        value="有助于形成更清晰的研究问题，并减少只做模型微调的同质化选题。",
        risk="中",
        confidence="中",
    )


def _method_gap(papers: list[PaperRead]) -> dict[str, Any]:
    evidence = _paper_evidence(papers, ["method", "framework", "model", "方法", "算法"])
    return _idea(
        title="把现有方法组合成更可控的模块化流程",
        category="method gap",
        why="多篇论文会提出局部有效的方法，但方法之间的接口、可解释性和可控性常常不足。",
        evidence=evidence,
        direction="把检测、生成、校正、评估拆成模块，研究模块之间的协同和错误传播控制。",
        value="更容易做消融实验，也更适合工程落地和后续扩展。",
        risk="中",
        confidence="中",
    )


def _data_gap(papers: list[PaperRead]) -> dict[str, Any]:
    evidence = _paper_evidence(papers, ["data", "dataset", "benchmark", "数据"])
    return _idea(
        title="构建更贴近目标场景的数据与错误案例集",
        category="data gap",
        why="论文中如果依赖公开 benchmark，可能无法覆盖真实场景里的长尾错误、噪声和领域差异。",
        evidence=evidence,
        direction="收集或整理小规模高质量案例集，覆盖常见失败模式、边界样本和跨域样本。",
        value="数据贡献可以支撑方法创新，也能让评估更可信。",
        risk="高",
        confidence="低",
    )


def _evaluation_gap(papers: list[PaperRead]) -> dict[str, Any]:
    evidence = _paper_evidence(papers, ["experiment", "evaluation", "metric", "benchmark", "实验", "评估"])
    return _idea(
        title="设计更能反映真实价值的评估指标",
        category="evaluation gap",
        why="现有实验可能只证明平均性能提升，但没有充分说明稳定性、失败代价和真实使用价值。",
        evidence=evidence,
        direction="加入鲁棒性、置信度、错误严重性、人工复核成本等指标。",
        value="能帮助区分“指标好看”和“真的可用”的方法。",
        risk="中",
        confidence="中",
    )


def _engineering_gap(papers: list[PaperRead]) -> dict[str, Any]:
    evidence = _paper_evidence(papers, ["deployment", "latency", "efficiency", "system", "工程", "部署"])
    return _idea(
        title="面向低成本部署优化系统流程",
        category="engineering gap",
        why="论文方法通常关注效果，但真实使用还受延迟、成本、稳定性和可维护性限制。",
        evidence=evidence,
        direction="研究轻量化推理、缓存、分阶段触发和失败回退机制。",
        value="更容易形成可演示系统，也能增强研究的应用说服力。",
        risk="中",
        confidence="低",
    )


def _idea(
    *,
    title: str,
    category: str,
    why: str,
    evidence: list[dict[str, Any]],
    direction: str,
    value: str,
    risk: str,
    confidence: str,
) -> dict[str, Any]:
    return {
        "title": title,
        "category": category,
        "why_this_gap_exists": why,
        "evidence_from_papers": evidence,
        "possible_research_direction": direction,
        "expected_value": value,
        "risk_level": risk,
        "confidence_level": confidence,
    }


def _paper_evidence(papers: list[PaperRead], keywords: list[str]) -> list[dict[str, Any]]:
    matched = []
    for paper in papers:
        text = " ".join(
            [
                paper.title or "",
                paper.abstract or "",
                paper.deep_summary or "",
                paper.screening_summary or "",
            ]
        )
        lower_text = text.lower()
        if any(keyword.lower() in lower_text for keyword in keywords):
            matched.append(
                {
                    "paper_id": paper.id,
                    "title": paper.title,
                    "evidence": text[:260],
                }
            )
    if matched:
        return matched[:4]
    return [
        {
            "paper_id": paper.id,
            "title": paper.title,
            "evidence": (paper.deep_summary or paper.screening_summary or paper.abstract or "暂无明确证据")[:260],
        }
        for paper in papers[:2]
    ]


def _source_field(paper: PaperRead) -> str:
    if paper.deep_summary:
        return "deep_summary"
    if paper.screening_summary:
        return "screening_summary"
    if paper.abstract:
        return "abstract"
    return "title"


def _has_data_signal(paper: PaperRead) -> bool:
    text = " ".join([paper.title or "", paper.abstract or "", paper.deep_summary or ""]).lower()
    return any(word in text for word in ["data", "dataset", "benchmark", "数据"])
