"""스냅샷 파일 배치: `SNAPSHOT_DIR/YYYY-MM-DD/<tool>__<arg>.json` (날짜는 KST)."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
LIST_TOOLS_FILE = "list_tools.json"
MANIFEST_FILE = "manifest.json"
ITEM_COMBINATIONS = ("tft_list_item_combinations", "ko_KR")  # (툴, lang)


def today_kst() -> dt.date:
    return dt.datetime.now(KST).date()


def snapshot_path(root: Path, date: dt.date) -> Path:
    return root / date.isoformat()


def response_file(tool: str, arg: str | None = None) -> str:
    """툴 응답 파일 이름. 인자가 없는 툴은 `<tool>.json`."""
    name = f"{tool}__{arg}.json" if arg else f"{tool}.json"
    if Path(name).name != name:
        raise ValueError(f"파일 이름으로 쓸 수 없는 툴·인자: {tool!r}, {arg!r}")
    return name


def read_manifest(folder: Path) -> dict[str, Any] | None:
    path = folder / MANIFEST_FILE
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_manifest(folder: Path, manifest: dict[str, Any]) -> None:
    (folder / MANIFEST_FILE).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )


def latest_file(root: Path, name: str) -> Path | None:
    """`name` 파일이 있는 가장 최근 날짜 폴더의 파일. 없으면 None."""
    if not root.is_dir():
        return None
    dated = sorted(
        (p for p in root.iterdir() if p.is_dir() and _is_date(p.name)),
        key=lambda p: p.name,
        reverse=True,
    )
    return next((p / name for p in dated if (p / name).is_file()), None)


def _is_date(name: str) -> bool:
    try:
        dt.date.fromisoformat(name)
    except ValueError:
        return False
    return True
