"""level_up_plan: 경험치 구매로 다음 레벨까지 드는 골드와 이후 상태."""

from __future__ import annotations

from core.envelope import Envelope
from core.errors import InvalidInput, MissingSetData
from core.models import LevelUpPlanInput, LevelUpPlanResult
from core.repo.base import Repository


def level_up_plan(params: LevelUpPlanInput, repo: Repository) -> Envelope[LevelUpPlanResult]:
    rules = repo.set_rules()
    known = [v for v in rules.xp_to_next.values() if v is not None]
    if not known:
        raise MissingSetData(f"set{rules.set:02d}.yaml xp_to_next에 경험치 값이 없다")
    max_level = max(level for level, v in rules.xp_to_next.items() if v is not None) + 1
    level = params.level
    if level >= max_level:
        raise InvalidInput(f"최대 레벨({max_level})이라 더 올릴 수 없다")
    if level not in rules.xp_to_next:
        raise MissingSetData(f"set{rules.set:02d}.yaml xp_to_next에 레벨 {level}이 없다")
    threshold = rules.xp_to_next[level]
    if threshold is None:
        raise InvalidInput(f"레벨 {level}은 자동으로 오르며 경험치 구매 대상이 아니다")
    if params.xp >= threshold:
        raise InvalidInput(
            f"xp({params.xp})가 레벨 {level}의 다음 레벨 필요량({threshold}) 이상이다"
        )
    odds = rules.shop_odds.get(level + 1)
    if odds is None:
        raise MissingSetData(f"set{rules.set:02d}.yaml shop_odds에 레벨 {level + 1}이 없다")

    buys = -(-(threshold - params.xp) // rules.xp_per_buy)
    cost = buys * rules.xp_buy_cost
    gold_after = params.gold - cost
    interest = min(rules.interest_cap, max(0, gold_after) // 10)
    notes = ["경험치 구매만으로 오르는 경우의 비용. 라운드 종료 시 자동 경험치는 반영하지 않는다"]
    if gold_after < 0:
        notes.append("골드가 모자라 gold_after는 가상의 음수 값이다")
    return Envelope[LevelUpPlanResult](
        source="calc",
        set_number=repo.set_number,
        results=LevelUpPlanResult(
            cost_to_next=cost,
            gold_after=gold_after,
            next_level_odds={c: float(p) for c, p in enumerate(odds, start=1)},
            interest_after=interest,
            affordable=gold_after >= 0,
        ),
        notes=notes,
    )
