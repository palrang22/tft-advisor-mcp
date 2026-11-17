"""일일 스냅샷 잡 테스트. OP.GG는 부르지 않는다.

가짜 클라이언트가 Phase 1 fixture(`list_tools`, 메타 덱, 조합식)를 돌려준다. 나머지 툴은 빈 배열.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
from pathlib import Path
from typing import Any

import pytest

from common.config import Settings
from snapshot import run
from snapshot.bq import raw_rows
from snapshot.opgg import OpggToolError
from snapshot.plan import enum_calls
from snapshot.store import read_manifest
from static.opgg_ref import read_item_kinds

FIX = Path(__file__).parent / "fixtures" / "opgg"
LIST_TOOLS = json.loads((FIX / "list_tools.json").read_text(encoding="utf-8"))
META_TEXT = (FIX / "tft_list_meta_decks.json").read_text(encoding="utf-8")
COMBOS_TEXT = (FIX / "tft_list_item_combinations__ko_KR.json").read_text(encoding="utf-8")
SOURCE_UPDATED_AT = json.loads(META_TEXT)["metadata"]["gameStatDateTime"]

DAY = dt.date(2026, 11, 13)
SIVIR = "tft_get_champion_item_build__DA_18_Sivir.json"
JUGGERNAUT = "tft_list_champions_for_item__DA_18_EmblemJuggernaut.json"


class FakeClient:
    """`fail`에 든 ID(인자 값)의 호출은 실패한다. `meta_text`로 OP.GG 갱신을 흉내 낸다."""

    def __init__(self, fail: set[str] | None = None, meta_text: str = META_TEXT) -> None:
        self.fail = fail or set()
        self.meta_text = meta_text
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.connections = 0

    async def __aenter__(self) -> FakeClient:
        self.connections += 1
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def list_tools(self) -> dict[str, Any]:
        return LIST_TOOLS

    async def call_tool(self, tool: str, args: dict[str, Any] | None = None) -> str:
        args = args or {}
        self.calls.append((tool, args))
        if self.fail & set(args.values()):
            raise OpggToolError(f"{tool} failed")
        if tool == "tft_list_meta_decks":
            return self.meta_text
        if tool == "tft_list_item_combinations":
            return COMBOS_TEXT
        return "[]"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(snapshot_dir=tmp_path / "snapshots", cache_dir=tmp_path / "cache")


def snap(client: FakeClient, settings: Settings, day: dt.date = DAY) -> dict[str, Any] | None:
    return asyncio.run(run.take_snapshot(lambda: client, settings, day))


def updated_meta(stamp: str) -> str:
    data = json.loads(META_TEXT)
    data["metadata"]["gameStatDateTime"] = stamp
    return json.dumps(data)


def enum_ids(tool: str, prop: str) -> list[str]:
    spec = next(t for t in LIST_TOOLS["tools"] if t["name"] == tool)
    return spec["inputSchema"]["properties"][prop]["enum"]


def test_call_list_covers_enum_and_skips_radiant_and_potions() -> None:
    calls = enum_calls(LIST_TOOLS, read_item_kinds(json.loads(COMBOS_TEXT), 18))
    champions = [c.args["champion_id"] for c in calls if "champion_id" in c.args]
    items = [c.args["item_id"] for c in calls if "item_id" in c.args]

    # 챔피언은 enum 전체 (CDragon에 없는 형태·소환물 포함)
    assert len(champions) == 77
    assert {"DA_18_Sivir", "DA_Gromp18_AD", "TFT18_SprykinSummonMelee"} <= set(champions)
    # 아이템: 상징 21 + 재료 10 + 일반 완성템 39 + 유물 30
    assert len(items) == 100
    assert {
        "DA_18_EmblemJuggernaut",
        "DA_Component_BFSword",
        "DA_InfinityEdge",
        "DA_Artifact_AegisOfDawn",
    } <= set(items)
    assert not {"DA_AdaptiveHelm_Radiant", "DA_HealthPotion18"} & set(items)


def test_snapshot_saves_responses_and_records_failures(settings: Settings) -> None:
    client = FakeClient(fail={"DA_18_Sivir"})
    manifest = snap(client, settings)
    folder = settings.snapshot_dir / "2026-11-13"

    assert manifest is not None
    assert client.calls[0] == ("tft_list_meta_decks", {})  # 메타 덱이 먼저
    assert manifest == read_manifest(folder)
    # 메타 덱 1 + 조합식 1 + 증강 1 + 챔피언 77 + 아이템 100
    assert manifest["counts"] == {"total": 180, "ok": 179, "error": 1}
    assert manifest["source_updated_at"] == SOURCE_UPDATED_AT
    assert manifest["finished_at"] is not None

    by_file = {c["file"]: c for c in manifest["calls"]}
    assert by_file[SIVIR]["status"] == "error"
    assert "failed" in by_file[SIVIR]["error"]
    assert not (folder / SIVIR).exists()
    # 실패 뒤에도 계속 진행한다
    assert by_file[JUGGERNAUT]["status"] == "ok"
    assert by_file[JUGGERNAUT]["args"] == {"item_id": "DA_18_EmblemJuggernaut"}
    assert (folder / JUGGERNAUT).read_text(encoding="utf-8") == "[]"
    assert (folder / "tft_list_meta_decks.json").read_text(encoding="utf-8") == META_TEXT
    assert json.loads((folder / "list_tools.json").read_text(encoding="utf-8")) == LIST_TOOLS


def test_unchanged_source_skips_everything_after_meta_decks(settings: Settings) -> None:
    assert snap(FakeClient(), settings, dt.date(2026, 11, 12)) is not None

    client = FakeClient()
    assert snap(client, settings, DAY) is None
    assert client.calls == [("tft_list_meta_decks", {})]
    assert not (settings.snapshot_dir / "2026-11-13").exists()


def test_updated_source_takes_new_snapshot(settings: Settings) -> None:
    assert snap(FakeClient(), settings, dt.date(2026, 11, 12)) is not None

    stamp = "2026-11-13T04:59:23.000Z"
    manifest = snap(FakeClient(meta_text=updated_meta(stamp)), settings, DAY)
    assert manifest is not None
    assert manifest["source_updated_at"] == stamp
    assert manifest["counts"]["ok"] == 180


def test_previous_snapshot_with_failures_does_not_block_today(settings: Settings) -> None:
    # 어제 스냅샷에 실패가 있었다면, 집계가 같아도 오늘 다시 받는다
    assert snap(FakeClient(fail={"DA_18_Sivir"}), settings, dt.date(2026, 11, 12)) is not None

    manifest = snap(FakeClient(), settings, DAY)
    assert manifest is not None
    assert manifest["counts"] == {"total": 180, "ok": 180, "error": 0}


def test_rerun_same_day_retries_only_failed_calls(settings: Settings) -> None:
    snap(FakeClient(fail={"DA_18_Sivir", "DA_InfinityEdge"}), settings)

    client = FakeClient()
    manifest = snap(client, settings)
    assert manifest is not None
    assert sorted(client.calls, key=str) == sorted(
        [
            ("tft_list_meta_decks", {}),
            ("tft_get_champion_item_build", {"champion_id": "DA_18_Sivir"}),
            ("tft_list_champions_for_item", {"item_id": "DA_InfinityEdge"}),
        ],
        key=str,
    )
    assert manifest["counts"] == {"total": 180, "ok": 180, "error": 0}


def test_complete_snapshot_is_not_refetched_even_after_source_update(settings: Settings) -> None:
    first = snap(FakeClient(), settings)

    # OP.GG 집계는 매시 바뀐다. 오늘 치를 끝까지 받았으면 연결조차 하지 않는다 (하루 1회)
    client = FakeClient(meta_text=updated_meta("2026-11-13T05:59:23.000Z"))
    assert snap(client, settings) == first
    assert client.connections == 0
    assert client.calls == []


def test_failed_snapshot_is_refetched_whole_when_source_updated(settings: Settings) -> None:
    snap(FakeClient(fail={"DA_18_Sivir"}), settings)

    # 집계 시각이 달라졌으면 지난 응답과 섞지 않고 전부 다시 받는다
    client = FakeClient(meta_text=updated_meta("2026-11-13T05:59:23.000Z"))
    manifest = snap(client, settings)
    assert manifest is not None
    assert len(client.calls) == 180
    assert manifest["source_updated_at"] == "2026-11-13T05:59:23.000Z"
    assert manifest["counts"]["error"] == 0


def test_stops_calling_after_consecutive_failures(settings: Settings) -> None:
    every_champion = set(enum_ids("tft_get_champion_item_build", "champion_id"))
    client = FakeClient(fail=every_champion)
    manifest = snap(client, settings)

    assert manifest is not None
    champion_calls = [c for c in client.calls if c[0] == "tft_get_champion_item_build"]
    assert len(champion_calls) == run.MAX_CONSECUTIVE_FAILURES
    # 부르지 않은 호출도 전부 error로 남는다 (챔피언 77 + 아이템 100)
    assert manifest["counts"] == {"total": 180, "ok": 3, "error": 177}
    assert not [c for c in client.calls if c[0] == "tft_list_champions_for_item"]


def test_meta_decks_failure_aborts_without_snapshot(settings: Settings) -> None:
    class Down(FakeClient):
        async def call_tool(self, tool: str, args: dict[str, Any] | None = None) -> str:
            raise OpggToolError("down")

    with pytest.raises(OpggToolError):
        snap(Down(), settings)
    assert not (settings.snapshot_dir / "2026-11-13").exists()


def test_raw_rows_carry_payload_and_errors(settings: Settings) -> None:
    manifest = snap(FakeClient(fail={"DA_18_Sivir"}), settings)
    assert manifest is not None
    rows = raw_rows(settings.snapshot_dir / "2026-11-13", manifest)
    by_key = {(r["tool"], json.dumps(r["args"], sort_keys=True)): r for r in rows}

    assert len(rows) == 180
    assert {r["snapshot_date"] for r in rows} == {"2026-11-13"}
    assert {r["source_updated_at"] for r in rows} == {SOURCE_UPDATED_AT}

    meta = by_key[("tft_list_meta_decks", "{}")]
    assert meta["payload"] == META_TEXT
    assert meta["status"] == "ok" and meta["error"] is None

    failed = by_key[("tft_get_champion_item_build", '{"champion_id": "DA_18_Sivir"}')]
    assert failed["payload"] is None
    assert failed["status"] == "error" and failed["error"]

    combos = by_key[("tft_list_item_combinations", '{"lang": "ko_KR"}')]
    assert combos["payload"] == COMBOS_TEXT
