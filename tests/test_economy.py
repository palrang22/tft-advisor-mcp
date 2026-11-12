"""reroll_odds · level_up_plan 테스트.

- 챔피언·시너지 정적 표는 `tests/fixtures`의 실제 CDragon/OP.GG 응답에서 `build_static`으로 만든다
  (오른 1코, 심술두꺼비 2코, 시비르 4코).
- 세트 규칙 YAML은 손으로 검산 가능한 작은 값을 임시 디렉터리에 쓴다. 실제 게임 수치가 아니다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.calc.level_up_plan import level_up_plan
from core.calc.reroll_odds import SIMULATIONS, reroll_odds
from core.envelope import Envelope
from core.errors import InvalidInput, MissingSetData
from core.models import LevelUpPlanInput, LevelUpPlanResult, RerollOddsInput, RerollOddsResult
from core.repo.cache_repo import CacheRepo
from static.loader import build_static, write_cache

FIX = Path(__file__).parent / "fixtures"

ORNN = "DA_18_Ornn"  # 1코
GROMP = "DA_Gromp18_AP"  # 2코

# 레벨 1·2: 1코 100%, 3: 2코 100%, 4: 4코 100%, 5: 4코 30% 포함 분산, 6: 5코 100%
YAML_TEMPLATE = """\
set: 18
shop_odds:
  1: [100, 0, 0, 0, 0]
  2: [100, 0, 0, 0, 0]
  3: [0, 100, 0, 0, 0]
  4: [0, 0, 0, 100, 0]
  5: [15, 20, 32, 30, 3]
  6: [0, 0, 0, 0, 100]
pool_size:
  1: {pool1}
  2: {pool2}
  3: 18
  4: 10
  5: 9
champions_per_cost:
  1: {champs1}
  2: {champs2}
  3: 14
  4: 14
  5: 10
xp_to_next:
  1: null
  2: 2
  3: 6
  4: 10
  5: 20
