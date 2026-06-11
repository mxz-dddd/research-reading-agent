"""保持测试离线、确定，并固定 PaperWeave 使用本地 hash embedding。"""

import os

os.environ.pop("OPENAI_API_KEY", None)
os.environ["RAG_EMBEDDING_PROVIDER"] = "hash"
