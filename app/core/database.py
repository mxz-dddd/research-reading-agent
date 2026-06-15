import sqlite3
from pathlib import Path
from typing import Iterator

from app.core.config import settings


def get_connection() -> sqlite3.Connection:
    """创建 SQLite 连接，并让查询结果可以像字典一样读取。"""
    db_path = Path(settings.database_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    # WAL 提升并发读（读写不互斥）；busy_timeout 避免瞬时锁直接报错。
    # 不开启 foreign_keys 强制，以免影响现有插入顺序与既有数据。
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def get_db() -> Iterator[sqlite3.Connection]:
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row["name"] == column for row in rows)


def _add_column_if_missing(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    column_type: str,
) -> None:
    if not _column_exists(conn, table, column):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")


def init_db() -> None:
    """初始化数据库表；已有数据库会做最小字段补齐。"""
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS research_topics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS papers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic_id INTEGER,
                title TEXT NOT NULL,
                authors TEXT,
                abstract TEXT,
                url TEXT,
                source TEXT,
                published_at TEXT,
                summary TEXT,
                screening_summary TEXT,
                relevance_score INTEGER,
                worth_reading TEXT,
                is_accepted INTEGER NOT NULL DEFAULT 0,
                accepted_at TEXT,
                pdf_url TEXT,
                local_pdf_path TEXT,
                local_text_path TEXT,
                local_summary_path TEXT,
                abstract_summary TEXT,
                deep_summary TEXT,
                ingest_status TEXT,
                status TEXT NOT NULL DEFAULT 'found',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (topic_id) REFERENCES research_topics(id)
            )
            """
        )
        _add_column_if_missing(conn, "papers", "screening_summary", "TEXT")
        _add_column_if_missing(conn, "papers", "relevance_score", "INTEGER")
        _add_column_if_missing(conn, "papers", "worth_reading", "TEXT")
        _add_column_if_missing(conn, "papers", "is_accepted", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "papers", "accepted_at", "TEXT")
        _add_column_if_missing(conn, "papers", "pdf_url", "TEXT")
        _add_column_if_missing(conn, "papers", "local_pdf_path", "TEXT")
        _add_column_if_missing(conn, "papers", "local_text_path", "TEXT")
        _add_column_if_missing(conn, "papers", "local_summary_path", "TEXT")
        _add_column_if_missing(conn, "papers", "abstract_summary", "TEXT")
        _add_column_if_missing(conn, "papers", "deep_summary", "TEXT")
        _add_column_if_missing(conn, "papers", "ingest_status", "TEXT")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_search_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic TEXT NOT NULL,
                source TEXT NOT NULL,
                result_count INTEGER NOT NULL,
                query_text TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS knowledge_artifacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic TEXT,
                source_paper_count INTEGER NOT NULL,
                knowledge_tree_markdown TEXT NOT NULL,
                learning_roadmap_markdown TEXT NOT NULL,
                mermaid_mindmap TEXT NOT NULL,
                mermaid_flowchart TEXT NOT NULL,
                local_markdown_path TEXT NOT NULL,
                generation_method TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS innovation_artifacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic TEXT,
                source_paper_count INTEGER NOT NULL,
                innovation_markdown TEXT NOT NULL,
                innovation_json TEXT NOT NULL,
                summary_markdown TEXT NOT NULL,
                generation_method TEXT NOT NULL,
                local_markdown_path TEXT NOT NULL,
                local_json_path TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS session_state (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                state_json TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(user_id, session_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workflow_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL UNIQUE,
                topic TEXT NOT NULL,
                success INTEGER NOT NULL,
                dry_run INTEGER NOT NULL DEFAULT 0,
                max_results INTEGER NOT NULL,
                accept_top_k INTEGER NOT NULL,
                searched_count INTEGER NOT NULL,
                accepted_count INTEGER NOT NULL,
                ingested_count INTEGER NOT NULL,
                knowledge_generated INTEGER NOT NULL,
                innovation_generated INTEGER NOT NULL,
                warnings_json TEXT NOT NULL,
                result_json TEXT NOT NULL,
                error TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS rag_chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chunk_id TEXT NOT NULL UNIQUE,
                paper_id TEXT NOT NULL,
                source_type TEXT NOT NULL,
                source_path TEXT,
                chunk_index INTEGER NOT NULL,
                content TEXT NOT NULL,
                content_preview TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        _add_column_if_missing(conn, "rag_chunks", "contextual_header", "TEXT")
        _add_column_if_missing(conn, "rag_chunks", "section_title", "TEXT")
        _add_column_if_missing(conn, "rag_chunks", "content_for_embedding", "TEXT")
        _add_column_if_missing(conn, "rag_chunks", "token_count", "INTEGER DEFAULT 0")
        _add_column_if_missing(conn, "rag_chunks", "chunker_version", "TEXT DEFAULT 'contextual_v1'")
        _add_column_if_missing(conn, "rag_chunks", "index_version", "TEXT DEFAULT 'hybrid_v2'")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS rag_embeddings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chunk_id TEXT NOT NULL,
                provider_key TEXT NOT NULL,
                dim INTEGER NOT NULL,
                vector_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(chunk_id, provider_key)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS context_packs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                context_pack_id TEXT NOT NULL UNIQUE,
                user_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                query TEXT NOT NULL,
                mode TEXT NOT NULL,
                paper_id TEXT,
                token_budget INTEGER NOT NULL,
                estimated_tokens INTEGER NOT NULL,
                item_count INTEGER NOT NULL,
                context_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS rag_traces (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trace_id TEXT NOT NULL UNIQUE,
                query TEXT NOT NULL,
                mode TEXT NOT NULL,
                paper_id TEXT,
                top_k INTEGER NOT NULL,
                hit_count INTEGER NOT NULL,
                no_evidence INTEGER NOT NULL,
                answer TEXT,
                evidence_json TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS rag_trace_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                feedback_id TEXT NOT NULL UNIQUE,
                trace_id TEXT NOT NULL,
                relevance_label TEXT NOT NULL,
                expected_terms_json TEXT NOT NULL,
                notes TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS rag_evidence_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                evidence_feedback_id TEXT NOT NULL UNIQUE,
                trace_id TEXT NOT NULL,
                chunk_id TEXT NOT NULL,
                rank INTEGER NOT NULL,
                relevance_score INTEGER NOT NULL,
                relevance_label TEXT NOT NULL,
                notes TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        _create_indexes(conn)
        conn.commit()


def _create_indexes(conn: sqlite3.Connection) -> None:
    """为高频过滤/排序列建立索引，避免随数据增长退化为全表扫描。"""
    index_statements = (
        # 检索按 paper_id 过滤（list_all_chunks / search_chunks / list_chunks_by_paper_id）
        "CREATE INDEX IF NOT EXISTS idx_rag_chunks_paper_id ON rag_chunks(paper_id)",
        # trace 按论文查询与按时间倒序列出
        "CREATE INDEX IF NOT EXISTS idx_rag_traces_paper_id ON rag_traces(paper_id)",
        "CREATE INDEX IF NOT EXISTS idx_rag_traces_created_at ON rag_traces(created_at)",
        # feedback 按 trace_id 聚合
        "CREATE INDEX IF NOT EXISTS idx_rag_trace_feedback_trace_id ON rag_trace_feedback(trace_id)",
        "CREATE INDEX IF NOT EXISTS idx_rag_evidence_feedback_trace_id ON rag_evidence_feedback(trace_id)",
        # workflow 历史按时间倒序列出 / latest
        "CREATE INDEX IF NOT EXISTS idx_workflow_runs_created_at ON workflow_runs(created_at)",
        # context pack 按 user/session 最近列表查询
        "CREATE INDEX IF NOT EXISTS idx_context_packs_user_session ON context_packs(user_id, session_id, created_at)",
        # 论文列表常按接收状态过滤
        "CREATE INDEX IF NOT EXISTS idx_papers_is_accepted ON papers(is_accepted)",
    )
    for statement in index_statements:
        conn.execute(statement)
