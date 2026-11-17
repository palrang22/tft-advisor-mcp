"""스냅샷 호출 목록.

챔피언·아이템 ID는 `list_tools()` enum에서, 아이템 분류는 조합식 응답의 `category`에서 읽는다.
ID를 코드에 적거나 문자열 패턴으로 분류하지 않는다.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from snapshot.store import ITEM_COMBINATIONS, response_file
from static.opgg_ref import ENUM_SOURCES, read_enums

META_DECKS = "tft_list_meta_decks"
AUGMENTS = "tft_list_augments"

# 템별 챔피언을 받을 분류. 찬란한 템(radiant)과 조합식에 없는 것(포션 등)은 받지 않는다.
SNAPSHOT_ITEM_KINDS = frozenset({"emblem", "component", "completed", "artifact"})


@dataclass(frozen=True)
class Call:
    tool: str
    args: Mapping[str, str] = field(default_factory=dict)  # `client_app` 제외, 최대 1개

    @property
    def file(self) -> str:
        return response_file(self.tool, next(iter(self.args.values()), None))


def fixed_calls() -> list[Call]:
    """인자가 ID가 아닌 호출: 조합식, 증강."""
    combinations, lang = ITEM_COMBINATIONS
    return [Call(combinations, {"lang": lang}), Call(AUGMENTS, {"lang": lang})]


def enum_calls(list_tools: dict[str, Any], item_kinds: Mapping[str, str]) -> list[Call]:
    """챔피언 빌드(enum 전체) + 템별 챔피언(`SNAPSHOT_ITEM_KINDS`에 드는 아이템)."""
    enums = read_enums(list_tools)
    unit_tool, unit_arg = ENUM_SOURCES["unit"]
    item_tool, item_arg = ENUM_SOURCES["item"]
    return [
        *(Call(unit_tool, {unit_arg: unit_id}) for unit_id in enums["unit"]),
        *(
            Call(item_tool, {item_arg: item_id})
            for item_id in enums["item"]
            if item_kinds.get(item_id) in SNAPSHOT_ITEM_KINDS
        ),
    ]
