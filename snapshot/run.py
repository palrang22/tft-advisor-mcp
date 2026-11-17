"""OP.GG MCP 일일 스냅샷.

    uv run python -m snapshot.run --date today [--load]
    uv run python -m snapshot.run --date 2026-11-12 --load   # 저장된 스냅샷만 다시 적재

순서: 메타 덱 → (갱신 확인) → `list_tools` → 조합식·증강 → 챔피언 빌드 전체 → 템별 챔피언.

- 메타 덱의 `gameStatDateTime`이 지난 스냅샷(끝까지 받았고 실패 0건)과 같으면 나머지를 안 부른다.
- 같은 날 같은 `gameStatDateTime`으로 다시 실행하면 성공한 호출은 건너뛰고 실패분만 받는다.
- 호출 실패는 `status=error`로 manifest에 남기고 계속 간다. 메타 덱·`list_tools` 실패만 중단한다.
- 오늘이 아닌 날짜는 OP.GG를 부르지 않는다. 저장된 스냅샷을 `--load`로 적재만 한다.

저장: `SNAPSHOT_DIR/YYYY-MM-DD/<tool>__<arg>.json`, `list_tools.json`, `manifest.json`.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Any, Protocol

from common.config import Settings, get_settings
from common.log import setup_logging
from snapshot.bq import load_snapshot
from snapshot.opgg import OpggClient
from snapshot.plan import META_DECKS, Call, enum_calls, fixed_calls
from snapshot.store import (
    ITEM_COMBINATIONS,
    LIST_TOOLS_FILE,
    MANIFEST_FILE,
    latest_file,
    read_manifest,
    response_file,
    snapshot_path,
    today_kst,
    write_manifest,
)
from static.opgg_ref import read_item_kinds

logger = logging.getLogger(__name__)

# 연속으로 이만큼 실패하면 남은 호출은 부르지 않고 error로만 남긴다 (죽은 서버를 두드리지 않는다).
MAX_CONSECUTIVE_FAILURES = 5
PROGRESS_EVERY = 20
NOISY_LOGGERS = ("httpx2", "mcp.client.streamable_http")


class OpggApi(Protocol):
    async def list_tools(self) -> dict[str, Any]: ...

    async def call_tool(self, tool: str, args: dict[str, Any] | None = None) -> str: ...


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def _entry(call: Call, status: str, error: str | None = None) -> dict[str, Any]:
    return {
        "tool": call.tool,
        "args": dict(call.args),
        "file": call.file,
        "status": status,
        "error": error,
        "fetched_at": _now(),
    }


def _counts(entries: list[dict[str, Any]]) -> dict[str, int]:
    ok = sum(e["status"] == "ok" for e in entries)
    return {"total": len(entries), "ok": ok, "error": len(entries) - ok}


def _is_clean(manifest: dict[str, Any]) -> bool:
    """끝까지 받았고 실패가 없다."""
    return manifest["finished_at"] is not None and manifest["counts"]["error"] == 0


def _already_have(settings: Settings, source_updated_at: str) -> str | None:
    """같은 OP.GG 집계를 끝까지(실패 0건) 받은 지난 스냅샷이 있으면 그 날짜."""
    path = latest_file(settings.snapshot_dir, MANIFEST_FILE)
    last = read_manifest(path.parent) if path else None
    if last is not None and last["source_updated_at"] == source_updated_at and _is_clean(last):
        return last["snapshot_date"]
    return None


def _item_kinds(settings: Settings) -> dict[str, str]:
    """가장 최근 조합식 파일의 아이템 분류. 오늘 조합식 호출이 실패했으면 지난 파일을 쓴다."""
    path = latest_file(settings.snapshot_dir, response_file(*ITEM_COMBINATIONS))
    if path is None:
        logger.warning("조합식 파일이 없어 아이템을 분류할 수 없다. 템별 챔피언은 받지 않는다")
        return {}
    logger.info("item categories from %s", path)
    return read_item_kinds(json.loads(path.read_text(encoding="utf-8")), settings.tft_set)


async def take_snapshot(
    connect: Callable[[], AbstractAsyncContextManager[OpggApi]], settings: Settings, date: dt.date
) -> dict[str, Any] | None:
    """`date` 폴더에 스냅샷을 받고 manifest를 돌려준다. OP.GG 갱신이 없어 건너뛰면 None.

    그날 스냅샷을 이미 끝까지(실패 0건) 받았으면 OP.GG에 연결하지 않고 그 manifest를 돌려준다
    (OP.GG 집계는 매시 바뀌지만 스냅샷은 하루 1회다).
    """
    done = read_manifest(snapshot_path(settings.snapshot_dir, date))
    if done is not None and _is_clean(done):
        logger.info("%s 스냅샷은 이미 끝까지 받았다. OP.GG를 부르지 않는다", date)
        return done
    async with connect() as client:
        return await _fetch_snapshot(client, settings, date)


async def _fetch_snapshot(
    client: OpggApi, settings: Settings, date: dt.date
) -> dict[str, Any] | None:
    out_dir = snapshot_path(settings.snapshot_dir, date)
    started_at = _now()

    meta = Call(META_DECKS)
    meta_text = await client.call_tool(meta.tool)
    source_updated_at: str = json.loads(meta_text)["metadata"]["gameStatDateTime"]

    reusable: dict[str, dict[str, Any]] = {}
    today = read_manifest(out_dir)
    if today is not None and today["source_updated_at"] == source_updated_at:
        reusable = {
            e["file"]: e
            for e in today["calls"]
            if e["status"] == "ok" and (out_dir / e["file"]).is_file()
        }
    else:
        have = _already_have(settings, source_updated_at)
        if have is not None:
            logger.info(
                "OP.GG 갱신 없음 (gameStatDateTime=%s, %s 스냅샷과 같음). 종료",
                source_updated_at,
                have,
            )
            return None

    out_dir.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, Any]] = []
    manifest: dict[str, Any] = {
        "snapshot_date": date.isoformat(),
        "source_updated_at": source_updated_at,
        "set": settings.tft_set,
        "client_app": settings.opgg_client_app,
        "started_at": started_at,
        "finished_at": None,
        "counts": _counts(entries),
        "calls": entries,
    }
    failures_in_a_row = 0

    def save(call: Call, text: str) -> None:
        (out_dir / call.file).write_text(text, encoding="utf-8")
        entries.append(_entry(call, "ok"))

    async def fetch(call: Call) -> None:
        nonlocal failures_in_a_row
        if call.file in reusable:
            entries.append(reusable[call.file])
            return
        if failures_in_a_row >= MAX_CONSECUTIVE_FAILURES:
            entries.append(
                _entry(call, "error", f"건너뜀: 앞선 호출이 연속 {MAX_CONSECUTIVE_FAILURES}회 실패")
            )
            return
        try:
            text = await client.call_tool(call.tool, dict(call.args))
        except Exception as exc:  # 전송·툴·파싱 오류 종류와 무관하게 기록하고 다음 호출로 간다
            failures_in_a_row += 1
            logger.warning("%s %s failed: %r", call.tool, dict(call.args), exc)
            entries.append(_entry(call, "error", repr(exc)))
        else:
            failures_in_a_row = 0
            save(call, text)

    try:
        save(meta, meta_text)
        tools = await client.list_tools()
        (out_dir / LIST_TOOLS_FILE).write_text(
            json.dumps(tools, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        for call in fixed_calls():
            await fetch(call)
        calls = enum_calls(tools, _item_kinds(settings))
        logger.info("%d enum calls planned (%d reusable)", len(calls), len(reusable))
        for i, call in enumerate(calls, start=1):
            await fetch(call)
            if i % PROGRESS_EVERY == 0 or i == len(calls):
                logger.info("progress %d/%d %s", i, len(calls), _counts(entries))
        manifest["finished_at"] = _now()
    finally:
        manifest["counts"] = _counts(entries)
        write_manifest(out_dir, manifest)

    logger.info("snapshot %s saved to %s: %s", date, out_dir, manifest["counts"])
    return manifest


def _parse_date(value: str) -> dt.date:
    return today_kst() if value == "today" else dt.date.fromisoformat(value)


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m snapshot.run")
    parser.add_argument("--date", type=_parse_date, default="today", help="today 또는 YYYY-MM-DD")
    parser.add_argument("--load", action="store_true", help="BigQuery raw_opgg에 적재")
    args = parser.parse_args()
    settings = get_settings()
    setup_logging()
    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

    if args.date == today_kst():
        manifest = asyncio.run(take_snapshot(lambda: OpggClient(settings), settings, args.date))
        if manifest is None:
            return
    elif not args.load:
        parser.error(
            "오늘이 아닌 날짜는 OP.GG에서 받을 수 없다. 저장된 스냅샷을 --load로 적재만 한다"
        )
    if args.load:
        load_snapshot(settings, snapshot_path(settings.snapshot_dir, args.date))


if __name__ == "__main__":
    main()