reroll_cost: {reroll}
xp_per_buy: 4
xp_buy_cost: 4
interest_cap: 5
"""


def make_repo(
    tmp_path: Path,
    *,
    pool1: int = 5,
    champs1: int = 2,
    pool2: int = 5,
    champs2: int = 2,
    reroll: object = 2,
) -> CacheRepo:
    build = build_static(
        18,
        json.loads((FIX / "cdragon/ko_kr_set18_subset.json").read_text(encoding="utf-8")),
        json.loads((FIX / "opgg/list_tools.json").read_text(encoding="utf-8")),
        json.loads(
            (FIX / "opgg/tft_list_item_combinations__ko_KR.json").read_text(encoding="utf-8")
        ),
        aliases_path=tmp_path / "no_aliases.yaml",
        overrides_path=tmp_path / "no_overrides.yaml",
    )
    write_cache(tmp_path, build, 18)
    sets_dir = tmp_path / "sets"
    sets_dir.mkdir(exist_ok=True)
    (sets_dir / "set18.yaml").write_text(
        YAML_TEMPLATE.format(
            pool1=pool1, champs1=champs1, pool2=pool2, champs2=champs2, reroll=reroll
        ),
        encoding="utf-8",
    )
    return CacheRepo(tmp_path, 18, sets_dir=sets_dir)


def roll(repo: CacheRepo, **kw: object) -> Envelope[RerollOddsResult]:
    kw.setdefault("owned", 0)
    return reroll_odds(RerollOddsInput(**kw), repo)


# ── reroll_odds ──


def test_already_complete(tmp_path: Path) -> None:
    env = roll(make_repo(tmp_path), level=2, gold=0, unit_id=ORNN, owned=3, target_star=2)
    r = env.results
    assert (r.p_hit, r.expected_gold_used, r.simulations) == (1.0, 0.0, SIMULATIONS)
    assert r.name_ko == "오른"
    assert env.is_estimate


def test_zero_funds(tmp_path: Path) -> None:
    # 리롤 2 + 구매 1이 필요하므로 2골드로는 한 번도 못 구른다
    r = roll(make_repo(tmp_path), level=2, gold=2, unit_id=ORNN, target_star=2).results
    assert (r.p_hit, r.expected_gold_used) == (0.0, 0.0)


def test_zero_shop_odds(tmp_path: Path) -> None:
    # 2레벨 상점에는 2코가 없다
    r = roll(make_repo(tmp_path), level=2, gold=100, unit_id=GROMP, target_star=2).results
    assert (r.p_hit, r.expected_gold_used) == (0.0, 0.0)


def test_pool_exhausted(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, pool1=5)
    # 풀 5장, 보유 2 + 경쟁 3 = 0장 남음 → 2성(3장 중 1장 더 필요) 불가
    r = roll(repo, level=2, gold=100, unit_id=ORNN, owned=2, contested=3, target_star=2).results
    assert (r.p_hit, r.expected_gold_used) == (0.0, 0.0)
    # 남은 5-1-3=1장, 필요 3-1=2장 → 불가
    r = roll(repo, level=2, gold=100, unit_id=ORNN, owned=1, contested=3, target_star=2).results
    assert (r.p_hit, r.expected_gold_used) == (0.0, 0.0)


def test_owned_plus_contested_over_pool(tmp_path: Path) -> None:
    with pytest.raises(InvalidInput):
        roll(make_repo(tmp_path, pool1=5), level=2, gold=10, unit_id=ORNN, owned=3, contested=3)


def test_unsupported_level(tmp_path: Path) -> None:
    with pytest.raises(InvalidInput):
        roll(make_repo(tmp_path), level=99, gold=10, unit_id=ORNN)


def test_without_replacement_analytic(tmp_path: Path) -> None:
    # 1코 풀: 5장 x 3종 = 15장, 목표 5장. 레벨 2 상점은 5칸 모두 1코.
    # 2성은 3장 필요. 한 상점에서 비복원으로 5장을 뽑아 목표가 3장 이상일 확률
    #   = [C(5,3)C(10,2) + C(5,4)C(10,1) + C(5,5)C(10,0)] / C(15,5) = 501/3003 ≈ 0.1668
    # 복원 추출(이항, p=1/3)이면 ≈ 0.2099라 둘은 구분된다.
    # 골드 5 = 리롤 2 + 3장 구매 → 상점 한 번만 가능.
    repo = make_repo(tmp_path, pool1=5, champs1=3)
    r = roll(repo, level=2, gold=5, unit_id=ORNN, target_star=2).results
    assert r.p_hit == pytest.approx(501 / 3003, abs=0.015)


def test_buy_cost_limits_gold(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    # 4골드: 리롤 2 후 2골드로 1코 2장만 산다 → 3장 필요하니 불가
    r = roll(repo, level=2, gold=4, unit_id=ORNN, target_star=2).results
    assert r.p_hit == 0.0
    assert 2.0 <= r.expected_gold_used <= 4.0
    # 2코(구매 2골드): 리롤 2 + 3장 6 = 8이면 가능, 7이면 불가
    cheap = roll(repo, level=3, gold=7, unit_id=GROMP, target_star=2).results
    enough = roll(repo, level=3, gold=8, unit_id=GROMP, target_star=2).results
    assert cheap.p_hit == 0.0
    assert enough.p_hit == pytest.approx(0.5, abs=0.02)


def test_deterministic_and_optimistic(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, pool1=9, champs1=3)
    a = roll(repo, level=2, gold=10, unit_id=ORNN, target_star=2)
    b = roll(repo, level=2, gold=10, unit_id=ORNN, target_star=2)
    assert a.results == b.results
    assert 0.0 < a.results.p_hit < 1.0
    assert a.results.optimistic is True and a.results.simulations == SIMULATIONS
    c = roll(repo, level=2, gold=10, unit_id=ORNN, target_star=2, contested=0)
    assert c.results.optimistic is False
    assert c.results.p_hit == a.results.p_hit  # contested None은 0으로 계산


def test_contested_lowers_probability(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, pool1=9, champs1=3)
    free = roll(repo, level=2, gold=10, unit_id=ORNN, target_star=2, contested=0).results
    tight = roll(repo, level=2, gold=10, unit_id=ORNN, target_star=2, contested=6).results
    assert tight.p_hit < free.p_hit


def test_reroll_todo_raises_missing_set_data(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, reroll="TODO")
    with pytest.raises(MissingSetData):
        roll(repo, level=2, gold=10, unit_id=ORNN)


# ── level_up_plan ──


def plan(repo: CacheRepo, level: int, xp: int, gold: int) -> Envelope[LevelUpPlanResult]:
    return level_up_plan(LevelUpPlanInput(level=level, xp=xp, gold=gold), repo)


def test_level_up_exact(tmp_path: Path) -> None:
    env = plan(make_repo(tmp_path), 2, 0, 20)
    r = env.results
    # 필요 2, 구매 1회 4xp → 1회 4골드
    assert (r.cost_to_next, r.gold_after, r.affordable, r.interest_after) == (4, 16, True, 1)
    assert r.next_level_odds == {1: 0.0, 2: 100.0, 3: 0.0, 4: 0.0, 5: 0.0}


def test_level_up_rounds_up(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    # 레벨 3: 필요 6, 보유 1 → 5 / 4 올림 2회 = 8골드
    assert plan(repo, 3, 1, 50).results.cost_to_next == 8
    # 필요 4 → 정확히 1회
    assert plan(repo, 3, 2, 50).results.cost_to_next == 4
    # 필요 1 → 1회
    assert plan(repo, 3, 5, 50).results.cost_to_next == 4


def test_level_up_interest_cap(tmp_path: Path) -> None:
    r = plan(make_repo(tmp_path), 2, 0, 200).results
    assert r.gold_after == 196 and r.interest_after == 5


def test_level_up_no_funds(tmp_path: Path) -> None:
    r = plan(make_repo(tmp_path), 3, 1, 3).results
    assert r.cost_to_next == 8
    assert r.gold_after == -5
    assert r.affordable is False
    assert r.interest_after == 0


def test_level_up_exact_funds(tmp_path: Path) -> None:
    r = plan(make_repo(tmp_path), 2, 0, 4).results
    assert r.gold_after == 0 and r.affordable is True and r.interest_after == 0


def test_level_up_top_level(tmp_path: Path) -> None:
    # xp_to_next 최대 키가 5라 최대 레벨은 6. 레벨 5는 아직 올릴 수 있다
    r = plan(make_repo(tmp_path), 5, 0, 100).results
    assert (r.cost_to_next, r.gold_after) == (20, 80)
    assert r.next_level_odds == {1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0, 5: 100.0}
    with pytest.raises(InvalidInput):
        plan(make_repo(tmp_path), 6, 0, 100)
    with pytest.raises(InvalidInput):
        plan(make_repo(tmp_path), 7, 0, 100)


def test_level_up_auto_level1(tmp_path: Path) -> None:
    with pytest.raises(InvalidInput):
        plan(make_repo(tmp_path), 1, 0, 100)


def test_level_up_xp_already_enough(tmp_path: Path) -> None:
    with pytest.raises(InvalidInput):
        plan(make_repo(tmp_path), 2, 2, 100)


def test_level_up_todo_raises_missing_set_data(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, reroll="TODO")
    with pytest.raises(MissingSetData):
        plan(repo, 2, 0, 10)
