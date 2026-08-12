"""Deterministic subprocess environment for external tools.

agentX reads meaning out of the stdout of external tools — above all git. Those
tools translate their human-facing output, so the same command produces
different text depending on the operator's locale::

    $ git status --short --branch          # LANG=en_US
    ## No commits yet on master
    $ git status --short --branch          # LANG=zh_TW
    ## 尚無提交在 master

Any parser written against the English form silently mis-reads the other. This
is not hypothetical: `git_status_payload` reported the branch of a fresh repo as
``尚無提交在 master`` on a zh_TW machine, and CI never caught it because GitHub
runners are always English.

Every subprocess whose *output we parse* must therefore run under a pinned,
non-localized environment. That is what `stable_env` / `run` provide, and why
they exist as one helper instead of 29 hand-written ``env=`` arguments.

Note the separate, complementary rule: for git specifically, prefer plumbing
(`--porcelain`) over porcelain (`--short`) wherever a machine reads the result.
`--porcelain` is contractually stable *and* untranslated; the env pinning here
is the belt to that suspenders, and covers the commands that have no plumbing
form.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

#: Environment overrides applied to every managed subprocess.
#:
#: - ``LC_ALL`` / ``LANG`` / ``LANGUAGE``: force the C locale so tool output is
#:   untranslated. ``LANGUAGE`` must be cleared explicitly — GNU gettext honours
#:   it *over* ``LC_ALL``, so setting ``LC_ALL=C`` alone is not sufficient.
#: - ``GIT_OPTIONAL_LOCKS=0``: read-only git commands must not take the index
#:   lock. Affects only optional locks, never ones git actually requires, so it
#:   is safe to apply uniformly and keeps concurrent agent runs from colliding.
STABLE_ENV_OVERRIDES: dict[str, str] = {
    "LC_ALL": "C",
    "LANG": "C",
    "LANGUAGE": "",
    "GIT_OPTIONAL_LOCKS": "0",
}


def stable_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Return ``os.environ`` with the deterministic overrides applied.

    The parent environment is inherited so PATH, credential helpers, proxy
    settings and friends keep working; only the variables that make output
    non-deterministic are pinned.
    """
    env = dict(os.environ)
    env.update(STABLE_ENV_OVERRIDES)
    if extra:
        env.update(extra)
    return env


def run_process(
    argv: list[str],
    *,
    cwd: Path | str | None = None,
    timeout: float | None = None,
    check: bool = False,
    env: dict[str, str] | None = None,
    **kwargs: Any,
) -> subprocess.CompletedProcess[str]:
    """`subprocess.run` with text mode, captured output and a pinned locale.

    `env` is merged *on top of* the stable overrides, so a caller can add
    variables without accidentally dropping the locale pinning.

    Optional arguments left at their default are *not* forwarded. Passing
    ``cwd=None`` explicitly is equivalent to omitting it for `subprocess.run`,
    but it is not equivalent for test doubles that patch `subprocess.run` with a
    narrower signature — so this wrapper stays as close to a plain call as it can.
    """
    kwargs.setdefault("text", True)
    kwargs.setdefault("capture_output", True)
    if cwd is not None:
        kwargs["cwd"] = cwd
    if timeout is not None:
        kwargs["timeout"] = timeout
    return subprocess.run(
        argv,
        check=check,
        env=stable_env(env),
        **kwargs,
    )
