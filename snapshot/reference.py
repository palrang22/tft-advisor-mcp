"""static 적재에 필요한 OP.GG 기준 데이터만 받는다: `list_tools()`(ID enum)와 조합식(`ko_KR`).

    uv run python -m snapshot.reference

저장: `SNAPSHOT_DIR/<오늘 KST>/list_tools.json`, `tft_list_item_combinations__ko_KR.json`.
`static.loader`는 이 두 파일이 있는 가장 최근 날짜 폴더를 읽는다.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from common.config import Settings, get_settings
from common.log import setup_logging
from snapshot.opgg import OpggClient
from snapshot.store import (
    ITEM_COMBINATIONS,
    LIST_TOOLS_FILE,
    response_file,
    snapshot_path,
    today_kst,
)

logger = logging.getLogger(__name__)


async def fetch_reference(settings: Settings) -> Path:
    out_dir = snapshot_path(settings.snapshot_dir, today_kst())
    out_dir.mkdir(parents=True, exist_ok=True)
    async with OpggClient(settings) as client:
        tools = await client.list_tools()
        (out_dir / LIST_TOOLS_FILE).write_text(
            json.dumps(tools, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        tool, lang = ITEM_COMBINATIONS
        text = await client.call_tool(tool, {"lang": lang})
        (out_dir / response_file(tool, lang)).write_text(text, encoding="utf-8")
    logger.info("saved OP.GG reference data to %s", out_dir)
    return out_dir


def main() -> None:
    setup_logging()
    asyncio.run(fetch_reference(get_settings()))


if __name__ == "__main__":
    main()
