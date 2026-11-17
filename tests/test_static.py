"""static 적재 변환 테스트.

- `tests/fixtures/cdragon/ko_kr_set18_subset.json`: 실제 CDragon `ko_kr.json`(2026-11-12)에서
  Set 18 챔피언 4·시너지 9·아이템 10·증강 2개와 Set 17 항목 1개만 그대로 잘라낸 것.
- OP.GG 파일은 Phase 1 fixture 그대로.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from snapshot.store import latest_file
from static import aliases, cdragon, id_map, opgg_ref
from static.loader import build_static

FIX = Path(__file__).parent / "fixtures"
CDRAGON = json.loads((FIX / "cdragon/ko_kr_set18_subset.json").read_text(encoding="utf-8"))
LIST_TOOLS = json.loads((FIX / "opgg/list_tools.json").read_text(encoding="utf-8"))
COMBOS = json.loads(
    (FIX / "opgg/tft_list_item_combinations__ko_KR.json").read_text(encoding="utf-8")
)


def write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def no_rules(tmp_path: Path) -> dict[str, Path]:
    return {"aliases_path": tmp_path / "none.yaml", "overrides_path": tmp_path / "none2.yaml"}


def by_api(rows: list) -> dict:
    return {r["api_name"]: r for r in rows}


def test_build_static_set18(no_rules: dict[str, Path]) -> None:
    build = build_static(18, CDRAGON, LIST_TOOLS, COMBOS, **no_rules)
    units = by_api(build.tables["static_units"])
    items = by_api(build.tables["static_items"])
    traits = by_api(build.tables["static_traits"])

    # Set 17 항목은 섞이지 않는다
    assert all(r["set_number"] == 18 for r in build.tables["static_units"])
    assert set(units) == {"DA_18_Sivir", "DA_18_Ornn", "DA_Gromp18_AP", "TFT_Krug"}

    # 챔피언 시너지는 한국어 이름 → 시너지 apiName
    assert units["DA_18_Ornn"]["traits"] == ["DA_18_Elderwood", "DA_18_Defender"]
    assert units["TFT_Krug"]["traits"] == []

    # kind: OP.GG category 기준, 조합식에 없거나 category가 없는 것은 other
    assert items["DA_InfinityEdge"]["kind"] == "completed"
    assert items["DA_InfinityEdge"]["components"] == [
        "DA_Component_BFSword",
        "DA_Component_SparringGloves",
    ]
    assert items["DA_Component_Spatula"]["kind"] == "component"
    assert items["DA_AdaptiveHelm_Radiant"]["kind"] == "radiant"
    assert items["DA_Artifact_AegisOfDawn"]["kind"] == "artifact"
    assert items["DA_HealthPotion18"]["kind"] == "other"
    assert items["TFT_Item_InfinityEdge"]["kind"] == "other"

    # 상징 → 시너지: "<시너지 이름> 상징". ID 형식이 달라도(DA_Juggernaut18) 이름으로 찾는다
    assert items["DA_18_EmblemFae"]["emblem_trait"] == "DA_18_Fae"
    assert items["DA_18_EmblemJuggernaut"]["emblem_trait"] == "DA_Juggernaut18"
    assert items["DA_InfinityEdge"]["emblem_trait"] is None
    assert build.emblem_failures == []

    # CDragon minUnits가 null인 단계는 breakpoints에서 빠진다
    assert traits["DA_18_Eclipse"]["breakpoints"] == []
    assert traits["DA_18_Elderwood"]["breakpoints"] == [3, 5, 7, 9, 11]


def test_id_map_exact_match_and_unmatched(no_rules: dict[str, Path]) -> None:
    build = build_static(18, CDRAGON, LIST_TOOLS, COMBOS, **no_rules)
    mapped = {r["opgg_id"]: r for r in build.tables["static_id_map"]}
    unmatched = {u["opgg_id"]: u["type"] for u in build.unmatched}

    assert mapped["DA_18_Sivir"]["api_name"] == "DA_18_Sivir"
    assert mapped["DA_18_Sivir"]["match_method"] == "auto"
    assert mapped["DA_18_Sivir"]["name_ko"] == "시비르"
    assert mapped["DA_18_EmblemFae"]["type"] == "item"
    # 비슷한 ID(DA_Gromp18_AP)가 있어도 추측해서 붙이지 않는다
    assert unmatched["DA_Gromp18_AD"] == "unit"
    assert "DA_Gromp18_AD" not in mapped


def test_overrides_take_precedence_and_todo_is_unfilled(tmp_path: Path) -> None:
    overrides = write(
        tmp_path / "o.yaml",
        "ids:\n"
        "  DA_Gromp18_AD: {api_name: DA_Gromp18_AP, name_ko: 심술두꺼비 (AD)}\n"
        "  DA_18_Sivir: DA_18_Ornn\n"
        "  TFT18_SprykinSummonMelee: {name_ko: 커다란 털뭉치 친구}\n"
        "  DA_NidaleeCougar18_AD: TODO\n"
        "emblem_traits:\n"
        "  DA_18_EmblemFae: DA_18_Hunter\n",
    )
    build = build_static(18, CDRAGON, LIST_TOOLS, COMBOS, tmp_path / "none.yaml", overrides)
    mapped = {r["opgg_id"]: r for r in build.tables["static_id_map"]}
    unmatched = {u["opgg_id"] for u in build.unmatched}

    # 같은 CDragon 챔피언에 붙이되 이름은 override 값
    assert mapped["DA_Gromp18_AD"] == {
        "opgg_id": "DA_Gromp18_AD",
        "api_name": "DA_Gromp18_AP",
        "type": "unit",
        "name_ko": "심술두꺼비 (AD)",
        "match_method": "override",
    }
    # 문자열 override는 CDragon 이름을 쓰고, 자동 결과보다 우선
    assert mapped["DA_18_Sivir"]["api_name"] == "DA_18_Ornn"
    assert mapped["DA_18_Sivir"]["name_ko"] == "오른"
    # CDragon에 없는 것은 이름만
    assert mapped["TFT18_SprykinSummonMelee"]["api_name"] is None
    assert mapped["TFT18_SprykinSummonMelee"]["name_ko"] == "커다란 털뭉치 친구"
    assert "DA_NidaleeCougar18_AD" in unmatched
    items = by_api(build.tables["static_items"])
    assert items["DA_18_EmblemFae"]["emblem_trait"] == "DA_18_Hunter"


@pytest.mark.parametrize(
    "overrides_yaml",
    [
        "ids:\n  DA_Gromp18_AD: DA_Nope\n",  # 없는 apiName
        "ids:\n  DA_Gromp18_AD: {api_name: DA_Nope, name_ko: x}\n",  # 맵에서도 검사
        "ids:\n  DA_Gromp18_AD: {name: 심술두꺼비}\n",  # 키 오타
        "emblem_traits:\n  DA_18_EmblemFae: DA_Nope\n",  # 없는 시너지
        "idz: {}\n",  # 섹션 오타
    ],
)
def test_bad_overrides_fail(tmp_path: Path, overrides_yaml: str) -> None:
    overrides = write(tmp_path / "o.yaml", overrides_yaml)
    with pytest.raises(ValueError):
        build_static(18, CDRAGON, LIST_TOOLS, COMBOS, tmp_path / "none.yaml", overrides)


def test_emblem_name_rule_failure_is_reported() -> None:
    data = json.loads(json.dumps(CDRAGON))
    for it in data["items"]:
        if it["apiName"] == "DA_18_EmblemFae":
            it["name"] = "요정 문장"
    set_data = cdragon.select_set(data, 18)
    _, failures = cdragon.build_items(
        data, set_data, 18, {"DA_18_EmblemFae": "emblem"}, emblem_overrides={}
    )
    assert failures == [{"api_name": "DA_18_EmblemFae", "name_ko": "요정 문장"}]


def test_unknown_set_and_stale_combinations_fail() -> None:
    with pytest.raises(ValueError):
        cdragon.select_set(CDRAGON, 19)
    with pytest.raises(ValueError):
        opgg_ref.read_item_kinds(COMBOS, 19)


def test_item_kinds_same_for_trimmed_combinations_response() -> None:
    # 2026-11-13 응답은 최상위 키가 set·version·data뿐이고 현재 세트 137행만 온다 (11-12는 519행).
    # OP.GG enum 아이템의 분류는 두 형태에서 같아야 한다.
    trimmed = json.loads(
        (FIX / "opgg/tft_list_item_combinations__ko_KR.20261113.json").read_text(encoding="utf-8")
    )
    full_kinds = opgg_ref.read_item_kinds(COMBOS, 18)
    trimmed_kinds = opgg_ref.read_item_kinds(trimmed, 18)
    item_ids = opgg_ref.read_enums(LIST_TOOLS)["item"]

    assert [trimmed_kinds.get(i) for i in item_ids] == [full_kinds.get(i) for i in item_ids]
    assert trimmed_kinds["DA_18_EmblemJuggernaut"] == "emblem"


def test_aliases(tmp_path: Path) -> None:
    path = write(
        tmp_path / "a.yaml", "items:\n  무대: 무한의 대검\n  오타: 무한의 대겸\nunits: {}\n"
    )
    rows = aliases.load_aliases(path)
    assert {"alias": "무대", "canonical_name_ko": "무한의 대검", "type": "item"} in rows
    bad = aliases.unknown_canonicals(rows, {"item": {"무한의 대검"}, "unit": set(), "trait": set()})
    assert [r["alias"] for r in bad] == ["오타"]

    with pytest.raises(ValueError):
        aliases.load_aliases(write(tmp_path / "b.yaml", "item:\n  무대: 무한의 대검\n"))


def test_unmatched_file_lists_ids_and_emblems(tmp_path: Path) -> None:
    out = tmp_path / "unmatched_ids.txt"
    id_map.write_unmatched(
        out,
        18,
        [{"opgg_id": "DA_Gromp18_AD", "type": "unit"}],
        [{"api_name": "DA_18_EmblemX", "name_ko": "엑스 문장"}],
    )
    lines = out.read_text(encoding="utf-8").splitlines()
    assert "DA_Gromp18_AD\tunit" in lines
    assert "DA_18_EmblemX\t엑스 문장" in lines


def test_latest_file_skips_dates_without_file(tmp_path: Path) -> None:
    for day, has in [("2026-11-10", True), ("2026-11-11", True), ("2026-11-12", False)]:
        (tmp_path / day).mkdir()
        if has:
            write(tmp_path / day / "list_tools.json", "{}")
    (tmp_path / "not-a-date").mkdir()
    write(tmp_path / "not-a-date" / "list_tools.json", "{}")

    assert latest_file(tmp_path, "list_tools.json") == tmp_path / "2026-11-11" / "list_tools.json"
    assert latest_file(tmp_path / "missing", "list_tools.json") is None
