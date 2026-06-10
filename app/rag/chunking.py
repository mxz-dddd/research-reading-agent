from __future__ import annotations

import re


SECTION_RE = re.compile(
    r"^\s*((\d+(\.\d+)*)\s+)?(abstract|introduction|background|method|methods|methodology|experiment|experiments|results|discussion|conclusion|references)\b.*$",
    re.IGNORECASE,
)


class ContextualChunker:
    def split(
        self,
        text: str,
        paper_title: str,
        source_type: str,
        source_path: str | None,
        chunk_size: int,
        chunk_overlap: int,
        chunker_version: str,
        index_version: str,
    ) -> list[dict]:
        paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
        if not paragraphs:
            return []
        chunks: list[dict] = []
        current_parts: list[str] = []
        section_title: str | None = None
        current_section: str | None = None

        expanded: list[str] = []
        for paragraph in paragraphs:
            if len(paragraph) <= chunk_size:
                expanded.append(paragraph)
                continue
            expanded.extend(self._split_long_paragraph(paragraph, chunk_size, chunk_overlap))

        for paragraph in expanded:
            maybe_section = self._section_title(paragraph)
            if maybe_section:
                current_section = maybe_section
            if current_parts and sum(len(part) for part in current_parts) + len(paragraph) + 2 > chunk_size:
                chunks.append(self._build_chunk(current_parts, paper_title, source_type, source_path, len(chunks), current_section or section_title, chunker_version, index_version))
                overlap_text = self._overlap_text("\n\n".join(current_parts), chunk_overlap)
                current_parts = [overlap_text] if overlap_text else []
            if maybe_section:
                section_title = maybe_section
            current_parts.append(paragraph)

        if current_parts:
            chunks.append(self._build_chunk(current_parts, paper_title, source_type, source_path, len(chunks), current_section or section_title, chunker_version, index_version))
        return chunks

    def _build_chunk(
        self,
        parts: list[str],
        paper_title: str,
        source_type: str,
        source_path: str | None,
        index: int,
        section_title: str | None,
        chunker_version: str,
        index_version: str,
    ) -> dict:
        content = "\n\n".join(part for part in parts if part).strip()
        header = (
            f"Paper: {paper_title}\n"
            f"Section: {section_title or 'Unknown'}\n"
            f"Chunk: {index}\n"
            f"Source: {source_type}"
        )
        if source_path:
            header += f"\nPath: {source_path}"
        content_for_embedding = f"{header}\n{content}"
        return {
            "content": content,
            "contextual_header": header,
            "section_title": section_title,
            "content_for_embedding": content_for_embedding,
            "token_count": len(re.findall(r"[a-zA-Z0-9_\u4e00-\u9fff]+", content_for_embedding)),
            "chunker_version": chunker_version,
            "index_version": index_version,
        }

    def _section_title(self, paragraph: str) -> str | None:
        first_line = paragraph.splitlines()[0].strip()
        if len(first_line) > 120:
            return None
        return first_line if SECTION_RE.match(first_line) else None

    def _overlap_text(self, text: str, chunk_overlap: int) -> str:
        if chunk_overlap <= 0:
            return ""
        return text[-chunk_overlap:].strip()

    def _split_long_paragraph(self, paragraph: str, chunk_size: int, chunk_overlap: int) -> list[str]:
        safe_overlap = min(chunk_overlap, max(chunk_size - 1, 0))
        step = max(1, chunk_size - safe_overlap)
        parts: list[str] = []
        for start in range(0, len(paragraph), step):
            part = paragraph[start : start + chunk_size].strip()
            if part:
                parts.append(part)
            if start + chunk_size >= len(paragraph):
                break
        return parts
