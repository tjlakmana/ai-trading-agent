"""Guards for the project's structural safety rules."""

import ast
import importlib
from pathlib import Path

import pytest

import main

ROOT = Path(__file__).resolve().parent.parent
PACKAGES = ("core", "agent", "bot", "data", "strategy", "execution", "memory")

# Package -> project packages it must never import.
FORBIDDEN_IMPORTS = {
    # The agent interprets; it must never reach the bot's internals or the broker.
    "agent": {"bot", "execution"},
    # The bot controls; it must not depend on the agent or on any LLM SDK.
    "bot": {"agent", "anthropic"},
    # The strategy decides setups deterministically: no risk/execution internals,
    # no agent, and no LLM SDK deciding whether numeric thresholds passed.
    "strategy": {"bot", "execution", "agent", "anthropic"},
    # Data adapters only supply inputs: they never reach risk/execution, the agent, or an LLM SDK.
    "data": {"bot", "execution", "agent", "anthropic"},
    # Memory is an audit store: it records and replays, it never trades or calls an LLM.
    "memory": {"bot", "execution", "agent", "anthropic"},
    # core is the neutral contract; it must not depend on any other project code.
    "core": set(PACKAGES) - {"core"} | {"main", "tests"},
}


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


@pytest.mark.parametrize("package", sorted(FORBIDDEN_IMPORTS))
def test_forbidden_imports(package):
    forbidden = FORBIDDEN_IMPORTS[package]
    violations = []
    for path in (ROOT / package).rglob("*.py"):
        bad = _imported_top_level_modules(path) & forbidden
        if bad:
            violations.append(f"{path.relative_to(ROOT)} imports {sorted(bad)}")
    assert not violations, (
        f"{package}/ must not import {sorted(forbidden)}:\n" + "\n".join(violations)
    )


def test_ticker_constants_live_in_core_and_are_shared():
    symbols = importlib.import_module("core.symbols")
    validation = importlib.import_module("bot.validation")
    assert validation.TICKER_PATTERN is symbols.TICKER_PATTERN
    assert validation.MAX_TICKER_LENGTH == symbols.MAX_TICKER_LENGTH == 10


def test_main_runs():
    assert main.main() == 0
