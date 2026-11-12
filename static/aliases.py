"""`rules/aliases.yaml` → `static_aliases` 행.

형식: 섹션(`units` / `items` / `traits`) 아래 `줄임말: 정식 한국어 이름`.
"""

from __future__ import annotations

from pathlib import Path
from typing import TypedDict

import yaml

TYPE_BY_SECTION: dict[str, str] = {"units": "unit", "items": "item", "traits": "trait"}


class AliasRow(TypedDict):
    alias: str
    canonical_name_ko: str
    type: str


def load_aliases(path: Path) -> list[AliasRow]:
    if not path.is_file():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    unknown = set(raw) - set(TYPE_BY_SECTION)
    if unknown:
        raise ValueError(f"{path}: 알 수 없는 섹션 {sorted(unknown)}")
    rows: list[AliasRow] = []
    for section, kind in TYPE_BY_SECTION.items():
        entries = raw.get(section) or {}
        if not isinstance(entries, dict):
            raise ValueError(f"{path}: {section}는 `줄임말: 이름` 맵이어야 한다")
        for alias, canonical in entries.items():
            if not isinstance(canonical, str) or not canonical:
                raise ValueError(f"{path}: {section}.{alias} 값이 비어 있거나 문자열이 아니다")
            rows.append(AliasRow(alias=str(alias), canonical_name_ko=canonical, type=kind))
    return rows


def unknown_canonicals(rows: list[AliasRow], names_by_type: dict[str, set[str]]) -> list[AliasRow]:
    """정식 이름이 static 데이터에 없는 줄임말 (오타 확인용)."""
    return [r for r in rows if r["canonical_name_ko"] not in names_by_type[r["type"]]]
