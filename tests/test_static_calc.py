"""resolve_names · craft_options · calc_traits 동작 테스트.

손으로 검산할 수 있는 작은 static 테이블을 임시 디렉터리에 JSON으로 쓰고 실제 `CacheRepo`로 읽는다.
이름·ID는 전부 이 파일 안에서 만든 가짜 값이다 (실제 세트 데이터가 아니다).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from core.calc.calc_traits import calc_traits
from core.calc.craft_options import craft_options
from core.calc.resolve_names import resolve_names
from core.envelope import Envelope
from core.errors import DataUnavailable, InvalidInput, UnknownName
from core.models import (
    CalcTraitsInput,
    CalcTraitsResult,
    CraftOptionsInput,
    CraftOptionsResult,
    ResolveNamesInput,
    ResolveNamesResult,
)
from core.repo.cache_repo import CacheRepo

SET = 18


def unit(api: str, name: str | None, cost: int, *traits: str) -> dict[str, Any]:
    return {
        "set_number": SET,
        "api_name": api,
        "name_ko": name,
        "cost": cost,
        "traits": list(traits),
        "role": None,
    }


def trait(api: str, name: str, *breakpoints: int) -> dict[str, Any]:
    return {
        "set_number": SET,
        "api_name": api,
        "name_ko": name,
        "breakpoints": list(breakpoints),
        "desc_ko": None,
    }


def item(
    api: str, name: str, kind: str, *components: str, emblem_trait: str | None = None
) -> dict[str, Any]:
    return {
        "set_number": SET,
        "api_name": api,
        "name_ko": name,
        "components": list(components),
        "kind": kind,
        "emblem_trait": emblem_trait,
    }


def mapping(
    opgg_id: str, api: str | None, kind: str, name: str | None, method: str
) -> dict[str, Any]:
    return {
        "opgg_id": opgg_id,
        "api_name": api,
        "type": kind,
        "name_ko": name,
        "match_method": method,
    }


def alias(word: str, canonical: str, kind: str) -> dict[str, Any]:
    return {"alias": word, "canonical_name_ko": canonical, "type": kind}


BRUISER, MAGE, ECLIPSE = "TFT18_Bruiser", "TFT18_Mage", "TFT18_Eclipse"
SWORD, ROD, SPATULA, PAN = "TFT_Item_Sword", "TFT_Item_Rod", "TFT_Item_Spatula", "TFT_Item_Pan"

_UNITS = [
    unit("TFT18_Garen", "가렌", 1, BRUISER, MAGE),
    unit("TFT18_Gnar", "나르", 2, BRUISER),
    unit("TFT18_Nami", "나미", 1, MAGE),
    unit("TFT18_Darius", "다리우스", 3, BRUISER),
    unit("TFT18_Zed", "제드", 4, BRUISER),
    unit("TFT18_Ornn", "오른", 2, BRUISER),
    unit("TFT18_Sion", "사이온", 1, BRUISER),
    unit("TFT18_Gromp_AP", "심술두꺼비", 2, MAGE),
    unit("TFT18_Moon", "달맞이", 5, ECLIPSE),
]

TABLES: dict[str, list[dict[str, Any]]] = {
    "static_traits": [
        trait(BRUISER, "브루저", 2, 4, 6),
        trait(MAGE, "마법사", 2, 4),
        trait(ECLIPSE, "일식"),  # 단계 정보 없음
    ],
    "static_units": _UNITS,
    "static_items": [
        item(SWORD, "대검", "component"),
        item(ROD, "지팡이", "component"),
        item(SPATULA, "뒤집개", "component"),
        item(PAN, "프라이팬", "component"),
        item("TFT_Item_SwordSword", "쌍대검", "completed", SWORD, SWORD),
        item("TFT_Item_SwordRod", "검지팡", "completed", SWORD, ROD),
        item(
            "TFT_Item_BruiserEmblem", "브루저 상징", "emblem", SPATULA, SWORD, emblem_trait=BRUISER
        ),
        item("TFT_Item_SwordPan", "검팬", "completed", SWORD, PAN),
        item("TFT_Item_Legacy", "낡은물건", "other", SWORD, ROD),
        item("TFT_Item_Relic", "유물", "artifact", ROD, ROD),
        item("TFT_Item_Lone", "단일재료", "completed", SWORD),
    ],
    "static_aliases": [
        alias("검지", "검지팡", "item"),
        alias("대장", "나르", "unit"),
        alias("브루저", "브루저 상징", "item"),
    ],
    "static_id_map": [
        *(mapping(u["api_name"], u["api_name"], "unit", u["name_ko"], "auto") for u in _UNITS),
        mapping("DA_Gromp_AD", "TFT18_Gromp_AP", "unit", "심술두꺼비 (AD)", "override"),
        mapping("TFT18_Summon", None, "unit", "털뭉치 친구", "override"),
        mapping("OPGG_Sword", SWORD, "item", "대검", "override"),
        mapping("OPGG_Rod", ROD, "item", "지팡이", "override"),
        mapping("OPGG_Spatula", SPATULA, "item", "뒤집개", "override"),
        mapping("OPGG_SwordSword", "TFT_Item_SwordSword", "item", "쌍대검", "override"),
        mapping("OPGG_SwordRod", "TFT_Item_SwordRod", "item", "검지팡", "override"),
        mapping("OPGG_BruiserEmblem", "TFT_Item_BruiserEmblem", "item", "브루저 상징", "override"),
    ],
    "static_augments": [],
}


@pytest.fixture
def repo(tmp_path: Path) -> CacheRepo:
    cache = tmp_path / "cache"
    cache.mkdir()
    for table, rows in TABLES.items():
        (cache / f"{table}.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    return CacheRepo(cache, SET, sets_dir=tmp_path / "sets")


def resolve(
    repo: CacheRepo, *words: str
) -> tuple[Envelope[ResolveNamesResult], list[tuple[str, str, str, str]]]:
    env = resolve_names(ResolveNamesInput(words=list(words)), repo)
    return env, [(m.input, m.id, m.type, m.method) for m in env.results.matches]


# ── resolve_names ──────────────────────────────────────────────────────────────


def test_alias_resolves_to_canonical_entity(repo: CacheRepo) -> None:
    _, matches = resolve(repo, "검지", "대장")
    assert matches == [
        ("검지", "OPGG_SwordRod", "item", "alias"),
        ("대장", "TFT18_Gnar", "unit", "alias"),
    ]


def test_alias_beats_exact_name(repo: CacheRepo) -> None:
    # "브루저"는 시너지 이름과도 정확히 일치하지만 줄임말 사전이 먼저다.
    _, matches = resolve(repo, "브루저")
    assert matches == [("브루저", "OPGG_BruiserEmblem", "item", "alias")]
    _, matches = resolve(repo, "일식")
    assert matches == [("일식", ECLIPSE, "trait", "exact")]


def test_exact_beats_partial(repo: CacheRepo) -> None:
    # "쌍대검"도 "대검"을 포함하지만 정확 일치가 있으면 하나만 돌려준다.
    _, matches = resolve(repo, "대검")
    assert matches == [("대검", "OPGG_Sword", "item", "exact")]


def test_exact_ignores_whitespace(repo: CacheRepo) -> None:
    _, matches = resolve(repo, "브루저상징")
    assert matches == [("브루저상징", "OPGG_BruiserEmblem", "item", "exact")]


def test_exact_known_id(repo: CacheRepo) -> None:
    _, matches = resolve(repo, "TFT18_Garen", "OPGG_Sword")
    assert matches == [
        ("TFT18_Garen", "TFT18_Garen", "unit", "exact"),
        ("OPGG_Sword", "OPGG_Sword", "item", "exact"),
    ]


def test_partial_returns_all_candidates_and_notes_ambiguity(repo: CacheRepo) -> None:
    env, matches = resolve(repo, "나")
    assert matches == [
        ("나", "TFT18_Gnar", "unit", "partial"),
        ("나", "TFT18_Nami", "unit", "partial"),
    ]
    assert len(env.notes) == 1
    assert "나" in env.notes[0]


def test_partial_candidates_sorted_by_name(repo: CacheRepo) -> None:
    _, matches = resolve(repo, "지팡")
    assert [(m[1], m[2]) for m in matches] == [("OPGG_SwordRod", "item"), ("OPGG_Rod", "item")]


def test_override_form_is_distinct_from_canonical_form(repo: CacheRepo) -> None:
    _, matches = resolve(repo, "심술두꺼비", "심술두꺼비 (AD)", "두꺼비")
    assert matches == [
        ("심술두꺼비", "TFT18_Gromp_AP", "unit", "exact"),
        ("심술두꺼비 (AD)", "DA_Gromp_AD", "unit", "exact"),
        ("두꺼비", "TFT18_Gromp_AP", "unit", "partial"),
        ("두꺼비", "DA_Gromp_AD", "unit", "partial"),
    ]


def test_name_only_summon_resolves_by_name(repo: CacheRepo) -> None:
    _, matches = resolve(repo, "털뭉치")
    assert matches == [("털뭉치", "TFT18_Summon", "unit", "partial")]


def test_unresolved_words_trimmed_and_ids_not_guessed(repo: CacheRepo) -> None:
    env, matches = resolve(repo, "  가렌  ", "없는말", "TFT18_Gare")
    assert matches == [("가렌", "TFT18_Garen", "unit", "exact")]
    assert env.results.unresolved == ["없는말", "TFT18_Gare"]


# ── craft_options ──────────────────────────────────────────────────────────────


def craft(
    repo: CacheRepo, *components: str
) -> tuple[Envelope[CraftOptionsResult], list[tuple[str, str, list[str], str]]]:
    env = craft_options(CraftOptionsInput(components=list(components)), repo)
    return env, [(o.item_id, o.name_ko, o.uses, o.kind) for o in env.results.root]


def test_craft_repeated_ingredient_needs_two_copies(repo: CacheRepo) -> None:
    _, one = craft(repo, "OPGG_Sword", "OPGG_Rod")
    assert one == [("OPGG_SwordRod", "검지팡", ["OPGG_Sword", "OPGG_Rod"], "completed")]
    _, two = craft(repo, "OPGG_Sword", "OPGG_Sword")
    assert two == [("OPGG_SwordSword", "쌍대검", ["OPGG_Sword", "OPGG_Sword"], "completed")]


def test_craft_alternatives_are_independent(repo: CacheRepo) -> None:
    # 대검 2 + 지팡이 1: 쌍대검(대검 2)과 검지팡(대검 1 + 지팡이 1)은 각각 가능하지만 동시에는 불가.
    env, options = craft(repo, "OPGG_Sword", "OPGG_Sword", "OPGG_Rod")
    assert {o[0] for o in options} == {"OPGG_SwordSword", "OPGG_SwordRod"}
    assert env.notes


def test_craft_counts_canonical_identity_across_id_forms(repo: CacheRepo) -> None:
    _, options = craft(repo, "OPGG_Sword", SWORD)
    assert [o[0] for o in options] == ["OPGG_SwordSword"]


def test_craft_includes_emblems_and_skips_legacy_kinds(repo: CacheRepo) -> None:
    # other·artifact·재료가 하나뿐인 항목은 조합 후보가 아니다.
    _, options = craft(repo, "OPGG_Spatula", "OPGG_Sword", "OPGG_Rod", "OPGG_Rod")
    assert {(o[0], o[3]) for o in options} == {
        ("OPGG_SwordRod", "completed"),
        ("OPGG_BruiserEmblem", "emblem"),
    }
    assert all(o[1] not in {"낡은물건", "유물", "단일재료"} for o in options)


def test_craft_uses_canonical_id_when_no_opgg_id(repo: CacheRepo) -> None:
    # 검팬과 프라이팬에는 OP.GG id가 없어 정식 apiName을 쓴다.
    _, options = craft(repo, PAN, "OPGG_Sword")
    assert options == [("TFT_Item_SwordPan", "검팬", ["OPGG_Sword", PAN], "completed")]


def test_craft_rejects_non_component(repo: CacheRepo) -> None:
    with pytest.raises(InvalidInput):
        craft(repo, "OPGG_SwordRod")


def test_craft_unknown_id_raises(repo: CacheRepo) -> None:
    with pytest.raises(UnknownName):
        craft(repo, "NOPE")


# ── calc_traits ────────────────────────────────────────────────────────────────


def traits(
    repo: CacheRepo, units: list[str], emblems: list[str] | None = None
) -> tuple[Envelope[CalcTraitsResult], list[tuple[str, str, int, int, int | None, int]]]:
    env = calc_traits(CalcTraitsInput(units=units, emblems=emblems or []), repo)
    return env, [
        (t.trait_id, t.name_ko, t.count, t.active_tier, t.next_breakpoint, t.need)
        for t in env.results.root
    ]


def test_traits_inactive_and_active_sorted_by_trait_id(repo: CacheRepo) -> None:
    # 브루저 2 → 1단계, 다음 4까지 2. 마법사 1 → 비활성, 다음 2까지 1.
    _, rows = traits(repo, ["TFT18_Garen", "TFT18_Gnar"])
    assert rows == [(BRUISER, "브루저", 2, 1, 4, 2), (MAGE, "마법사", 1, 0, 2, 1)]


def test_traits_breakpoint_boundaries(repo: CacheRepo) -> None:
    _, below = traits(repo, ["TFT18_Gnar"])
    assert below == [(BRUISER, "브루저", 1, 0, 2, 1)]
    _, four = traits(repo, ["TFT18_Garen", "TFT18_Gnar", "TFT18_Darius", "TFT18_Zed"])
    assert (BRUISER, "브루저", 4, 2, 6, 2) in four
    _, six = traits(
        repo,
        ["TFT18_Garen", "TFT18_Gnar", "TFT18_Darius", "TFT18_Zed", "TFT18_Ornn", "TFT18_Sion"],
    )
    assert (BRUISER, "브루저", 6, 3, None, 0) in six


def test_traits_count_each_champion_once(repo: CacheRepo) -> None:
    _, rows = traits(repo, ["TFT18_Garen"] * 3)
    assert rows == [(BRUISER, "브루저", 1, 0, 2, 1), (MAGE, "마법사", 1, 0, 2, 1)]


def test_traits_ad_and_ap_forms_are_one_champion(repo: CacheRepo) -> None:
    # 심술두꺼비 AP + AD는 한 명. 나미와 합쳐 마법사 2.
    _, rows = traits(repo, ["TFT18_Gromp_AP", "DA_Gromp_AD", "TFT18_Nami"])
    assert rows == [(MAGE, "마법사", 2, 1, 4, 2)]


def test_traits_emblems_each_add_one_with_note(repo: CacheRepo) -> None:
    # 같은 상징을 id 형태만 달리해 두 번: 인스턴스마다 +1. 2 + 2 = 4 → 2단계.
    env, rows = traits(
        repo,
        ["TFT18_Garen", "TFT18_Gnar"],
        ["OPGG_BruiserEmblem", "TFT_Item_BruiserEmblem"],
    )
    assert (BRUISER, "브루저", 4, 2, 6, 2) in rows
    assert len(env.notes) == 1


def test_traits_emblem_alone_counts_trait(repo: CacheRepo) -> None:
    _, rows = traits(repo, [], ["OPGG_BruiserEmblem"])
    assert rows == [(BRUISER, "브루저", 1, 0, 2, 1)]


def test_traits_rejects_non_emblem(repo: CacheRepo) -> None:
    with pytest.raises(InvalidInput):
        traits(repo, ["TFT18_Garen"], ["OPGG_SwordRod"])
    with pytest.raises(InvalidInput):
        traits(repo, ["TFT18_Garen"], ["OPGG_Sword"])


def test_traits_without_breakpoints_is_unavailable(repo: CacheRepo) -> None:
    with pytest.raises(DataUnavailable):
        traits(repo, ["TFT18_Garen", "TFT18_Moon"])


def test_traits_name_only_summon_is_unavailable(repo: CacheRepo) -> None:
    with pytest.raises(DataUnavailable):
        traits(repo, ["TFT18_Garen", "TFT18_Summon"])


def test_traits_unknown_unit_raises(repo: CacheRepo) -> None:
    with pytest.raises(UnknownName):
        traits(repo, ["NOPE"])
