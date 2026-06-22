import ast
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYTHON_FILES = sorted(
    path
    for directory in ("app", "frontend", "tests")
    for path in (PROJECT_ROOT / directory).rglob("*.py")
)


@pytest.mark.parametrize("path", PYTHON_FILES, ids=lambda path: str(path.relative_to(PROJECT_ROOT)))
def test_source_parses_with_python_311_grammar(path: Path) -> None:
    ast.parse(
        path.read_text(encoding="utf-8"),
        filename=str(path),
        feature_version=(3, 11),
    )
