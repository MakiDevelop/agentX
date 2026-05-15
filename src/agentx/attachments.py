from __future__ import annotations

import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader


SENSITIVE_PARTS = {".ssh", ".gnupg", ".secrets"}
TEXT_EXTENSIONS = {
    ".cfg",
    ".css",
    ".csv",
    ".env",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".log",
    ".md",
    ".py",
    ".rs",
    ".sh",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff", ".tif"}


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
        content = _read_attachment(path)
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


def _read_attachment(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _read_pdf(path)
    if suffix in IMAGE_EXTENSIONS:
        return _read_image(path)
    if suffix in TEXT_EXTENSIONS or _looks_textual(path):
        return path.read_text(encoding="utf-8", errors="replace")
    return f"[binary file: {path.name}, size={path.stat().st_size} bytes]"


def _read_pdf(path: Path) -> str:
    reader = PdfReader(str(path))
    pages: list[str] = []
    for index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if text.strip():
            pages.append(f"[page {index}]\n{text.strip()}")
    content = "\n\n".join(pages).strip()
    return content or f"[pdf file: {path.name}, pages={len(reader.pages)}, no extractable text]"


def _read_image(path: Path) -> str:
    metadata = [f"[image file: {path.name}, size={path.stat().st_size} bytes]"]
    dimensions = _image_dimensions(path)
    if dimensions:
        metadata.append(f"dimensions={dimensions[0]}x{dimensions[1]}")
    ocr = _try_tesseract(path)
    if ocr:
        metadata.append("OCR:")
        metadata.append(ocr)
    else:
        metadata.append("OCR unavailable; install tesseract to extract image text locally.")
    return "\n".join(metadata)


def _try_tesseract(path: Path) -> str:
    if shutil.which("tesseract") is None:
        return ""
    completed = subprocess.run(
        ["tesseract", str(path), "stdout", "-l", "eng+chi_tra"],
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def _looks_textual(path: Path) -> bool:
    try:
        chunk = path.read_bytes()[:2048]
    except OSError:
        return False
    if b"\0" in chunk:
        return False
    return True


def _image_dimensions(path: Path) -> tuple[int, int] | None:
    data = path.read_bytes()[:4096]
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    if data.startswith(b"\xff\xd8"):
        return _jpeg_dimensions(data)
    return None


def _jpeg_dimensions(data: bytes) -> tuple[int, int] | None:
    index = 2
    while index + 9 < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        index += 2
        if marker in {0xD8, 0xD9}:
            continue
        if index + 2 > len(data):
            return None
        length = int.from_bytes(data[index : index + 2], "big")
        if marker in {0xC0, 0xC1, 0xC2, 0xC3} and index + 7 < len(data):
            height = int.from_bytes(data[index + 3 : index + 5], "big")
            width = int.from_bytes(data[index + 5 : index + 7], "big")
            return width, height
        index += length
    return None
