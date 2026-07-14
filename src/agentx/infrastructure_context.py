from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class InfrastructureMap:
    key: str
    title: str
    path: Path


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
    }
    maps["all"] = InfrastructureMap(key="all", title="all infrastructure maps", path=root)
    return maps


MAP_ALIASES = {
    "home": "quick",
    "home-ai": "quick",
    "facility": "quick",
    "facilities": "quick",
    "vps": "quick",
}


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

    selected = [item for item in maps.values() if item.key != "all"] if key == "all" else [maps[key]]
    sections = [
        "Infrastructure maps are read-only references. For SSH/deploy/production actions, confirm runtime state and get explicit approval before acting.",
    ]
    if raw_key != key:
        sections.append(f"Map alias: {raw_key} -> {key}")
    for item in selected:
        if not item.path.is_file():
            sections.append(f"--- {item.title} ({item.path}) ---\n(missing)")
            continue
        content = item.path.read_text(encoding="utf-8", errors="replace")[:per_file_chars]
        sections.append(f"--- {item.title} ({item.path}) ---\n{content}")

    return "\n\n".join(sections)[:max_chars]
