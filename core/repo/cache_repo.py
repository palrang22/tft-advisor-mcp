"""Phase 2 static JSON 또는 parquet 캐시를 읽는 오프라인 Repository.

인스턴스는 로드한 파일의 메모리 스냅샷이다. 세트 수치는 필요한 계산에서만 검증한다.
서빙 갱신 주기·BigQuery fallback은 Phase 6에서 처리한다.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import MappingProxyType
from typing import Any

import yaml
from pydantic import BaseModel, TypeAdapter, ValidationError

from common.config import ROOT_DIR
from core.errors import DataUnavailable, MissingSetData, UnknownName
from core.models import Alias, IdMapping, NameEntry, SetRules, StaticItem, StaticTrait, StaticUnit


class CacheRepo:
    def __init__(
        self, cache_dir: Path, set_number: int, sets_dir: Path = ROOT_DIR / "static" / "sets"
    ) -> None:
        self.set_number = set_number
        self._cache_dir = Path(cache_dir)
        self._set_path = Path(sets_dir) / f"set{set_number}.yaml"
        self._rules: SetRules | None = None
        self.units = MappingProxyType(self._entities("static_units", StaticUnit))
        self.items = MappingProxyType(self._entities("static_items", StaticItem))
        self.traits = MappingProxyType(self._entities("static_traits", StaticTrait))
        self.aliases = tuple(self._read("static_aliases", Alias))
        mappings = self._read("static_id_map", IdMapping)
        if len({m.opgg_id for m in mappings}) != len(mappings):
            raise DataUnavailable("static_id_map에 중복 OP.GG ID가 있다")
        self.id_map = MappingProxyType({m.opgg_id: m for m in mappings})
        for m in mappings:
            table = self.units if m.type == "unit" else self.items
            if m.api_name is not None and m.api_name not in table:
                raise DataUnavailable(f"static_id_map의 {m.opgg_id} 대상 {m.api_name}이 없다")
        self.names = self._name_entries()

    def _read[T: BaseModel](self, table: str, model: type[T]) -> list[T]:
        path = self._cache_dir / f"{table}.json"
        parquet = self._cache_dir / f"{table}.parquet"
        try:
            if path.is_file():
                raw = json.loads(path.read_text(encoding="utf-8"))
            elif parquet.is_file():
                import pandas as pd

                raw = json.loads(pd.read_parquet(parquet).to_json(orient="records"))
            else:
                raise DataUnavailable(f"캐시가 없다: {path} (또는 {parquet.name})")
            return TypeAdapter(list[model]).validate_python(raw)
        except (OSError, ValueError, ImportError) as exc:
            raise DataUnavailable(f"{table} 캐시를 읽을 수 없다: {exc}") from exc

    def _entities[T: StaticUnit | StaticItem | StaticTrait](
        self, table: str, model: type[T]
    ) -> dict[str, T]:
        rows = self._read(table, model)
        if any(r.set_number != self.set_number for r in rows):
            raise DataUnavailable(f"{table} 캐시의 세트가 요청한 Set {self.set_number}와 다르다")
        by_id = {r.api_name: r for r in rows}
        if len(by_id) != len(rows):
            raise DataUnavailable(f"{table}에 중복 api_name이 있다")
        return by_id

    def unit(self, identifier: str) -> StaticUnit:
        return self._entity(identifier, "unit", self.units)

    def item(self, identifier: str) -> StaticItem:
        return self._entity(identifier, "item", self.items)

    def _entity[T: StaticUnit | StaticItem](
        self, identifier: str, kind: str, table: MappingProxyType[str, T]
    ) -> T:
        mapping = self.id_map.get(identifier)
        if mapping is not None and mapping.type == kind:
            if mapping.api_name is None:
                raise DataUnavailable(
                    f"{mapping.name_ko or identifier}: 이름만 등록되어 코스트·시너지 정보가 없다"
                )
            return table[mapping.api_name]
        if identifier in table:
            return table[identifier]
        raise UnknownName(f"알 수 없는 {kind} ID: {identifier}")

    def _name_entries(self) -> tuple[NameEntry, ...]:
        entries: list[NameEntry] = []
        mapped: set[tuple[str, str]] = set()
        # 이름이 겹치는 legacy other 아이템보다 분류가 확인된 아이템을 우선한다.
        current_item_names = {
            item.name_ko for item in self.items.values() if item.kind != "other" and item.name_ko
        }
        for m in self.id_map.values():
            if m.name_ko:
                entries.append(
                    NameEntry(id=m.opgg_id, api_name=m.api_name, name_ko=m.name_ko, type=m.type)
                )
                if m.api_name is not None:
                    mapped.add((m.type, m.api_name))
        for kind, table in (("unit", self.units), ("item", self.items), ("trait", self.traits)):
            for row in table.values():
                if not row.name_ko or (kind, row.api_name) in mapped:
                    continue
                if (
                    isinstance(row, StaticItem)
                    and row.kind == "other"
                    and row.name_ko in current_item_names
                ):
                    continue
                entries.append(
                    NameEntry(
                        id=row.api_name, api_name=row.api_name, name_ko=row.name_ko, type=kind
                    )
                )
        return tuple(sorted(entries, key=lambda e: (e.type, e.name_ko, e.id)))

    def set_rules(self) -> SetRules:
        if self._rules is not None:
            return self._rules
        try:
            raw = yaml.safe_load(self._set_path.read_text(encoding="utf-8"))
            missing = _todo_paths(raw)
            if missing:
                raise MissingSetData(f"{self._set_path}: 채울 값 {', '.join(missing)}")
            rules = SetRules.model_validate(raw)
            if rules.set != self.set_number:
                raise MissingSetData(f"{self._set_path}: set 값이 {self.set_number}가 아니다")
        except (OSError, yaml.YAMLError, ValidationError) as exc:
            raise MissingSetData(f"{self._set_path}: 세트 수치를 읽을 수 없다: {exc}") from exc
        self._rules = rules
        return rules


def _todo_paths(value: Any, prefix: str = "") -> list[str]:
    if isinstance(value, str) and value.strip().upper() == "TODO":
        return [prefix]
    if isinstance(value, dict):
        return [p for key, child in value.items() for p in _todo_paths(child, f"{prefix}.{key}")]
    if isinstance(value, list):
        return [p for i, child in enumerate(value) for p in _todo_paths(child, f"{prefix}[{i}]")]
    return []
