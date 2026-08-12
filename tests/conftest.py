"""Pin the environment that decides how output is *rendered*.

Sibling of `agentx.proc`, which pins the environment of subprocesses agentX
spawns. This file pins the environment of the process running the tests.

Both exist for the same reason: agentX asserts on human-facing text in a number
of places, and that text is not a stable contract — it varies with locale,
terminal width, and colour support. When those inputs are ambient, a test can be
green on one machine and red on another for reasons that have nothing to do with
the code.

Two concrete failures this prevents, both found when CI ran the suite for the
first time after the lockfile gate was fixed (2026-08):

1. `git_status_payload` returned ``尚無提交在 master`` under a zh_TW locale.
   Fixed properly in `agentx.proc`; the locale pinning here keeps the *test*
   process consistent with the subprocesses it inspects.

2. Five `test_headless_exit_codes` cases asserted on Typer/Click parameter
   errors. GitHub runners set no ``COLUMNS`` and Rich detected colour support,
   so the error panel was rendered as a coloured, width-truncated box::

       Try 'root -...   │
       ╰────────────────╯

   The expected message was still "in" the panel visually, but chopped by an
   ellipsis, so the substring assertion failed. Locally the terminal was wider
   and uncoloured, so it passed. Reproducible with ``FORCE_COLOR=1 COLUMNS=80``.

Anything that genuinely needs a narrow or coloured terminal should set it
explicitly inside that test, via monkeypatch, rather than relying on ambient
state.
"""

from __future__ import annotations

import pytest

#: Applied to every test. Values are chosen to be wide and boring:
#: - NO_COLOR / TERM: Rich emits plain text, so no ANSI codes land in
#:   `result.output` and no colour-aware truncation happens.
#: - COLUMNS: wide enough that Click/Rich never wraps a one-line error message.
#: - LC_ALL / LANG / LANGUAGE: untranslated tool output (see agentx.proc).
DETERMINISTIC_OUTPUT_ENV = {
    "NO_COLOR": "1",
    "TERM": "dumb",
    "COLUMNS": "200",
    "LINES": "50",
    "LC_ALL": "C",
    "LANG": "C",
    "LANGUAGE": "",
}


@pytest.fixture(autouse=True)
def _deterministic_output_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make rendered output independent of the machine running the tests."""
    for key, value in DETERMINISTIC_OUTPUT_ENV.items():
        monkeypatch.setenv(key, value)
    # Click reads this to decide whether to emit colour at all; belt to
    # NO_COLOR's braces, since FORCE_COLOR in the ambient env would win otherwise.
    monkeypatch.delenv("FORCE_COLOR", raising=False)
