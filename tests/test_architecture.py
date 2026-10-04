"""Guards for the project's structural safety rules."""

import ast
import importlib
from pathlib import Path

import pytest

import main

ROOT = Path(__file__).resolve().parent.parent
PACKAGES = ("agent", "bot", "data", "strategy", "execution", "memory")

# The agent proposes; it must never reach the bot's internals or the broker.
AGENT_FORBIDDEN_IMPORTS = ("bot", "execution")


@pytest.mark.parametrize("name", PACKAGES)
def test_package_imports(name):
    importlib.import_module(name)


def _imported_top_level_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module.split(".")[0])
    return found


def test_agent_never_imports_bot_or_execution():
    violations = []
    for path in (ROOT / "agent").rglob("*.py"):
        bad = _imported_top_level_modules(path) & set(AGENT_FORBIDDEN_IMPORTS)
        if bad:
            violations.append(f"{path.relative_to(ROOT)} imports {sorted(bad)}")
    assert not violations, "Agent must not import bot/execution:\n" + "\n".join(violations)


def test_main_runs():
    assert main.main() == 0
