from app.schemas.paper import PaperRead

CATEGORIES = [
    "背景与综述",
    "核心问题定义",
    "关键方法",
    "实验与验证",
    "应用与扩展",
    "局限与开放问题",
]


def pick_category(paper: PaperRead) -> str:
    text = " ".join(
        [
            paper.title or "",
            paper.abstract or "",
            paper.deep_summary or "",
            paper.screening_summary or "",
        ]
    ).lower()
    if any(word in text for word in ["survey", "review", "overview", "综述", "背景"]):
        return "背景与综述"
    if any(word in text for word in ["problem", "challenge", "定义", "问题"]):
        return "核心问题定义"
    if any(word in text for word in ["method", "framework", "model", "方法", "算法"]):
        return "关键方法"
    if any(word in text for word in ["experiment", "benchmark", "evaluation", "实验", "验证"]):
        return "实验与验证"
    if any(word in text for word in ["application", "medical", "deployment", "应用", "扩展"]):
        return "应用与扩展"
    return "局限与开放问题"


def paper_label(paper: PaperRead) -> str:
    return f"[P{paper.id}] {paper.title}"
