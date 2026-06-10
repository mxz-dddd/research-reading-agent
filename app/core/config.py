from __future__ import annotations

import os
from dataclasses import dataclass


def _env_bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).lower() == "true"


@dataclass(frozen=True)
class Settings:
    app_name: str = "Research Agent"
    database_path: str = "data/research_agent.db"
    openai_api_key: str | None = None
    openai_model: str = "gpt-5.4-mini"
    feishu_app_id: str | None = None
    feishu_app_secret: str | None = None
    feishu_verification_token: str | None = None
    feishu_encrypt_key: str | None = None
    feishu_bot_name: str | None = None
    feishu_enable_signature_check: bool = False
    rag_retrieval_mode: str = "hybrid"
    rag_embedding_provider: str = "hash"
    rag_embedding_dim: int = 256
    rag_rrf_k: int = 60
    rag_rerank_enabled: bool = True
    rag_context_token_budget: int = 6000

    @classmethod
    def from_env(cls) -> Settings:
        """在调用时读取环境变量构造配置（而不是 import 时）。"""
        return cls(
            app_name=os.getenv("APP_NAME", cls.app_name),
            database_path=os.getenv("DATABASE_PATH", cls.database_path),
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            openai_model=os.getenv("OPENAI_MODEL", cls.openai_model),
            feishu_app_id=os.getenv("FEISHU_APP_ID"),
            feishu_app_secret=os.getenv("FEISHU_APP_SECRET"),
            feishu_verification_token=os.getenv("FEISHU_VERIFICATION_TOKEN"),
            feishu_encrypt_key=os.getenv("FEISHU_ENCRYPT_KEY"),
            feishu_bot_name=os.getenv("FEISHU_BOT_NAME"),
            feishu_enable_signature_check=_env_bool("FEISHU_ENABLE_SIGNATURE_CHECK"),
            rag_retrieval_mode=os.getenv("RAG_RETRIEVAL_MODE", cls.rag_retrieval_mode),
            rag_embedding_provider=os.getenv("RAG_EMBEDDING_PROVIDER", cls.rag_embedding_provider),
            rag_embedding_dim=int(os.getenv("RAG_EMBEDDING_DIM", str(cls.rag_embedding_dim))),
            rag_rrf_k=int(os.getenv("RAG_RRF_K", str(cls.rag_rrf_k))),
            rag_rerank_enabled=_env_bool("RAG_RERANK_ENABLED", "true"),
            rag_context_token_budget=int(
                os.getenv("RAG_CONTEXT_TOKEN_BUDGET", str(cls.rag_context_token_budget))
            ),
        )


settings = Settings.from_env()
