from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_paperweave_name_is_present_in_docs_and_frontend() -> None:
    readme = read_text("README.md")
    docs = read_text("docs/rag_v2_context_pack.md")
    frontend = read_text("frontend/streamlit_app.py")

    assert "PaperWeave" in readme
    assert "PaperWeave 论文证据织网" in docs
    assert "PaperWeave 调试台" in frontend
    assert "PaperWeave 评估看板" in frontend


def test_public_docs_do_not_use_blocked_old_names() -> None:
    combined = "\n".join(
        [
            read_text("README.md"),
            read_text("docs/rag_v2_context_pack.md"),
        ]
    )

    blocked_terms = [
        "RAG" + " demo",
        "research-agent-rag" + "-workflow",
        "rag" + "2",
        "RAG" + "2",
    ]
    for term in blocked_terms:
        assert term not in combined


def test_old_page_titles_are_not_user_visible() -> None:
    combined = "\n".join(
        [
            read_text("README.md"),
            read_text("frontend/streamlit_app.py"),
        ]
    )

    assert "RAG" + " v2 调试台" not in combined
    assert "RAG" + " v2 评估看板" not in combined
