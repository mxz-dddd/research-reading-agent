import importlib


def test_paper_repository_import_is_annotation_safe() -> None:
    module = importlib.import_module("app.repositories.paper_repo")

    assert module.PaperRepository.__name__ == "PaperRepository"
