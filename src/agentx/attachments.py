from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path


SENSITIVE_PARTS = {".ssh", ".gnupg", ".secrets"}


@dataclass(frozen=True)
class Attachment:
    path: Path
    content: str
    truncated: bool


def extract_file_paths(text: str, workspace: Path, *, limit: int = 5) -> list[Path]:
    paths: list[Path] = []
    for token in _shell_tokens(text):
        candidate = _clean_token(token)
        if not candidate:
            continue
        if candidate.startswith("@"):
            candidate = candidate[1:]
        if not _looks_like_path(candidate) and not (workspace / candidate).is_file():
            continue
        path = Path(candidate).expanduser()
        if not path.is_absolute():
            path = (workspace / path).resolve()
        else:
            path = path.resolve()
        if path.is_file() and not _is_sensitive(path) and path not in paths:
            paths.append(path)
        if len(paths) >= limit:
            break
    return paths


def read_attachments(paths: list[Path], *, max_chars_per_file: int = 20000) -> list[Attachment]:
    attachments: list[Attachment] = []
    for path in paths:
        if _is_sensitive(path):
            continue
        content = path.read_text(encoding="utf-8", errors="replace")
        truncated = len(content) > max_chars_per_file
        attachments.append(
            Attachment(
                path=path,
                content=content[:max_chars_per_file],
                truncated=truncated,
            )
        )
    return attachments


def format_attachment_context(attachments: list[Attachment]) -> str:
    if not attachments:
        return ""
    parts = ["Attached file context:"]
    for attachment in attachments:
        suffix = "\n[truncated]" if attachment.truncated else ""
        parts.append(f"\n--- {attachment.path} ---\n{attachment.content}{suffix}")
    return "\n".join(parts)


def _shell_tokens(text: str) -> list[str]:
    try:
        return shlex.split(text)
    except ValueError:
        return text.split()


def _clean_token(token: str) -> str:
    return token.strip().strip("\u202a\u202c").strip(",，。:：;；)")


def _looks_like_path(token: str) -> bool:
    return token.startswith(("/", "~/", "./", "../", "@/", "@~/", "@./", "@../"))


def _is_sensitive(path: Path) -> bool:
    return any(part in SENSITIVE_PARTS for part in path.parts)
