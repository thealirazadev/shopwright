"""The agent must not be able to change an order, even if prompted to.

Writes live in app.connectors.shopify.write and app.actions; nothing the agent
or the chat API imports may reach them. This is the code-level half of the
"proposals only" guarantee in docs/architecture.md.
"""

import ast
from pathlib import Path

APP = Path(__file__).parents[2] / "app"
FORBIDDEN = ("app.connectors.shopify.write", "app.actions")


def imports_of(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def test_agent_and_chat_cannot_import_write_paths() -> None:
    offenders = {
        f"{path.relative_to(APP)} imports {name}"
        for package in ("agent", "chat")
        for path in (APP / package).glob("*.py")
        for name in imports_of(path)
        if name.startswith(FORBIDDEN)
    }

    assert offenders == set()


def test_the_check_would_catch_a_violation(tmp_path: Path) -> None:
    bad = tmp_path / "bad.py"
    bad.write_text("from app.connectors.shopify.write import ShopifyWriteClient\n")

    assert any(name.startswith(FORBIDDEN) for name in imports_of(bad))
