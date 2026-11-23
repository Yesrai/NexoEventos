"""Los scripts del respaldo se ejecutan en la EC2 con `/usr/bin/python3` = 3.9 (Amazon Linux 2023). Python 3.9 evalúa las anotaciones al definir la función:
`dict | None` lanza TypeError salvo que el módulo use `from __future__ import annotations`. Comprobación estática (no hace falta tener 3.9 instalado)."""
import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ["scripts/multicloud/backup_cycle.py", "scripts/multicloud/backup_freshness.py"]


def _annotations(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield from (a.annotation for a in node.args.args + node.args.kwonlyargs if a.annotation)
            if node.returns:
                yield node.returns
        elif isinstance(node, ast.AnnAssign):
            yield node.annotation


@pytest.mark.parametrize("rel", SCRIPTS)
def test_script_parses_as_python_39_and_does_not_evaluate_union_annotations(rel: str) -> None:
    source = (ROOT / rel).read_text()
    tree = ast.parse(source, feature_version=(3, 9))  # SyntaxError si usa sintaxis posterior a 3.9
    has_union = any(isinstance(n, ast.BinOp) and isinstance(n.op, ast.BitOr) for a in _annotations(tree) for n in ast.walk(a))
    has_future = any(isinstance(n, ast.ImportFrom) and n.module == "__future__" and any(x.name == "annotations" for x in n.names) for n in tree.body)
    assert not has_union or has_future, f"{rel}: anotaciones X | Y sin `from __future__ import annotations` (fallan en Python 3.9)"


@pytest.mark.parametrize("rel", SCRIPTS)
def test_script_avoids_python_310_plus_stdlib_names(rel: str) -> None:
    text = (ROOT / rel).read_text()
    for forbidden in ("datetime.UTC", "tomllib", "ExceptionGroup", "StrEnum", "itertools.batched"):
        assert forbidden not in text, f"{rel} usa {forbidden}, que no existe en Python 3.9"
