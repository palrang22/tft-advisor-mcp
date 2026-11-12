"""reroll_odds: 상점 리롤 몬테카를로 (유한 공용 풀, 상점 5칸, 비복원 추출)."""

from __future__ import annotations

import random

from core.envelope import Envelope
from core.errors import InvalidInput, MissingSetData
from core.models import RerollOddsInput, RerollOddsResult, SetRules
from core.repo.base import Repository

SIMULATIONS = 10_000
SHOP_SLOTS = 5
_SEED = 20261112


def reroll_odds(params: RerollOddsInput, repo: Repository) -> Envelope[RerollOddsResult]:
    rules = repo.set_rules()
    unit = repo.unit(params.unit_id)
    id_row = repo.id_map.get(params.unit_id)
    name_ko = (id_row.name_ko if id_row else None) or unit.name_ko or unit.api_name

    odds = rules.shop_odds.get(params.level)
    if odds is None:
        raise InvalidInput(f"지원하지 않는 레벨: {params.level} (set {rules.set} shop_odds에 없다)")
    cost = unit.cost
    for table, label in (
        (rules.pool_size, "pool_size"),
        (rules.champions_per_cost, "champions_per_cost"),
    ):
        if cost not in table:
            raise MissingSetData(f"set{rules.set:02d}.yaml {label}에 {cost}코스트가 없다")

    pool = rules.pool_size[cost]
    champions = rules.champions_per_cost[cost]
    contested = params.contested or 0
    if params.owned + contested > pool:
        raise InvalidInput(
            f"owned({params.owned}) + contested({contested})가 풀 크기({pool})를 넘는다"
        )

    copies = 3 ** (params.target_star - 1)
    need = copies - params.owned
    target_left = pool - params.owned - contested
    tier_total = pool * champions - params.owned - contested
    tier_odds = odds[cost - 1] / 100 if cost - 1 < len(odds) else 0.0

    if need <= 0:
        p_hit, gold_used = 1.0, 0.0
    elif target_left < need or tier_odds <= 0:
        p_hit, gold_used = 0.0, 0.0
    else:
        p_hit, gold_used = _simulate(
            rules, params.gold, cost, tier_odds, need, target_left, tier_total, random.Random(_SEED)
        )

    notes = [
        f"기물 풀 {pool}장 x {champions}종 기준. "
        "다른 플레이어 보유량은 contested로 준 목표 기물 장수만 반영",
        "골드는 리롤 비용과 목표 기물 구매 비용만 센다. 이미 떠 있는 상점, 이자·수입, "
        "다른 코스트 구매, 특수 리롤 효과는 제외",
    ]
    if params.contested is None:
        notes.append("contested를 주지 않아 0으로 계산했다. 실제보다 낙관적인 값")
    return Envelope[RerollOddsResult](
        source="calc",
        set_number=repo.set_number,
        results=RerollOddsResult(
            unit_id=params.unit_id,
            name_ko=name_ko,
            p_hit=p_hit,
            expected_gold_used=gold_used,
            simulations=SIMULATIONS,
            optimistic=params.contested is None,
        ),
        notes=notes,
        is_estimate=True,
    )


def _simulate(
    rules: SetRules,
    gold: int,
    cost: int,
    tier_odds: float,
    need: int,
    target_left: int,
    tier_total: int,
    rng: random.Random,
) -> tuple[float, float]:
    """(성공 비율, 평균 사용 골드). 같은 시드면 항상 같은 값."""
    reroll = rules.reroll_cost
    hits_total = 0
    spent_total = 0
    for _ in range(SIMULATIONS):
        g = gold
        remaining = need
        target = target_left
        total = tier_total
        while remaining > 0 and g >= reroll + cost:
            g -= reroll
            drawn_total = total
            drawn_target = target
            seen = 0
            for _slot in range(SHOP_SLOTS):
                if drawn_total <= 0 or rng.random() >= tier_odds:
                    continue
                if rng.random() * drawn_total < drawn_target:
                    seen += 1
                    drawn_target -= 1
                drawn_total -= 1
            bought = min(seen, remaining, g // cost)
            g -= bought * cost
            remaining -= bought
            target -= bought
            total -= bought
        if remaining == 0:
            hits_total += 1
        spent_total += gold - g
    return hits_total / SIMULATIONS, spent_total / SIMULATIONS
