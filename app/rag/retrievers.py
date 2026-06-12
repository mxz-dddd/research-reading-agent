from app.rag.embeddings import cosine_similarity, get_embedding_provider
from app.rag.fusion import reciprocal_rank_fusion
from app.rag.rerankers import DeterministicReranker
from app.rag.sqlite_vector_store import SqliteVectorStore, build_provider_key
from app.schemas.rag import RagChunkRead, RagSearchChunk


def _preview(text: str, max_chars: int = 240) -> str:
    return text[:max_chars] + ("..." if len(text) > max_chars else "")


class HybridRetriever:
    def __init__(self, rag_repo, settings) -> None:
        self.rag_repo = rag_repo
        self.settings = settings
        self.embedding_provider = get_embedding_provider(
            provider=getattr(settings, "rag_embedding_provider", "hash"),
            dim=getattr(settings, "rag_embedding_dim", 256),
            model_name=getattr(
                settings,
                "rag_sentence_transformers_model",
                "sentence-transformers/all-MiniLM-L6-v2",
            ),
            device=getattr(settings, "rag_sentence_transformers_device", "auto"),
            batch_size=getattr(settings, "rag_embedding_batch_size", 32),
        )
        self.reranker = DeterministicReranker()
        self.vector_store = self._build_vector_store()

    def _build_vector_store(self):
        store_name = getattr(self.settings, "rag_vector_store", "none").strip().lower()
        if store_name == "sqlite":
            return SqliteVectorStore()
        if store_name == "chroma":
            from app.rag.chroma_vector_store import ChromaVectorStore

            return ChromaVectorStore(
                persist_directory=getattr(
                    self.settings,
                    "rag_chroma_persist_directory",
                    "data/chroma",
                )
            )
        return None

    def search(
        self,
        query: str,
        top_k: int,
        paper_id: str | None = None,
    ) -> tuple[list[RagSearchChunk], dict]:
        candidate_k = max(top_k * 4, 20)
        sparse_chunks = self.rag_repo.search_chunks(query, top_k=candidate_k, paper_id=paper_id)
        all_chunks = self.rag_repo.list_all_chunks(paper_id=paper_id)
        dense_pairs, embedding_cache = self._dense_candidates(
            query=query, chunks=all_chunks, limit=candidate_k
        )
        dense_scores = {chunk.chunk_id: score for chunk, score in dense_pairs}
        provider_metadata = self.embedding_provider.metadata()

        sparse_ids = [chunk.chunk_id for chunk in sparse_chunks]
        dense_ids = [chunk.chunk_id for chunk, _score in dense_pairs]
        rrf_scores = reciprocal_rank_fusion([sparse_ids, dense_ids], k=self.settings.rag_rrf_k)

        sparse_by_id = {chunk.chunk_id: chunk for chunk in sparse_chunks}
        read_by_id = {chunk.chunk_id: chunk for chunk in all_chunks}
        merged: list[RagSearchChunk] = []
        for chunk_id, rrf_score in sorted(rrf_scores.items(), key=lambda item: item[1], reverse=True):
            if chunk_id in sparse_by_id:
                item = sparse_by_id[chunk_id]
            else:
                read = read_by_id[chunk_id]
                item = self._read_to_search_chunk(
                    read,
                    score=dense_scores.get(chunk_id, 0.0),
                    provider_name=provider_metadata["embedding_provider"],
                )
            item.retrieval_scores = {
                "sparse": sparse_by_id.get(chunk_id).score if chunk_id in sparse_by_id else 0.0,
                "dense": dense_scores.get(chunk_id, 0.0),
                "rrf": rrf_score,
            }
            item.score = rrf_score
            merged.append(item)

        if self.settings.rag_rerank_enabled:
            merged = self.reranker.rerank(query, merged)
        else:
            merged.sort(key=lambda item: (item.score, item.chunk_id), reverse=True)

        pipeline = {
            "retrieval_mode": "hybrid",
            "sparse_candidate_count": len(sparse_chunks),
            "dense_candidate_count": len(dense_pairs),
            "fused_candidate_count": len(merged),
            "rerank_enabled": self.settings.rag_rerank_enabled,
            "rrf_k": self.settings.rag_rrf_k,
            "vector_store": self.vector_store.name if self.vector_store else "none",
            "embedding_cache": embedding_cache,
        }
        pipeline.update(provider_metadata)
        return merged[:top_k], pipeline

    def _dense_candidates(
        self,
        *,
        query: str,
        chunks: list[RagChunkRead],
        limit: int,
    ) -> tuple[list[tuple[RagChunkRead, float]], dict]:
        query_vec = self.embedding_provider.embed_text(query)
        chunk_vectors, cache_stats = self._chunk_vectors(chunks)
        scored: list[tuple[RagChunkRead, float]] = []
        for chunk in chunks:
            chunk_vec = chunk_vectors.get(chunk.chunk_id)
            if not chunk_vec:
                continue
            score = cosine_similarity(query_vec, chunk_vec)
            if score > 0:
                scored.append((chunk, score))
        scored.sort(key=lambda item: (item[1], item[0].chunk_id), reverse=True)
        return scored[:limit], cache_stats

    def _chunk_vectors(self, chunks: list[RagChunkRead]) -> tuple[dict[str, list[float]], dict]:
        provider_key = build_provider_key(self.embedding_provider.metadata())
        stored: dict[str, list[float]] = {}
        store_error: str | None = None
        if self.vector_store:
            try:
                stored = self.vector_store.get_vectors(
                    [chunk.chunk_id for chunk in chunks], provider_key
                )
            except Exception as exc:
                store_error = f"vector store read failed: {exc}"

        missing = [chunk for chunk in chunks if chunk.chunk_id not in stored]
        if missing:
            texts = [chunk.content_for_embedding or chunk.content for chunk in missing]
            embed_texts = getattr(self.embedding_provider, "embed_texts", None)
            vectors = (
                embed_texts(texts)
                if callable(embed_texts)
                else [self.embedding_provider.embed_text(text) for text in texts]
            )
            new_items = [(chunk.chunk_id, vector) for chunk, vector in zip(missing, vectors)]
            stored.update(dict(new_items))
            if self.vector_store and store_error is None:
                try:
                    self.vector_store.upsert_vectors(provider_key, new_items)
                except Exception as exc:
                    store_error = f"vector store write failed: {exc}"

        cache_stats = {
            "provider_key": provider_key,
            "total_chunks": len(chunks),
            "cache_hits": len(chunks) - len(missing) if self.vector_store else 0,
            "computed": len(missing),
        }
        if store_error:
            cache_stats["store_error"] = store_error
        return stored, cache_stats

    def _read_to_search_chunk(
        self,
        chunk: RagChunkRead,
        score: float,
        provider_name: str,
    ) -> RagSearchChunk:
        return RagSearchChunk(
            score=score,
            chunk_id=chunk.chunk_id,
            paper_id=chunk.paper_id,
            chunk_index=chunk.chunk_index,
            matched_terms=[],
            content=chunk.content,
            content_preview=_preview(chunk.content_preview or chunk.content),
            source_path=chunk.source_path,
            metadata=chunk.metadata,
            score_reason=f"dense {provider_name} embedding candidate",
            section_title=chunk.section_title,
            contextual_header=chunk.contextual_header,
        )
