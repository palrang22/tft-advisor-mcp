"""CommunityDragon `ko_kr.json` → static 행.

구조 (2026-11-12 확인):
- `setData[]`: 세트·모드별 항목. 현재 세트 본편은 `number == N`이고 `mutator == "TFTSet{N}"`인 항목.
  `champions[]`, `traits[]`, `items`(apiName 목록), `augments`(apiName 목록)를 가진다.
- `items[]`: 모든 세트의 아이템·증강 상세. 세트 항목의 apiName 목록으로 골라낸다.
- 챔피언의 `traits`는 시너지 apiName이 아니라 한국어 이름이다.
  같은 세트 `traits[]`의 이름으로 apiName을 찾는다.
"""

from __future__ import annotations

import logging
from typing import Any, TypedDict

import httpx

from common.retry import RetryPolicy, retry_call

logger = logging.getLogger(__name__)

POLICY = RetryPolicy(timeout=120.0, attempts=4, base_delay=2.0, max_delay=30.0)

EMBLEM_SUFFIX = " 상징"


class UnitRow(TypedDict):
    set_number: int
    api_name: str
    name_ko: str | None
    cost: int
    traits: list[str]
    role: str | None


class TraitRow(TypedDict):
    set_number: int
    api_name: str
    name_ko: str | None
    breakpoints: list[int]
    desc_ko: str | None


class ItemRow(TypedDict):
    set_number: int
    api_name: str
    name_ko: str | None
    components: list[str]
    kind: str
    emblem_trait: str | None


class AugmentRow(TypedDict):
    set_number: int
    api_name: str
    name_ko: str | None
    desc_ko: str | None


class EmblemFailure(TypedDict):
    api_name: str
    name_ko: str | None


def fetch(url: str, policy: RetryPolicy = POLICY) -> dict[str, Any]:
    def once(timeout: float) -> dict[str, Any]:
        resp = httpx.get(url, timeout=timeout, follow_redirects=True)
        resp.raise_for_status()
        return resp.json()

    return retry_call(
        once,
        retry_on=(httpx.TransportError, httpx.HTTPStatusError),
        policy=policy,
        name="cdragon fetch",
    )


def select_set(cdragon: dict[str, Any], set_number: int) -> dict[str, Any]:
    mutator = f"TFTSet{set_number}"
    found = [
        s
        for s in cdragon["setData"]
        if s.get("number") == set_number and s.get("mutator") == mutator
    ]
    if len(found) != 1:
        raise ValueError(f"CDragon setData에서 {mutator} 항목을 1개 찾지 못했다 ({len(found)}개)")
    return found[0]


def build_traits(set_data: dict[str, Any], set_number: int) -> list[TraitRow]:
    """`breakpoints` = `effects[].minUnits`. minUnits가 null인 단계는 빼고 경고한다."""
    rows: list[TraitRow] = []
    for t in set_data["traits"]:
        mins = [e.get("minUnits") for e in t.get("effects", [])]
        if None in mins:
            logger.warning("%s(%s): minUnits가 null인 단계 제외", t["apiName"], t.get("name"))
        rows.append(
            TraitRow(
                set_number=set_number,
                api_name=t["apiName"],
                name_ko=t.get("name"),
                breakpoints=[m for m in mins if m is not None],
                desc_ko=t.get("desc"),
            )
        )
    return rows


def trait_ids_by_name(set_data: dict[str, Any]) -> dict[str, str]:
    by_name: dict[str, str] = {}
    for t in set_data["traits"]:
        name = t.get("name")
        if not name:
            continue
        if name in by_name:
            raise ValueError(f"시너지 이름 중복: {name} ({by_name[name]}, {t['apiName']})")
        by_name[name] = t["apiName"]
    return by_name


def build_units(set_data: dict[str, Any], set_number: int) -> list[UnitRow]:
    by_name = trait_ids_by_name(set_data)
    rows: list[UnitRow] = []
    for c in set_data["champions"]:
        unknown = [n for n in c.get("traits", []) if n not in by_name]
        if unknown:
            raise ValueError(f"{c['apiName']}: 세트 시너지 목록에 없는 시너지 이름 {unknown}")
        rows.append(
            UnitRow(
                set_number=set_number,
                api_name=c["apiName"],
                name_ko=c.get("name"),
                cost=c["cost"],
                traits=[by_name[n] for n in c.get("traits", [])],
                role=c.get("role"),
            )
        )
    return rows


def _details(cdragon: dict[str, Any], api_names: list[str], what: str) -> list[dict[str, Any]]:
    by_api = {it["apiName"]: it for it in cdragon["items"]}
    missing = [a for a in api_names if a not in by_api]
    if missing:
        raise ValueError(f"CDragon items[]에 없는 세트 {what}: {missing[:10]}")
    return [by_api[a] for a in api_names]


def build_items(
    cdragon: dict[str, Any],
    set_data: dict[str, Any],
    set_number: int,
    kinds: dict[str, str],
    emblem_overrides: dict[str, str],
) -> tuple[list[ItemRow], list[EmblemFailure]]:
    """세트 아이템 행과 상징 → 시너지 매칭 실패 목록.

    - `kinds`: apiName → kind (OP.GG 조합식 `category`에서 만든 것). 없으면 `other`.
    - 상징 시너지: `emblem_overrides`가 먼저, 없으면 이름에서 " 상징"을 뗀 값 = 세트 시너지 이름.
    """
    by_name = trait_ids_by_name(set_data)
    trait_ids = set(by_name.values())
    rows: list[ItemRow] = []
    failures: list[EmblemFailure] = []
    for it in _details(cdragon, set_data["items"], "아이템"):
        api, name = it["apiName"], it.get("name")
        kind = kinds.get(api, "other")
        emblem_trait: str | None = None
        if kind == "emblem":
            if api in emblem_overrides:
                emblem_trait = emblem_overrides[api]
                if emblem_trait not in trait_ids:
                    raise ValueError(f"emblem_traits.{api}: 세트 시너지가 아니다 ({emblem_trait})")
            elif name and name.endswith(EMBLEM_SUFFIX):
                emblem_trait = by_name.get(name.removesuffix(EMBLEM_SUFFIX))
            if emblem_trait is None:
                failures.append(EmblemFailure(api_name=api, name_ko=name))
        rows.append(
            ItemRow(
                set_number=set_number,
                api_name=api,
                name_ko=name,
                components=list(it.get("composition") or []),
                kind=kind,
                emblem_trait=emblem_trait,
            )
        )
    return rows, failures


def build_augments(
    cdragon: dict[str, Any], set_data: dict[str, Any], set_number: int
) -> list[AugmentRow]:
    return [
        AugmentRow(
            set_number=set_number,
            api_name=a["apiName"],
            name_ko=a.get("name"),
            desc_ko=a.get("desc"),
        )
        for a in _details(cdragon, set_data["augments"], "증강")
    ]
