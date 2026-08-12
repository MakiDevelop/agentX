"""Lock the shape of runner-facing JSON payloads.

`agentx capabilities/next/gate/status/inspect --json` are consumed by external
runners — other agents, CI steps, scripts. Their whole purpose is that a caller
does not have to parse human prose. That only holds if the shape is stable.

Nothing enforced it. Every payload is assembled by hand as `dict[str, object]`
(259 such annotations across src/), so renaming a key, dropping one, or changing
a value's type is a one-line edit that no test notices and no type checker
catches — while silently breaking every downstream consumer.

These tests snapshot the *shape* (schema id, top-level key names, value types),
never the values, so they are stable across machines and workspaces. When a
payload legitimately changes, update the snapshot in the same commit: that makes
the contract change visible in review instead of invisible in production.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from agentx.cli import app

SNAPSHOT_PATH = Path(__file__).parent / "runner_payload_contract.json"

#: Runner-facing commands that must keep a stable JSON shape. These are the ones
#: documented as machine-readable entrypoints; adding a command here makes its
#: contract enforced from then on.
#: (name, argv, takes_workspace). `capabilities` describes the CLI itself and
#: has no --workspace option; the rest are workspace-scoped and get a clean
#: temp dir so the recorded shape does not depend on this repo's state.
CONTRACT_COMMANDS: tuple[tuple[str, tuple[str, ...], bool], ...] = (
    ("capabilities", ("capabilities", "--json"), False),
    ("next", ("next", "--json"), True),
    ("gate", ("gate", "--json"), True),
    ("status", ("status", "--json"), True),
    ("inspect", ("inspect", "--json"), True),
)


def _type_name(value: Any) -> str:
    """Describe a value's type, one level deep.

    One level is the useful depth: it catches "this became a string" and "this
    list became a dict" — the changes that break a consumer — without pinning
    every nested field and turning the snapshot into noise that gets regenerated
    reflexively.
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list):
        if not value:
            return "list[]"
        return f"list[{_type_name(value[0])}]"
    if isinstance(value, dict):
        return f"dict{{{','.join(sorted(value))}}}" if len(value) <= 12 else "dict"
    return type(value).__name__


def _shape(payload: dict[str, Any]) -> dict[str, str]:
    return {key: _type_name(value) for key, value in sorted(payload.items())}


def _run(args: tuple[str, ...], workspace: Path, takes_workspace: bool = True) -> dict[str, Any]:
    argv = [*args, "--workspace", str(workspace)] if takes_workspace else list(args)
    result = CliRunner().invoke(app, argv)
    assert result.exit_code == 0, f"{argv} exited {result.exit_code}: {result.output[:400]}"
    return json.loads(result.output)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """A clean workspace, so the shape does not depend on this repo's state."""
    (tmp_path / "README.md").write_text("# fixture\n", encoding="utf-8")
    return tmp_path


def _load_snapshot() -> dict[str, dict[str, str]]:
    if not SNAPSHOT_PATH.exists():
        return {}
    return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "name,args,takes_workspace", CONTRACT_COMMANDS, ids=[c[0] for c in CONTRACT_COMMANDS]
)
def test_payload_shape_matches_the_recorded_contract(
    name: str, args: tuple[str, ...], takes_workspace: bool, workspace: Path
) -> None:
    snapshot = _load_snapshot()
    assert name in snapshot, (
        f"no recorded contract for `agentx {name} --json`. "
        f"Regenerate with: uv run python scripts/update_payload_contract.py"
    )

    actual = _shape(_run(args, workspace, takes_workspace))
    expected = snapshot[name]

    added = sorted(set(actual) - set(expected))
    removed = sorted(set(expected) - set(actual))
    retyped = sorted(k for k in set(actual) & set(expected) if actual[k] != expected[k])

    problems = []
    if removed:
        problems.append(f"keys REMOVED (breaks consumers): {removed}")
    if retyped:
        problems.append(
            "keys CHANGED TYPE: " + ", ".join(f"{k}: {expected[k]} -> {actual[k]}" for k in retyped)
        )
    if added:
        problems.append(f"keys added: {added}")

    assert not problems, (
        f"`agentx {name} --json` changed its contract:\n  "
        + "\n  ".join(problems)
        + "\n\nIf intended, regenerate the snapshot in the same commit:\n"
        + "  uv run python scripts/update_payload_contract.py"
    )


@pytest.mark.parametrize(
    "name,args,takes_workspace", CONTRACT_COMMANDS, ids=[c[0] for c in CONTRACT_COMMANDS]
)
def test_every_payload_declares_a_schema(
    name: str, args: tuple[str, ...], takes_workspace: bool, workspace: Path
) -> None:
    """A runner keys off `schema` to know what it is holding."""
    payload = _run(args, workspace, takes_workspace)

    assert isinstance(payload.get("schema"), str)
    assert payload["schema"].startswith("agentx.")
    assert payload["schema"].split(".")[-1].startswith("v")


def test_snapshot_covers_exactly_the_contract_commands() -> None:
    """A command dropped from CONTRACT_COMMANDS would stop being checked without
    anything failing; a stale snapshot entry hides that."""
    snapshot = _load_snapshot()

    assert set(snapshot) == {name for name, _args, _ws in CONTRACT_COMMANDS}
