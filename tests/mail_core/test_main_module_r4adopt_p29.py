"""A215: ``mail_core.__main__`` must not import names it never uses.

``Any`` was imported from typing but referenced nowhere in the module;
dead imports mislead readers about the module's surface. AST-level scan
so the check follows the source, not a frozen string.
"""

from __future__ import annotations

import ast
from pathlib import Path

import mail_core.__main__ as main_module


def test_main_module_does_not_import_any():
    source = Path(main_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                imported.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported.add((alias.asname or alias.name).split(".")[0])
    used = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }
    unused = imported - used - {"annotations"}
    assert "Any" not in imported, f"unused typing import remains: {sorted(unused)}"
