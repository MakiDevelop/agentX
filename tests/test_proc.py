"""Guards for the pinned subprocess environment.

Regression origin: `git_status_payload` reported a fresh repo's branch as
``尚無提交在 master`` on a zh_TW machine, because the parser matched the English
string "No commits yet on ". GitHub runners are always English, so CI could
never reproduce it. These tests force a translated locale explicitly.
"""

from __future__ import annotations

import ast
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from agentx.bootstrap import _git_status
from agentx.cli import git_status_payload
from agentx.git_workflow import build_commit_plan
from agentx.proc import STABLE_ENV_OVERRIDES, run_process, stable_env

SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "agentx"

#: Call sites allowed to use raw `subprocess.run`. Everything else must route
#: through `agentx.proc.run_process` so the locale stays pinned.
RAW_SUBPROCESS_ALLOWLIST = {
    # Passthrough exec: streams the resumed command straight to the user's
    # terminal (no capture_output). Nothing parses it, and pinning LC_ALL=C
    # would strip translations from output a human is meant to read.
    ("cli.py", "handoff_resume"),
    # The wrapper itself.
    ("proc.py", "run_process"),
}


def _translated_locale() -> str | None:
    """Pick an installed non-English locale, or None if the box has none."""
    for candidate in ("zh_TW.UTF-8", "zh_CN.UTF-8", "ja_JP.UTF-8", "fr_FR.UTF-8", "de_DE.UTF-8"):
        probe = subprocess.run(
            ["locale", "-a"], capture_output=True, text=True, check=False, timeout=10
        )
        available = {line.strip().lower() for line in probe.stdout.splitlines()}
        if candidate.lower() in available or candidate.replace("-", "").lower() in available:
            return candidate
    return None


def _git_init(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True, text=True)


# --- The environment itself --------------------------------------------------


def test_stable_env_pins_locale_and_clears_language() -> None:
    env = stable_env()

    assert env["LC_ALL"] == "C"
    assert env["LANG"] == "C"
    # GNU gettext honours LANGUAGE over LC_ALL, so it must be cleared, not just
    # overridden — otherwise LC_ALL=C alone still yields translated output.
    assert env["LANGUAGE"] == ""
    assert env["GIT_OPTIONAL_LOCKS"] == "0"


def test_stable_env_inherits_parent_environment() -> None:
    env = stable_env()

    assert env.get("PATH") == os.environ.get("PATH")


def test_stable_env_extra_cannot_silently_drop_pinning() -> None:
    env = stable_env({"MY_VAR": "1"})

    assert env["MY_VAR"] == "1"
    assert env["LC_ALL"] == "C"


def test_run_process_applies_overrides_to_the_child() -> None:
    result = run_process(["/usr/bin/env"])

    assert result.returncode == 0
    assert "LC_ALL=C" in result.stdout


def test_run_process_defaults_to_captured_text_output() -> None:
    result = run_process(["echo", "hi"])

    assert result.stdout == "hi\n"
    assert isinstance(result.stdout, str)


# --- The actual regression ---------------------------------------------------


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_git_status_payload_is_locale_independent(tmp_path: Path, monkeypatch) -> None:
    """The original bug, reproduced by forcing a translated locale."""
    locale = _translated_locale()
    if locale is None:
        pytest.skip("no translated locale installed on this machine")

    _git_init(tmp_path)
    (tmp_path / "note.txt").write_text("draft\n", encoding="utf-8")
    for var in ("LC_ALL", "LANG", "LANGUAGE"):
        monkeypatch.setenv(var, locale)

    payload = git_status_payload(tmp_path)

    assert payload["ok"] is True
    assert payload["branch"] in {"main", "master"}, payload["branch"]
    assert payload["initial"] is True
    assert payload["dirty"] is True
    assert payload["changes"] == ["?? note.txt"]


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_bootstrap_git_status_is_locale_independent(tmp_path: Path, monkeypatch) -> None:
    locale = _translated_locale()
    if locale is None:
        pytest.skip("no translated locale installed on this machine")

    _git_init(tmp_path)
    for var in ("LC_ALL", "LANG", "LANGUAGE"):
        monkeypatch.setenv(var, locale)

    text = _git_status(tmp_path)

    assert "## No commits yet on" in text


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_commit_plan_parses_files_under_translated_locale(tmp_path: Path, monkeypatch) -> None:
    _git_init(tmp_path)
    (tmp_path / "a.txt").write_text("x\n", encoding="utf-8")
    locale = _translated_locale()
    if locale is None:
        pytest.skip("no translated locale installed on this machine")
    for var in ("LC_ALL", "LANG", "LANGUAGE"):
        monkeypatch.setenv(var, locale)

    plan = build_commit_plan(tmp_path)

    assert plan.files == ["a.txt"]


# --- Structural guard: no new unpinned call sites ----------------------------


def _enclosing_function(tree: ast.Module, lineno: int) -> str:
    best = "<module>"
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.lineno <= lineno <= (
            node.end_lineno or node.lineno
        ):
            best = node.name
    return best


def test_no_unpinned_subprocess_calls_in_src() -> None:
    """Fail if someone reintroduces a raw subprocess.run outside the allowlist.

    Without this, the fix decays: the next `subprocess.run(["git", ...])` added
    anywhere in src/ silently reintroduces locale-dependent parsing.
    """
    offenders: list[str] = []
    for path in sorted(SRC_ROOT.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if ast.unparse(node.func) not in {
                "subprocess.run",
                "subprocess.check_output",
                "subprocess.Popen",
            }:
                continue
            key = (path.name, _enclosing_function(tree, node.lineno))
            if key in RAW_SUBPROCESS_ALLOWLIST:
                continue
            offenders.append(
                f"{path.relative_to(SRC_ROOT.parent.parent)}:{node.lineno} in {key[1]}"
            )

    assert not offenders, (
        "raw subprocess calls must use agentx.proc.run_process so the locale stays pinned:\n  "
        + "\n  ".join(offenders)
    )


def test_stable_env_overrides_is_not_accidentally_emptied() -> None:
    assert set(STABLE_ENV_OVERRIDES) >= {"LC_ALL", "LANG", "LANGUAGE", "GIT_OPTIONAL_LOCKS"}
