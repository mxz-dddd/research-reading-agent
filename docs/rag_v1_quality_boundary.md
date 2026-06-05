# RAG v1 质量边界说明

本文档说明当前 Research Reading Agent 中轻量 RAG v1 的实现方式、适用场景、能力边界和后续升级路线。RAG v1 是科研阅读工作台中的本地查询与复盘模块，不是项目的唯一目标。

## 当前实现方式

RAG v1 是一个本地、轻量、可测试的检索增强模块，目标是先跑通 evidence retrieval 链路，而不是一次性实现完整向量 RAG。

当前链路：

```text
已 ingest 论文文本
-> 文本切分 chunks
-> 写入 SQLite rag_chunks 表
-> keyword / token overlap 检索
-> 返回 evidence chunks
-> 模板化保守回答
-> 保存 RAG evidence trace
-> 人工 feedback 标注
-> 轻量 evaluation summary
-> evidence-level feedback
-> Recall@K / MRR / nDCG@5
```

核心特点：

- 使用 SQLite `rag_chunks` 表保存 chunks。
- 优先读取已 ingest 论文的 `local_text_path`，缺失时兼容 summary / abstract。
- 使用固定字符长度和 overlap 切分文本。
- 检索时基于 query token 与 chunk token 的 overlap 计分。
- 返回 `matched_terms`、`score_reason`、`content_preview` 和 evidence chunk 元数据。
- `answer_with_rag` 使用模板化回答，不调用 LLM。
- `search_rag` / `answer_with_rag` 默认保存 Evidence Trace，包括 query、mode、paper_id、top_k、evidence、answer、no_evidence 和 metadata。
- `rag_trace_feedback` 保存人工相关性标注，summary 基于每条 trace 的最新 feedback 统计。
- `rag_evidence_feedback` 保存单条 evidence chunk 的相关性标注，指标基于每个 trace/chunk 的最新标注统计。
- 当前不调用 OpenAI embedding，不接 Qdrant，不做 rerank。

## 适合的场景

RAG v1 适合做轻量 evidence 定位：

- 术语检索：查看某个关键词是否出现在已索引论文中。
- 关键词定位：快速找到包含某些方法名、任务名或概念名的论文片段。
- 论文片段查找：为后续阅读定位相关 chunk。
- 概念出现验证：判断某个概念是否在已 ingest 文本中出现过。
- 本地演示和测试：在无 embedding、无向量数据库条件下展示 RAG 基础链路。

## 不适合的场景

RAG v1 不适合承担完整语义检索和复杂问答：

- 复杂语义改写：query 与论文表达差异较大时，关键词 overlap 可能召回失败。
- 跨段落深度推理：当前检索以单个 chunk 为单位，不做跨 chunk 推理。
- 同义词召回：没有 embedding，无法稳定召回同义表达。
- 高质量自然语言综合回答：当前回答是模板化保守总结，不是 LLM 融合生成。
- 大规模论文库检索：SQLite + 简单扫描适合 MVP，不适合大规模高性能检索。

## 如何避免幻觉

当前 RAG v1 使用以下策略降低幻觉风险：

- 没有 evidence chunks 时不编造答案。
- no evidence 场景返回明确提示：当前已索引论文中没有检索到足够证据。
- 有 evidence 时在回答中展示 `[Evidence 1]`、`[Evidence 2]` 等编号。
- 每个 evidence chunk 返回 `matched_terms` 和 `score_reason`，说明为什么被召回。
- 回答中明确标注：RAG v1 使用关键词 / token overlap 检索，不等价于完整语义理解。
- `content_preview` 用于快速展示，`content` 保留完整 chunk，方便进一步复核。
- RAG Evidence Trace 会保存 query、evidence、answer 和 no_evidence 状态，方便之后检查是否存在误召回或无证据回答。

## Evidence Trace

当前新增了 `rag_traces` 表，用于保存每次 RAG search / answer 的证据链路：

