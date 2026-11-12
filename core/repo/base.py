"""계산·추천 툴이 보는 데이터 접근 계약. OP.GG 호출·어댑터 의존성이 없다."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from core.models import Alias, IdMapping, NameEntry, SetRules, StaticItem, StaticTrait, StaticUnit


class Repository(Protocol):
    set_number: int
    units: Mapping[str, StaticUnit]
    items: Mapping[str, StaticItem]
    traits: Mapping[str, StaticTrait]
    aliases: tuple[Alias, ...]
    id_map: Mapping[str, IdMapping]
    names: tuple[NameEntry, ...]

    def unit(self, identifier: str) -> StaticUnit: ...

    def item(self, identifier: str) -> StaticItem: ...

    def set_rules(self) -> SetRules: ...
