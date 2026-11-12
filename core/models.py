"""모든 어댑터가 공유하는 입력·출력과 정적 데이터 계약. 세트별 ID·게임 수치 기본값은 없다."""

from __future__ import annotations

import math
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    StringConstraints,
    field_validator,
    model_validator,
)

Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
EntityType = Literal["unit", "item", "trait"]
NonNegativeInt = Annotated[int, Field(ge=0, strict=True)]
PositiveInt = Annotated[int, Field(gt=0, strict=True)]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class StaticUnit(Model):
    set_number: PositiveInt
    api_name: Identifier
    name_ko: str | None
    cost: NonNegativeInt
    traits: tuple[str, ...]
    role: str | None


class StaticItem(Model):
    set_number: PositiveInt
    api_name: Identifier
    name_ko: str | None
    components: tuple[str, ...]
    kind: Literal["component", "completed", "emblem", "artifact", "radiant", "other"]
    emblem_trait: str | None


class StaticTrait(Model):
    set_number: PositiveInt
    api_name: Identifier
    name_ko: str | None
    breakpoints: tuple[PositiveInt, ...]
    desc_ko: str | None

    @field_validator("breakpoints")
    @classmethod
    def distinct_breakpoints(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        # CDragon은 같은 인원 단계의 효과를 여러 행으로 내보내기도 한다.
        return tuple(sorted(set(value)))


class Alias(Model):
    alias: Identifier
    canonical_name_ko: Identifier
    type: EntityType


class IdMapping(Model):
    opgg_id: Identifier
    api_name: Identifier | None
    type: Literal["unit", "item"]
    name_ko: str | None
    match_method: Literal["auto", "override"]


class NameEntry(Model):
    id: Identifier
    api_name: str | None
    name_ko: Identifier
    type: EntityType


class SetRules(Model):
    set: PositiveInt
    shop_odds: dict[PositiveInt, tuple[float, ...]]
    pool_size: dict[PositiveInt, PositiveInt]
    champions_per_cost: dict[PositiveInt, PositiveInt]
    xp_to_next: dict[PositiveInt, PositiveInt | None]
    reroll_cost: PositiveInt
    xp_per_buy: PositiveInt
    xp_buy_cost: PositiveInt
    interest_cap: NonNegativeInt

    @model_validator(mode="after")
    def consistent_tables(self) -> Self:
        costs = set(self.pool_size)
        if not costs or costs != set(range(1, len(costs) + 1)):
            raise ValueError("pool_size의 코스트 키는 1부터 연속이어야 한다")
        if costs != set(self.champions_per_cost):
            raise ValueError("champions_per_cost와 pool_size의 코스트 키가 다르다")
        if not self.shop_odds or not self.xp_to_next:
            raise ValueError("shop_odds와 xp_to_next가 비어 있다")
        for level, odds in self.shop_odds.items():
            if len(odds) != len(costs):
                raise ValueError(f"shop_odds[{level}] 코스트 수가 pool_size와 다르다")
            if any(not math.isfinite(p) or p < 0 or p > 100 for p in odds):
                raise ValueError(f"shop_odds[{level}]에 잘못된 확률이 있다")
            if not math.isclose(sum(odds), 100.0, abs_tol=1e-8):
                raise ValueError(f"shop_odds[{level}]의 합이 100이 아니다")
        return self


class ResolveNamesInput(Model):
    words: list[Identifier]


class ResolvedName(Model):
    input: str
    id: str
    name_ko: str
    type: EntityType
    method: Literal["alias", "exact", "partial"]


class ResolveNamesResult(Model):
    matches: list[ResolvedName]
    unresolved: list[str]


class RerollOddsInput(Model):
    level: PositiveInt
    gold: NonNegativeInt
    unit_id: Identifier
    owned: NonNegativeInt
    target_star: Literal[1, 2, 3] = 3
    contested: NonNegativeInt | None = None


class RerollOddsResult(Model):
    unit_id: str
    name_ko: str
    p_hit: float = Field(ge=0, le=1)
    expected_gold_used: float = Field(ge=0)
    simulations: PositiveInt
    optimistic: bool


class LevelUpPlanInput(Model):
    level: PositiveInt
    xp: NonNegativeInt
    gold: NonNegativeInt


class LevelUpPlanResult(Model):
    cost_to_next: NonNegativeInt
    gold_after: int
    next_level_odds: dict[int, float]
    interest_after: NonNegativeInt
    affordable: bool


class CraftOptionsInput(Model):
    components: list[Identifier]


class CraftOption(Model):
    item_id: str
    name_ko: str
    uses: list[str]
    kind: str


class CraftOptionsResult(RootModel[list[CraftOption]]):
    pass


class CalcTraitsInput(Model):
    units: list[Identifier]
    emblems: list[Identifier] = Field(default_factory=list)


class TraitCount(Model):
    trait_id: str
    name_ko: str
    count: NonNegativeInt
    active_tier: NonNegativeInt
    next_breakpoint: PositiveInt | None
    need: NonNegativeInt


class CalcTraitsResult(RootModel[list[TraitCount]]):
    pass