- `trace_id`: 单次 trace ID
- `query`: 用户问题或检索关键词
- `mode`: `search` 或 `answer`
- `paper_id`: 可选论文 ID
- `top_k`: 检索数量
- `hit_count`: evidence 命中数量
- `no_evidence`: 是否没有证据
- `answer`: answer 模式下的模板回答
- `evidence`: top evidence chunks 的结构化 JSON
- `metadata`: score summary、warning、source 等轻量信息

可用接口：

- `GET /api/rag/traces/latest`
- `GET /api/rag/traces/{trace_id}`
- `GET /api/rag/traces/by-paper/{paper_id}`

Trace 不是自动质量判分，它只是把检索和回答过程保存下来。后续可以基于 trace 做人工标注、误召回分析和系统化评估。

## 人工 Feedback 与轻量评估

当前新增 `rag_trace_feedback` 表，用于对 RAG trace 做人工相关性标注。

支持 label：

- `relevant`: evidence 与 query 相关。
- `partially_relevant`: evidence 部分相关，但覆盖不足。
- `irrelevant`: evidence 与 query 不相关。
- `no_evidence_correct`: 系统拒答是正确的。
- `no_evidence_incorrect`: 系统拒答是错误的，应该召回证据。

评估摘要会统计：

- `total_traces`
- `answered_traces`
- `no_evidence_traces`
- `total_feedback`
- `relevance_rate`
- `no_evidence_accuracy`
- `label_distribution`

可用接口：

- `POST /api/rag/traces/{trace_id}/feedback`
- `GET /api/rag/evaluation/summary`
- `GET /api/rag/evaluation/traces/{trace_id}`

注意：当前 evaluation summary 是基于人工 feedback 的轻量统计，不是自动评估，不等价于 RAGAS。

## Evidence-Level 标注与排序指标

当前新增 `rag_evidence_feedback` 表，用于对一次 trace 中的每条 evidence chunk 做精细标注。

支持分数：

- `0`: irrelevant
- `1`: partially_relevant
- `2`: relevant

评估时默认使用同一个 `trace_id + chunk_id` 的最新一条标注。

轻量指标定义：

- `Recall@K`: 对每个有标注的 trace，只要 top-K 中至少有一个 `relevance_score > 0`，就算命中。
- `MRR`: 对每个 trace 找到第一个 `relevance_score > 0` 的 rank，计算 `1 / rank` 后取平均。
- `nDCG@5`: 使用 `gain = relevance_score`，按 `(2^gain - 1) / log2(rank + 1)` 计算 DCG，再除以理想排序 IDCG。

可用接口：

- `POST /api/rag/traces/{trace_id}/evidence-feedback`
- `GET /api/rag/evaluation/evidence-summary`
- `GET /api/rag/evaluation/traces/{trace_id}/evidence`

这些指标仍然依赖人工标注，不是自动相关性判断。

## 轻量评估

当前新增了轻量评估脚本：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m app.evaluation.rag_eval
```

评估脚本会使用临时 SQLite 数据库和内置测试 chunks，不读取真实论文库，不写正式 `data` 数据库。

输出字段：

- `total_cases`: 测试 case 数量
- `hit_count`: 命中的 case 数量
- `hit_at_k`: top-k 命中率
- `cases`: 每条 case 的 query、expected、top_results、hit

这只是检索 smoke test，用于验证当前 keyword / token overlap 检索是否能命中明确关键词。它不是 RAGAS，也不是完整语义检索评估。

## 后续升级路线

后续可以按以下顺序升级：

1. 引入 embedding，为 chunks 生成向量表示。
2. 接入 Qdrant，支持向量检索和更大的论文库。
3. 增加 BM25 + dense hybrid retrieval，兼顾关键词和语义召回。
4. 增加 reranker，对候选 chunks 做重排。
5. 引入 LLM evidence fusion，让回答能更自然地整合多个 evidence。
6. 增加 RAGAS 风格评估样本导出和更完整的离线评估报表。
7. 引入自动相关性判断，减少人工标注成本。
8. 引入 evidence-level 可视化审核界面，让反馈可以持续积累。
