import os
import sys
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv() -> None:
    """零依赖加载项目根目录的 .env 到 os.environ。

    设计要点：
    - 不引入第三方依赖；解析 KEY=VALUE，忽略空行与 # 注释，去除引号。
    - 真实环境变量优先：已存在的 key 不会被 .env 覆盖。
    - 运行 pytest 时跳过，保持测试不依赖本地 .env（可用 RRA_SKIP_DOTENV=1 显式关闭）。
    - 可用 DOTENV_PATH 指定 .env 路径，默认项目根目录下的 .env。
    """
    if os.getenv("RRA_SKIP_DOTENV", "").lower() in {"1", "true", "yes"}:
        return
    if "pytest" in sys.modules:
        return
    dotenv_path = os.getenv("DOTENV_PATH")
    path = Path(dotenv_path) if dotenv_path else Path(__file__).resolve().parents[2] / ".env"
    if not path.is_file():
        return
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export "):].strip()
        if not key or key in os.environ:
            continue
        value = value.strip().strip('"').strip("'")
        os.environ[key] = value


_load_dotenv()


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "Research Agent")
    database_path: str = os.getenv("DATABASE_PATH", "data/research_agent.db")
    openai_api_key: str | None = os.getenv("OPENAI_API_KEY")
    # 可用 OPENAI_MODEL 覆盖；LLM 调用统一走 Responses API。
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    openai_base_url: str = os.getenv("OPENAI_BASE_URL", "")
    feishu_app_id: str | None = os.getenv("FEISHU_APP_ID")
    feishu_app_secret: str | None = os.getenv("FEISHU_APP_SECRET")
    feishu_verification_token: str | None = os.getenv("FEISHU_VERIFICATION_TOKEN")
    feishu_encrypt_key: str | None = os.getenv("FEISHU_ENCRYPT_KEY")
    feishu_bot_name: str | None = os.getenv("FEISHU_BOT_NAME")
    feishu_enable_signature_check: bool = (
        os.getenv("FEISHU_ENABLE_SIGNATURE_CHECK", "false").lower() == "true"
    )
    rag_retrieval_mode: str = os.getenv("RAG_RETRIEVAL_MODE", "hybrid")
    rag_embedding_provider: str = os.getenv("RAG_EMBEDDING_PROVIDER", "hash")
    rag_embedding_dim: int = int(os.getenv("RAG_EMBEDDING_DIM", "256"))
    rag_sentence_transformers_model: str = os.getenv(
        "RAG_SENTENCE_TRANSFORMERS_MODEL",
        "sentence-transformers/all-MiniLM-L6-v2",
    )
    rag_sentence_transformers_device: str = os.getenv("RAG_SENTENCE_TRANSFORMERS_DEVICE", "auto")
    rag_embedding_batch_size: int = int(os.getenv("RAG_EMBEDDING_BATCH_SIZE", "32"))
    rag_rrf_k: int = int(os.getenv("RAG_RRF_K", "60"))
    rag_rerank_enabled: bool = os.getenv("RAG_RERANK_ENABLED", "true").lower() == "true"
    rag_rerank_provider: str = os.getenv("RAG_RERANK_PROVIDER", "deterministic")
    rag_cross_encoder_model: str = os.getenv(
        "RAG_CROSS_ENCODER_MODEL",
        "cross-encoder/ms-marco-MiniLM-L-6-v2",
    )
    rag_context_token_budget: int = int(os.getenv("RAG_CONTEXT_TOKEN_BUDGET", "6000"))
    # auto 仅在配置 API key 时启用 LLM；否则保留确定性模板回答。
    rag_answer_mode: str = os.getenv("RAG_ANSWER_MODE", "auto")
    # sqlite（默认）在索引期预计算并缓存 embedding，检索时只读缓存，避免每次全量重算；
    # none 保留原有“每次查询即时计算”行为；chroma 使用本地 Chroma 持久化。
    rag_vector_store: str = os.getenv("RAG_VECTOR_STORE", "sqlite")
    rag_chroma_persist_directory: str = os.getenv(
        "RAG_CHROMA_PERSIST_DIRECTORY", "data/chroma"
    )
    # Multi-step Agent is opt-in; the existing single-step route remains the default.
    agent_multi_step_enabled: bool = (
        os.getenv("AGENT_MULTI_STEP_ENABLED", "false").lower() == "true"
    )
    agent_max_steps: int = int(os.getenv("AGENT_MAX_STEPS", "3"))
    conversation_context_enabled: bool = (
        os.getenv("CONVERSATION_CONTEXT_ENABLED", "true").lower() == "true"
    )
    conversation_ttl_hours: int = int(os.getenv("CONVERSATION_TTL_HOURS", "168"))
    conversation_max_turns: int = int(os.getenv("CONVERSATION_MAX_TURNS", "10"))
    conversation_max_result_refs: int = int(os.getenv("CONVERSATION_MAX_RESULT_REFS", "20"))


settings = Settings()
