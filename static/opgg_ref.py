"""스냅샷이 저장한 OP.GG 기준 데이터 읽기 (OP.GG를 직접 부르지 않는다).

- `list_tools.json` → 챔피언·아이템 ID enum
- `tft_list_item_combinations__ko_KR.json` → 아이템 kind (`category`)
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# id_map type → (OP.GG 툴, enum이 있는 인자)
ENUM_SOURCES: dict[str, tuple[str, str]] = {
    "unit": ("tft_get_champion_item_build", "champion_id"),
    "item": ("tft_list_champions_for_item", "item_id"),
}

# OP.GG 조합식 category → static_items.kind
KIND_BY_CATEGORY: dict[str, str] = {
    "component": "component",
    "core": "completed",
    "emblem": "emblem",
    "artifact": "artifact",
    "radiant": "radiant",
}


def read_enums(list_tools: dict[str, Any]) -> dict[str, list[str]]:
    tools = {t["name"]: t for t in list_tools["tools"]}
    enums: dict[str, list[str]] = {}
    for kind, (tool, prop) in ENUM_SOURCES.items():
        if tool not in tools:
            raise ValueError(f"list_tools에 {tool}이 없다")
        schema = tools[tool]["inputSchema"]["properties"][prop]
        if "enum" not in schema:
            raise ValueError(f"{tool}.{prop}에 enum이 없다")
        enums[kind] = list(schema["enum"])
    return enums


def read_item_kinds(combinations: dict[str, Any], set_number: int) -> dict[str, str]:
    """apiName → kind. 매핑에 없는 category(또는 null)는 넣지 않는다 (= other)."""
    if combinations.get("set") != set_number:
        raise ValueError(
            f"조합식 스냅샷의 set={combinations.get('set')}가 요청한 세트 {set_number}와 다르다"
        )
    kinds: dict[str, str] = {}
    unknown: set[str] = set()
    for row in combinations["data"]:
        category = row.get("category")
        if category in KIND_BY_CATEGORY:
            kinds[row["apiName"]] = KIND_BY_CATEGORY[category]
        elif category is not None:
            unknown.add(category)
    if unknown:
        logger.warning("kind로 옮기지 않은 OP.GG category (other로 처리): %s", sorted(unknown))
    return kinds
