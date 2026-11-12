"""calc_traits: 기물 + 상징 → 시너지 개수·활성 단계.

- 기물은 정식(canonical) 챔피언 단위로 한 번만 센다 (AD·AP 형태, 같은 기물 중복 입력 포함).
- 상징은 인스턴스마다 +1.
- 단계 정보가 없는 시너지는 값을 지어내지 않고 DataUnavailable.
"""

from __future__ import annotations

from collections import Counter

from core.envelope import Envelope
from core.errors import DataUnavailable, InvalidInput
from core.models import CalcTraitsInput, CalcTraitsResult, StaticUnit, TraitCount
from core.repo.base import Repository


def calc_traits(inp: CalcTraitsInput, repo: Repository) -> Envelope[CalcTraitsResult]:
    counts: Counter[str] = Counter()

    unique_units: dict[str, StaticUnit] = {}
    for identifier in inp.units:
        unit = repo.unit(identifier)
        unique_units[unit.api_name] = unit
    for unit in unique_units.values():
        counts.update(set(unit.traits))

    for identifier in inp.emblems:
        item = repo.item(identifier)
        if item.kind != "emblem":
            raise InvalidInput(f"{identifier}은(는) 상징이 아니다 (kind={item.kind}).")
        if item.emblem_trait is None:
            raise DataUnavailable(f"{identifier}: 상징이 올려 주는 시너지 정보가 없다.")
        counts[item.emblem_trait] += 1

    results: list[TraitCount] = []
    for trait_id in sorted(counts):
        trait = repo.traits.get(trait_id)
        if trait is None:
            raise DataUnavailable(f"시너지 {trait_id}의 정의가 static 데이터에 없다.")
        breakpoints = sorted(trait.breakpoints)
        if not breakpoints:
            raise DataUnavailable(
                f"시너지 {trait_id}({trait.name_ko})의 단계 정보(breakpoints)가 비어 있다."
            )
        count = counts[trait_id]
        next_breakpoint = next((b for b in breakpoints if b > count), None)
        results.append(
            TraitCount(
                trait_id=trait_id,
                name_ko=trait.name_ko or trait_id,
                count=count,
                active_tier=sum(1 for b in breakpoints if b <= count),
                next_breakpoint=next_breakpoint,
                need=next_breakpoint - count if next_breakpoint is not None else 0,
            )
        )

    notes: list[str] = []
    if inp.emblems:
        notes.append("상징은 해당 시너지가 없는 서로 다른 기물이 하나씩 착용한다고 가정한다.")
    return Envelope[CalcTraitsResult](
        source="calc",
        set_number=repo.set_number,
        results=CalcTraitsResult(results),
        notes=notes,
    )
