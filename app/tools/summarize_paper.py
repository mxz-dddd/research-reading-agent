def summarize_paper(title: str, abstract: str | None = None) -> str:
    # TODO: 后续统一改为调用 PaperService 的 LLM 总结能力。
    if abstract:
        return f"""# {title}

## 研究问题
根据摘要初步判断，需要进一步阅读全文确认。

## 核心方法
摘要片段：{abstract[:500]}

## 关键贡献
规则版总结暂不能稳定判断，建议结合正文继续精读。

## 实验/验证情况
待 PDF 正文解析后补充。

## 优势
已具备可归档的基础摘要信息。

## 局限
当前仅基于摘要生成。

## 对后续研究的启发
可先判断其主题、方法和实验对象是否与你的研究方向一致。
"""
    return f"《{title}》缺少摘要，后续会尝试根据可用信息总结。"
