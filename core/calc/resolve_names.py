"""resolve_names: 줄임말·이름·부분 문자열 → ID.

순서: `aliases` → 한국어 이름(또는 알려진 id) 정확 일치 → 부분 일치.
앞 단계에서 하나라도 찾으면 거기서 멈추고, 그 단계의 후보를 전부 돌려준다 (모호하면 여러 개).
ID는 `repo.names`에 있는 값 그대로만 쓴다. 문자열 패턴으로 만들지 않는다.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import Literal

from core.envelope import Envelope
from core.models import NameEntry, ResolvedName, ResolveNamesInput, ResolveNamesResult
from core.repo.base import Repository

Method = Literal["alias", "exact", "partial"]


def _norm(text: str) -> str:
    """공백을 없애고 대소문자를 접는다. 이름 비교에만 쓴다."""
    return "".join(text.split()).casefold()


def _unique_sorted(entries: Iterable[NameEntry]) -> list[NameEntry]:
    seen: dict[tuple[str, str], NameEntry] = {}
    for e in entries:
        seen.setdefault((e.type, e.id), e)
    return sorted(seen.values(), key=lambda e: (e.type, e.name_ko, e.id))


class _Index:
    def __init__(self, repo: Repository) -> None:
        self.names = repo.names
        self.by_name: dict[str, list[NameEntry]] = defaultdict(list)
        self.by_typed_name: dict[tuple[str, str], list[NameEntry]] = defaultdict(list)
        self.by_id: dict[str, list[NameEntry]] = defaultdict(list)
        self.by_api: dict[str, list[NameEntry]] = defaultdict(list)
        for e in self.names:
            norm = _norm(e.name_ko)
            self.by_name[norm].append(e)
            self.by_typed_name[(e.type, norm)].append(e)
            self.by_id[e.id].append(e)
            if e.api_name is not None:
                self.by_api[e.api_name].append(e)
        self.aliases: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for a in repo.aliases:
            self.aliases[_norm(a.alias)].append((a.type, _norm(a.canonical_name_ko)))

    def lookup(self, word: str) -> tuple[Method, list[NameEntry]]:
        key = _norm(word)

        via_alias = _unique_sorted(
            e
            for kind, canonical in self.aliases.get(key, [])
            for e in self.by_typed_name.get((kind, canonical), [])
        )
        if via_alias:
            return "alias", via_alias

        # 이름이 같거나, 알려진 id(OP.GG id 우선, 없으면 정식 apiName)와 같은 것.
        exact = _unique_sorted(
            [*self.by_name.get(key, []), *(self.by_id.get(word) or self.by_api.get(word) or [])]
        )
        if exact:
            return "exact", exact

        return "partial", _unique_sorted(e for e in self.names if key in _norm(e.name_ko))


def resolve_names(inp: ResolveNamesInput, repo: Repository) -> Envelope[ResolveNamesResult]:
    index = _Index(repo)
    matches: list[ResolvedName] = []
    unresolved: list[str] = []
    ambiguous: list[str] = []

    for raw in inp.words:
        word = raw.strip()
        method, found = index.lookup(word)
        if not found:
            unresolved.append(word)
            continue
        if len(found) > 1:
            ambiguous.append(word)
        matches.extend(
            ResolvedName(input=word, id=e.id, name_ko=e.name_ko, type=e.type, method=method)
            for e in found
        )

    notes: list[str] = []
    if ambiguous:
        notes.append("후보가 여러 개인 입력(전부 반환): " + ", ".join(dict.fromkeys(ambiguous)))
    return Envelope[ResolveNamesResult](
        source="calc",
        set_number=repo.set_number,
        results=ResolveNamesResult(matches=matches, unresolved=unresolved),
        notes=notes,
    )
