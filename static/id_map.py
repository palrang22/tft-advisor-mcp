"""OP.GG enum ID ↔ CDragon apiName 매핑.

1. `rules/id_overrides.yaml`의 `ids`가 먼저 (값이 `TODO`면 아직 안 채운 것으로 본다).
2. 자동 매칭: CDragon 세트 데이터에 apiName이 **그대로** 있으면 매칭.
   문자열 패턴으로 추측하지 않는다.
3. 둘 다 안 되면 unmatched로 남겨 `data/cache/unmatched_ids.txt`에 쓴다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypedDict

import yaml

from static.cdragon import EmblemFailure

logger = logging.getLogger(__name__)

TODO = "TODO"


class IdMapRow(TypedDict):
    opgg_id: str
    api_name: str | None  # None: CDragon에 대응 항목이 없음 (override로 이름만 지정)
    type: str
    name_ko: str | None
    match_method: str


class Unmatched(TypedDict):
    opgg_id: str
    type: str


@dataclass(frozen=True)
class IdOverride:
    """`ids` 항목. 문자열이면 api_name만, 맵이면 `api_name`·`name_ko` 중 하나 이상."""

    api_name: str | None = None
    name_ko: str | None = None


@dataclass(frozen=True)
class Overrides:
    ids: dict[str, IdOverride] = field(default_factory=dict)
    emblem_traits: dict[str, str] = field(default_factory=dict)


def load_overrides(path: Path) -> Overrides:
    if not path.is_file():
        return Overrides()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    unknown = set(raw) - {"ids", "emblem_traits"}
    if unknown:
        raise ValueError(f"{path}: 알 수 없는 섹션 {sorted(unknown)}")
    ids = {
        key: _id_override(value, path, key)
        for key, value in _section(raw.get("ids"), path, "ids").items()
    }
    emblem_traits: dict[str, str] = {}
    for key, value in _section(raw.get("emblem_traits"), path, "emblem_traits").items():
        if not isinstance(value, str):
            raise ValueError(f"{path}: emblem_traits.{key} 값은 문자열이어야 한다")
        emblem_traits[key] = value
    return Overrides(ids=ids, emblem_traits=emblem_traits)


def _section(section: object, path: Path, name: str) -> dict[str, object]:
    """`키: 값` 맵에서 값이 비었거나 TODO인 항목(아직 안 채운 것)을 뺀다."""
    if section is None:
        return {}
    if not isinstance(section, dict):
        raise ValueError(f"{path}: {name}는 `키: 값` 맵이어야 한다")
    out: dict[str, object] = {}
    for key, value in section.items():
        if not isinstance(key, str):
            raise ValueError(f"{path}: {name}의 키 {key!r}는 문자열이어야 한다")
        if value is None or value == TODO:
            continue
        out[key] = value
    return out


def _id_override(value: object, path: Path, key: str) -> IdOverride:
    if isinstance(value, str):
        return IdOverride(api_name=value)
    if isinstance(value, dict):
        extra = set(value) - {"api_name", "name_ko"}
        api_name, name_ko = value.get("api_name"), value.get("name_ko")
        valid = all(v is None or isinstance(v, str) for v in (api_name, name_ko))
        if not extra and valid and (api_name or name_ko):
            return IdOverride(api_name=api_name, name_ko=name_ko)
    raise ValueError(
        f"{path}: ids.{key}는 apiName 문자열 또는 {{api_name, name_ko}} 맵(하나 이상)이어야 한다"
    )


def build_id_map(
    enums: dict[str, list[str]],
    names_by_type: dict[str, dict[str, str | None]],
    override_ids: dict[str, IdOverride],
) -> tuple[list[IdMapRow], list[Unmatched]]:
    """`enums`: type → OP.GG ID 목록, `names_by_type`: type → {CDragon apiName: name_ko}."""
    rows: list[IdMapRow] = []
    unmatched: list[Unmatched] = []
    seen: set[str] = set()
    for kind, opgg_ids in enums.items():
        names = names_by_type[kind]
        for opgg_id in opgg_ids:
            seen.add(opgg_id)
            override = override_ids.get(opgg_id)
            if override is not None:
                target = override.api_name
                if target is not None and target not in names:
                    raise ValueError(
                        f"id_overrides ids.{opgg_id}: CDragon 세트 {kind}에 {target}이 없다"
                    )
                name = override.name_ko or (names[target] if target else None)
                rows.append(_row(opgg_id, target, kind, name, "override"))
            elif opgg_id in names:
                rows.append(_row(opgg_id, opgg_id, kind, names[opgg_id], "auto"))
            else:
                unmatched.append(Unmatched(opgg_id=opgg_id, type=kind))
    stale = sorted(set(override_ids) - seen)
    if stale:
        logger.warning("OP.GG enum에 없는 id_overrides 항목: %s", stale)
    return rows, unmatched


def _row(
    opgg_id: str, api_name: str | None, kind: str, name_ko: str | None, method: str
) -> IdMapRow:
    return IdMapRow(
        opgg_id=opgg_id, api_name=api_name, type=kind, name_ko=name_ko, match_method=method
    )


def write_unmatched(
    path: Path,
    set_number: int,
    unmatched: list[Unmatched],
    emblem_failures: list[EmblemFailure],
) -> None:
    lines = [
        f"# static.loader --set {set_number} 매칭 실패 목록. rules/id_overrides.yaml에 채운다.",
        "",
        "# [ids] OP.GG ID → CDragon apiName (type)",
        *(f"{u['opgg_id']}\t{u['type']}" for u in unmatched),
        "",
        "# [emblem_traits] 상징 apiName → 세트 시너지 apiName (이름 규칙 실패)",
        *(f"{e['api_name']}\t{e['name_ko']}" for e in emblem_failures),
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
