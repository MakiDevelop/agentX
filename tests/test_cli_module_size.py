"""Keep cli.py shrinking, not growing.

At its peak cli.py was 10,761 lines — 46% of the entire source tree — holding
326 top-level functions, 52 Typer commands, and a `shell()` function with a
cyclomatic complexity of 160. Everything in it is therefore hard to test in
isolation, and `docs/CLI_DISPATCH_REFACTOR_HANDOFF.md` records a split that
stalled after four commands.

This is a ratchet, not a target. It exists because the failure mode is not "one
bad commit" — it is a hundred reasonable commits each adding thirty lines to the
file that was already the easiest place to put them.

To lower the limits: extract a *closed* group (one whose functions depend only
on each other and on imports, so the move cannot create a circular import back
into cli.py), re-export anything external callers use, and drop the numbers here
in the same commit.
"""

from __future__ import annotations

from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "agentx"

#: Measured after extracting cli_git, cli_output, cli_verify and cli_artifacts.
#: Only ever revise downward.
MAX_CLI_LINES = 10_900

#: No other module should become the new dumping ground. Set just above the
#: largest legitimate module (loop.py, 1,508 lines — the agent loop itself),
#: so it constrains growth without demanding an unrelated refactor today.
MAX_OTHER_MODULE_LINES = 1_600

#: Exempt from the general cap and governed by MAX_CLI_LINES instead.
KNOWN_LARGE_MODULES = {"cli.py"}


def _line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def test_cli_module_does_not_grow() -> None:
    actual = _line_count(SRC / "cli.py")

    assert actual <= MAX_CLI_LINES, (
        f"cli.py grew to {actual} lines (limit {MAX_CLI_LINES}). "
        "Put new code in a focused module instead, or extract a closed group "
        "and lower MAX_CLI_LINES in the same commit."
    )


def test_no_new_oversized_modules() -> None:
    oversized = {
        path.name: _line_count(path)
        for path in sorted(SRC.rglob("*.py"))
        if path.name not in KNOWN_LARGE_MODULES and _line_count(path) > MAX_OTHER_MODULE_LINES
    }

    assert not oversized, (
        f"module(s) over {MAX_OTHER_MODULE_LINES} lines: {oversized}. "
        "Splitting cli.py is pointless if the pieces become the same problem."
    )


EXTRACTED_MODULES = ("cli_git.py", "cli_output.py", "cli_verify.py", "cli_artifacts.py")


def test_extracted_git_module_stays_closed() -> None:
    """Extracted modules must not import back into cli.py.

    If that stops being true the module has to be re-entangled, and the next
    extraction loses its worked example.

    Checked by parsing imports rather than grepping the text — the first version
    of this test matched the phrase inside its own module docstring.
    """
    import ast

    for module in EXTRACTED_MODULES:
        tree = ast.parse((SRC / module).read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
            elif isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)

        assert "agentx.cli" not in imported, f"{module} imports back into cli.py"
