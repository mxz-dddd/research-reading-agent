import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "Research Agent")
    database_path: str = os.getenv("DATABASE_PATH", "data/research_agent.db")
    openai_api_key: str | None = os.getenv("OPENAI_API_KEY")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-5.4-mini")
    openai_base_url: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
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
    rag_context_token_budget: int = int(os.getenv("RAG_CONTEXT_TOKEN_BUDGET", "6000"))
    # auto 仅在配置 API key 时启用 LLM；否则保留确定性模板回答。
    rag_answer_mode: str = os.getenv("RAG_ANSWER_MODE", "auto")
    # none 保留原有即时计算行为；sqlite 显式启用本地 embedding 缓存。
    rag_vector_store: str = os.getenv("RAG_VECTOR_STORE", "none")
    rag_chroma_persist_directory: str = os.getenv(
        "RAG_CHROMA_PERSIST_DIRECTORY", "data/chroma"
    )


settings = Settings()
