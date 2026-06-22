import json
import re
import ssl
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import certifi


class ArchiveService:
    def __init__(self) -> None:
        self.pdf_dir = Path("data/papers/pdfs")
        self.text_dir = Path("data/papers/text")
        self.summary_dir = Path("data/archives/summaries")
        self.knowledge_dir = Path("data/archives/knowledge")
        self.innovation_dir = Path("data/archives/innovation")

    def ensure_dirs(self) -> None:
        self.pdf_dir.mkdir(parents=True, exist_ok=True)
        self.text_dir.mkdir(parents=True, exist_ok=True)
        self.summary_dir.mkdir(parents=True, exist_ok=True)
        self.knowledge_dir.mkdir(parents=True, exist_ok=True)
        self.innovation_dir.mkdir(parents=True, exist_ok=True)

    def make_base_name(self, paper_id: int, title: str) -> str:
        safe_title = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "-", title).strip("-")
        safe_title = safe_title[:60] or "paper"
        return f"{paper_id}-{safe_title}"

    def download_pdf(self, pdf_url: str, base_name: str) -> tuple[str | None, str | None]:
        self.ensure_dirs()
        pdf_path = self.pdf_dir / f"{base_name}.pdf"
        request = Request(pdf_url, headers={"User-Agent": "research-agent/0.3"})

        try:
            with urlopen(request, timeout=30, context=self._ssl_context()) as response:
                content_type = response.headers.get("Content-Type", "")
                data = response.read()
            if "pdf" not in content_type.lower() and not data.startswith(b"%PDF"):
                return None, "PDF 无法访问或返回内容不是 PDF"
            pdf_path.write_bytes(data)
            return str(pdf_path), None
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            return None, f"PDF 下载失败：{exc}"

    def extract_pdf_text(self, pdf_path: str, base_name: str) -> tuple[str | None, str | None]:
        self.ensure_dirs()
        text_path = self.text_dir / f"{base_name}.txt"

        try:
            from pypdf import PdfReader
        except ImportError:
            return None, "PDF 文本提取失败：缺少 pypdf 依赖"

        try:
            reader = PdfReader(pdf_path)
            pages: list[str] = []
            for page in reader.pages:
                pages.append(page.extract_text() or "")
            text = "\n\n".join(page for page in pages if page.strip()).strip()
            if not text:
                return None, "PDF 文本提取失败：未提取到有效文本"
            text_path.write_text(text, encoding="utf-8")
            return str(text_path), None
        except Exception as exc:
            return None, f"PDF 文本提取失败：{exc}"

    def write_abstract_text(self, abstract: str, base_name: str) -> str:
        self.ensure_dirs()
        text_path = self.text_dir / f"{base_name}-abstract.txt"
        text_path.write_text(abstract or "无摘要", encoding="utf-8")
        return str(text_path)

    def write_summary(self, content: str, base_name: str) -> str:
        self.ensure_dirs()
        summary_path = self.summary_dir / f"{base_name}.md"
        summary_path.write_text(content, encoding="utf-8")
        return str(summary_path)

    def write_knowledge_artifact(self, topic: str | None, content: str) -> str:
        self.ensure_dirs()
        safe_topic = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "-", topic or "all").strip("-")
        safe_topic = safe_topic[:60] or "all"
        timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        path = self.knowledge_dir / f"{timestamp}-{safe_topic}.md"
        path.write_text(content, encoding="utf-8")
        return str(path)

    def write_innovation_artifact(
        self,
        topic: str | None,
        markdown_content: str,
        json_content: dict,
    ) -> tuple[str, str]:
        self.ensure_dirs()
        safe_topic = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "-", topic or "all").strip("-")
        safe_topic = safe_topic[:60] or "all"
        timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        markdown_path = self.innovation_dir / f"{timestamp}-{safe_topic}.md"
        json_path = self.innovation_dir / f"{timestamp}-{safe_topic}.json"
        markdown_path.write_text(markdown_content, encoding="utf-8")
        json_path.write_text(
            json.dumps(json_content, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return str(markdown_path), str(json_path)

    def _ssl_context(self) -> ssl.SSLContext:
        return ssl.create_default_context(cafile=certifi.where())
