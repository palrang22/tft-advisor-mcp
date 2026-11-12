"""툴의 유일한 등록 지점. 어댑터는 이 목록의 모델·설명·호출 함수를 사용한다."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from pydantic import BaseModel, ValidationError

from core.calc.calc_traits import calc_traits
from core.calc.craft_options import craft_options
from core.calc.level_up_plan import level_up_plan
from core.calc.reroll_odds import reroll_odds
from core.calc.resolve_names import resolve_names
from core.envelope import Envelope
from core.errors import InvalidInput
from core.models import (
    CalcTraitsInput,
    CalcTraitsResult,
    CraftOptionsInput,
    CraftOptionsResult,
    LevelUpPlanInput,
    LevelUpPlanResult,
    RerollOddsInput,
    RerollOddsResult,
    ResolveNamesInput,
    ResolveNamesResult,
)
from core.repo.base import Repository


@dataclass(frozen=True)
class ToolSpec[I: BaseModel, O: BaseModel]:
    name: str
    description: str
    fn: Callable[[I, Repository], Envelope[O]]
    input_model: type[I]
    output_model: type[O]

    def invoke(self, arguments: Mapping[str, Any], repo: Repository) -> Envelope[O]:
        try:
            inputs = self.input_model.model_validate(arguments)
        except ValidationError as exc:
            raise InvalidInput(str(exc)) from exc
        return self.fn(inputs, repo)


TOOLS: Mapping[str, ToolSpec[Any, Any]] = MappingProxyType(
    {
        spec.name: spec
        for spec in (
            ToolSpec(
                "resolve_names",
                "줄임말·한국어 이름·ID를 해석한다. 모호하면 모든 후보와 미해결 입력을 반환한다.",
                resolve_names,
                ResolveNamesInput,
                ResolveNamesResult,
            ),
            ToolSpec(
                "reroll_odds",
                "레벨·골드·보유 장수로 목표 성급 도달 확률과 평균 지출을 계산한다. "
                "목표 기물 구매비 포함, 1만 회 몬테카를로 추정이다.",
                reroll_odds,
                RerollOddsInput,
                RerollOddsResult,
            ),
            ToolSpec(
                "level_up_plan",
                "다음 레벨까지 경험치 구매비·남는 골드·이자·다음 레벨 상점 확률을 계산한다.",
                level_up_plan,
                LevelUpPlanInput,
                LevelUpPlanResult,
            ),
            ToolSpec(
                "craft_options",
                "보유 재료로 만들 수 있는 완성템·상징을 모두 찾는다. 각 행은 독립적인 선택지다.",
                craft_options,
                CraftOptionsInput,
                CraftOptionsResult,
            ),
            ToolSpec(
                "calc_traits",
                "챔피언·상징으로 활성 시너지 단계와 다음 단계까지 부족한 수를 계산한다.",
                calc_traits,
                CalcTraitsInput,
                CalcTraitsResult,
            ),
        )
    }
)


def get_tool(name: str) -> ToolSpec[Any, Any]:
    try:
        return TOOLS[name]
    except KeyError as exc:
        raise InvalidInput(f"등록되지 않은 툴: {name}") from exc


def call_tool(name: str, arguments: Mapping[str, Any], repo: Repository) -> Envelope[Any]:
    return get_tool(name).invoke(arguments, repo)
