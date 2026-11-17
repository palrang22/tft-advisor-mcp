"""캐시 누락·세트 혼합·수치 누락과 JSON/parquet 읽기 경계 검사. 외부 연결 없음."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from core.errors import DataUnavailable, MissingSetData
from core.repo.cache_repo import CacheRepo


@pytest.fixture
def cache(tmp_path: Path) -> Path:
    tables = {
        "static_units": [
            {
                "set_number": 18,
                "api_name": "Unit",
                "name_ko": "기물",
                "cost": 1,
                "traits": ["Trait"],
                "role": None,
            }
        ],
        "static_traits": [
            {
                "set_number": 18,
                "api_name": "Trait",
                "name_ko": "특성",
                "breakpoints": [2, 4],
                "desc_ko": None,
            }
        ],
        "static_items": [
            {
                "set_number": 18,
                "api_name": "Current",
                "name_ko": "대검",
                "components": [],
                "kind": "component",
                "emblem_trait": None,
            },
            {
                "set_number": 18,
                "api_name": "Legacy",
                "name_ko": "대검",
                "components": [],
                "kind": "other",
                "emblem_trait": None,
            },
        ],
        "static_aliases": [],
        "static_id_map": [
            {
                "opgg_id": "Form",
                "api_name": "Unit",
                "type": "unit",
                "name_ko": "기물 (AD)",
                "match_method": "override",
            },
            {
                "opgg_id": "Summon",
                "api_name": None,
                "type": "unit",
                "name_ko": "소환물",
                "match_method": "override",
            },
        ],
    }
    for name, rows in tables.items():
        (tmp_path / f"{name}.json").write_text(json.dumps(rows), encoding="utf-8")
    return tmp_path


def test_missing_and_corrupt_cache_fail_with_domain_error(cache: Path) -> None:
    (cache / "static_items.json").unlink()
    with pytest.raises(DataUnavailable, match="static_items"):
        CacheRepo(cache, 18)
    (cache / "static_items.json").write_text("not json", encoding="utf-8")
    with pytest.raises(DataUnavailable, match="static_items"):
        CacheRepo(cache, 18)


def test_other_set_cache_cannot_supply_current_set(cache: Path) -> None:
    with pytest.raises(DataUnavailable, match="Set 19"):
        CacheRepo(cache, 19)


def test_name_lookup_prefers_current_items_and_preserves_overrides(cache: Path) -> None:
    repo = CacheRepo(cache, 18)
    assert [(n.id, n.name_ko) for n in repo.names if n.type == "item"] == [("Current", "대검")]
    assert repo.unit("Form").api_name == "Unit"
    assert any(n.id == "Summon" and n.name_ko == "소환물" for n in repo.names)
    with pytest.raises(DataUnavailable):
        repo.unit("Summon")  # 이름만 아는 소환물에 비용·시너지를 만들어 넣지 않는다


def test_parquet_preserves_repeated_traits_and_null_fields(cache: Path) -> None:
    path = cache / "static_units.json"
    pd.DataFrame(json.loads(path.read_text())).to_parquet(cache / "static_units.parquet")
    path.unlink()
    unit = CacheRepo(cache, 18).unit("Form")
    assert unit.name_ko == "기물"
    assert unit.traits == ("Trait",)
    assert unit.role is None


def test_rules_are_lazy_and_missing_file_is_actionable(cache: Path) -> None:
    repo = CacheRepo(cache, 18, sets_dir=cache / "sets")
    assert repo.item("Current").name_ko == "대검"
    with pytest.raises(MissingSetData, match="set18.yaml"):
        repo.set_rules()


def test_nested_todo_reports_field_path(cache: Path) -> None:
    (cache / "set18.yaml").write_text("set: 18\nshop_odds:\n  6: [30, TODO]\n")
    with pytest.raises(MissingSetData, match=r"shop_odds.6\[1\]"):
        CacheRepo(cache, 18, sets_dir=cache).set_rules()


def test_invalid_probability_sum_is_not_silently_normalized(cache: Path) -> None:
    (cache / "set18.yaml").write_text(
        "set: 18\nshop_odds: {1: [80]}\npool_size: {1: 10}\n"
        "champions_per_cost: {1: 2}\nxp_to_next: {1: null, 2: 2}\n"
        "reroll_cost: 2\nxp_per_buy: 4\nxp_buy_cost: 4\ninterest_cap: 5\n"
    )
    with pytest.raises(MissingSetData, match="100"):
        CacheRepo(cache, 18, sets_dir=cache).set_rules()


def test_repeated_effect_threshold_does_not_double_trait_tier(cache: Path) -> None:
    from core.calc.calc_traits import calc_traits
    from core.models import CalcTraitsInput

    path = cache / "static_traits.json"
    rows = json.loads(path.read_text())
    rows[0]["breakpoints"] = [1, 1, 2]  # 실제 CDragon 경쟁자와 같은 중복 최소 인원
    path.write_text(json.dumps(rows))
    result = calc_traits(CalcTraitsInput(units=["Unit"]), CacheRepo(cache, 18)).results.root[0]
    assert (result.count, result.active_tier, result.next_breakpoint, result.need) == (1, 1, 2, 1)
