from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class InfrastructureMap:
    key: str
    title: str
    path: Path
    section_headings: tuple[str, ...] = ()


def infrastructure_maps(home: Path | None = None) -> dict[str, InfrastructureMap]:
    root = (home or Path.home()) / "infrastructure"
    maps = {
        "quick": InfrastructureMap(
            key="quick",
            title="infrastructure-quick-ref",
            path=root / "infrastructure-quick-ref.md",
        ),
        "project": InfrastructureMap(
            key="project",
            title="project-map",
            path=root / "project-map.md",
        ),
        "resource": InfrastructureMap(
            key="resource",
            title="resource-map",
            path=root / "resource-map.md",
        ),
        "home": InfrastructureMap(
            key="home",
            title="home-ai-facilities-map",
            path=root / "resource-map.md",
            section_headings=("家庭 AI 中心",),
        ),
        "vps": InfrastructureMap(
            key="vps",
            title="vps-map",
            path=root / "resource-map.md",
            section_headings=("外網主機 / VPS", "VPS 對照"),
        ),
    }
    maps["all"] = InfrastructureMap(key="all", title="all infrastructure maps", path=root)
    return maps


MAP_ALIASES = {
    "home-ai": "home",
    "facility": "home",
    "facilities": "home",
}


PRIMARY_MAP_KEYS = ("quick", "project", "resource")


def _heading_level(line: str) -> int | None:
    stripped = line.lstrip()
    if not stripped.startswith("#"):
        return None
    hashes = len(stripped) - len(stripped.lstrip("#"))
    if hashes == 0 or hashes > 6 or not stripped[hashes:].startswith(" "):
        return None
    return hashes


def _heading_text(line: str) -> str:
    return line.lstrip("#").strip()


def _extract_markdown_section(content: str, headings: tuple[str, ...]) -> str | None:
    if not headings:
        return None

    lines = content.splitlines()
    wanted = tuple(heading.strip().lower() for heading in headings)
    start_index: int | None = None
    start_level: int | None = None

    for index, line in enumerate(lines):
        level = _heading_level(line)
        if level is None:
            continue
        heading = _heading_text(line).lower()
        if any(heading == item or heading.startswith(item) for item in wanted):
            start_index = index
            start_level = level
            break

    if start_index is None or start_level is None:
        return None

    end_index = len(lines)
    for index in range(start_index + 1, len(lines)):
        level = _heading_level(lines[index])
        if level is not None and level <= start_level:
            end_index = index
            break

    return "\n".join(lines[start_index:end_index]).strip()


def build_infrastructure_context(
    map_key: str = "all",
    *,
    home: Path | None = None,
    per_file_chars: int = 5000,
    max_chars: int = 14000,
) -> str:
    maps = infrastructure_maps(home)
    raw_key = (map_key or "all").strip().lower()
    key = MAP_ALIASES.get(raw_key, raw_key)
    if key not in maps:
        allowed = ", ".join(sorted([*maps, *MAP_ALIASES]))
        raise ValueError(f"unknown infrastructure map: {map_key}. Use one of: {allowed}")

    selected = [maps[item_key] for item_key in PRIMARY_MAP_KEYS] if key == "all" else [maps[key]]
    sections = [
        "Infrastructure maps are read-only references. For SSH/deploy/production actions, confirm runtime state and get explicit approval before acting.",
    ]
    if raw_key != key:
        sections.append(f"Map alias: {raw_key} -> {key}")
    for item in selected:
        if not item.path.is_file():
            sections.append(f"--- {item.title} ({item.path}) ---\n(missing)")
            continue
        raw_content = item.path.read_text(encoding="utf-8", errors="replace")
        if item.section_headings:
            extracted = _extract_markdown_section(raw_content, item.section_headings)
            content = extracted or f"(section missing: {', '.join(item.section_headings)})"
        else:
            content = raw_content
        content = content[:per_file_chars]
        sections.append(f"--- {item.title} ({item.path}) ---\n{content}")

    return "\n\n".join(sections)[:max_chars]
