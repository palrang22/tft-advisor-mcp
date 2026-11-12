"""craft_options: 가진 재료로 만들 수 있는 완성템·상징 전부.

각 결과는 독립된 대안이다 (재료를 나눠 쓰는 동시 제작 계획이 아니다).
같은 재료가 두 번 필요한 조합은 그 재료를 두 개 가졌을 때만 나온다.
"""

from __future__ import annotations

from collections import Counter

from core.envelope import Envelope
from core.errors import InvalidInput
from core.models import CraftOption, CraftOptionsInput, CraftOptionsResult
from core.repo.base import Repository

CRAFTED_KINDS = frozenset({"completed", "emblem"})
RECIPE_SIZE = 2


def _preferred_ids(repo: Repository) -> dict[str, str]:
    """canonical apiName → 응답에 쓸 id. OP.GG id가 있으면 그것, 없으면 apiName."""
    candidates: dict[str, list[str]] = {}
    for entry in repo.names:
        if entry.type == "item" and entry.api_name is not None:
            candidates.setdefault(entry.api_name, []).append(entry.id)
    return {
        api: min(ids, key=lambda i: (i == api, i))  # apiName과 다른 id(=OP.GG id) 우선
        for api, ids in candidates.items()
    }


def craft_options(inp: CraftOptionsInput, repo: Repository) -> Envelope[CraftOptionsResult]:
    inventory: Counter[str] = Counter()
    for identifier in inp.components:
        item = repo.item(identifier)
        if item.kind != "component":
            raise InvalidInput(
                f"{identifier}은(는) 재료가 아니다 (kind={item.kind}). 기본 재료 ID만 넣는다."
            )
        inventory[item.api_name] += 1

    ids = _preferred_ids(repo)

    def out_id(api_name: str) -> str:
        return ids.get(api_name, api_name)

    options: list[CraftOption] = []
    for item in repo.items.values():
        if item.kind not in CRAFTED_KINDS or len(item.components) != RECIPE_SIZE:
            continue
        needed = Counter(item.components)
        if any(inventory[component] < count for component, count in needed.items()):
            continue
        options.append(
            CraftOption(
                item_id=out_id(item.api_name),
                name_ko=item.name_ko or out_id(item.api_name),
                uses=[out_id(c) for c in item.components],
                kind=item.kind,
            )
        )
    options.sort(key=lambda o: (o.kind, o.name_ko, o.item_id))

    notes: list[str] = []
    if len(options) > 1:
        notes.append("각 항목은 독립된 대안이다. 재료가 겹치면 동시에 전부 만들 수 없다.")
    return Envelope[CraftOptionsResult](
        source="calc",
        set_number=repo.set_number,
        results=CraftOptionsResult(options),
        notes=notes,
    )
