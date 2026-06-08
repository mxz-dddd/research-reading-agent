import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "Research Agent")
    database_path: str = os.getenv("DATABASE_PATH", "data/research_agent.db")
    openai_api_key: str | None = os.getenv("OPENAI_API_KEY")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-5.4-mini")
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
    rag_rrf_k: int = int(os.getenv("RAG_RRF_K", "60"))
    rag_rerank_enabled: bool = os.getenv("RAG_RERANK_ENABLED", "true").lower() == "true"
    rag_context_token_budget: int = int(os.getenv("RAG_CONTEXT_TOKEN_BUDGET", "6000"))


settings = Settings()
