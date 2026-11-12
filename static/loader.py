"""static 적재: CDragon + OP.GG 기준 데이터(스냅샷 파일) + rules/*.yaml → static 캐시 + BigQuery.

    uv run python -m snapshot.reference          # OP.GG list_tools·조합식 스냅샷 (먼저 1회)
    uv run python -m static.loader --set 18 [--no-bigquery]

출력:
- `CACHE_DIR/static_{units,traits,items,augments,aliases,id_map}.json`
- `CACHE_DIR/unmatched_ids.txt` (사람이 `rules/id_overrides.yaml`에 채울 목록)
- BigQuery `static_*` (WRITE_TRUNCATE)
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from common.config import ROOT_DIR, Settings, get_settings
from common.log import setup_logging
from snapshot.store import ITEM_COMBINATIONS, LIST_TOOLS_FILE, latest_file, response_file
from static import aliases as aliases_mod
from static import bq, cdragon, id_map, opgg_ref

logger = logging.getLogger(__name__)

ALIASES_PATH = ROOT_DIR / "rules" / "aliases.yaml"
OVERRIDES_PATH = ROOT_DIR / "rules" / "id_overrides.yaml"
UNMATCHED_FILE = "unmatched_ids.txt"


@dataclass(frozen=True)
class StaticBuild:
    tables: dict[str, list[Any]]
    unmatched: list[id_map.Unmatched]
    emblem_failures: list[cdragon.EmblemFailure]


def build_static(
    set_number: int,
    cdragon_data: dict[str, Any],
    list_tools: dict[str, Any],
    combinations: dict[str, Any],
    aliases_path: Path = ALIASES_PATH,
    overrides_path: Path = OVERRIDES_PATH,
) -> StaticBuild:
    overrides = id_map.load_overrides(overrides_path)
    set_data = cdragon.select_set(cdragon_data, set_number)

    units = cdragon.build_units(set_data, set_number)
    traits = cdragon.build_traits(set_data, set_number)
    items, emblem_failures = cdragon.build_items(
        cdragon_data,
        set_data,
        set_number,
        kinds=opgg_ref.read_item_kinds(combinations, set_number),
        emblem_overrides=overrides.emblem_traits,
    )
    augments = cdragon.build_augments(cdragon_data, set_data, set_number)

    id_rows, unmatched = id_map.build_id_map(
        opgg_ref.read_enums(list_tools),
        {
            "unit": {u["api_name"]: u["name_ko"] for u in units},
            "item": {i["api_name"]: i["name_ko"] for i in items},
        },
        overrides.ids,
    )

    alias_rows = aliases_mod.load_aliases(aliases_path)
    for bad in aliases_mod.unknown_canonicals(
        alias_rows,
        {
            "unit": {u["name_ko"] for u in units if u["name_ko"]},
            "item": {i["name_ko"] for i in items if i["name_ko"]},
            "trait": {t["name_ko"] for t in traits if t["name_ko"]},
        },
    ):
        logger.warning(
            "aliases.yaml: %s → '%s'가 세트 %s %s 이름에 없다",
            bad["alias"],
            bad["canonical_name_ko"],
            set_number,
            bad["type"],
        )

    return StaticBuild(
        tables={
            "static_units": units,
            "static_traits": traits,
            "static_items": items,
            "static_augments": augments,
            "static_aliases": alias_rows,
            "static_id_map": id_rows,
        },
        unmatched=unmatched,
        emblem_failures=emblem_failures,
    )


def write_cache(cache_dir: Path, build: StaticBuild, set_number: int) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    for table, rows in build.tables.items():
        (cache_dir / f"{table}.json").write_text(
            json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )
    id_map.write_unmatched(
        cache_dir / UNMATCHED_FILE, set_number, build.unmatched, build.emblem_failures
    )


def _read_latest(settings: Settings, name: str) -> dict[str, Any]:
    path = latest_file(settings.snapshot_dir, name)
    if path is None:
        raise SystemExit(
            f"{settings.snapshot_dir}/<날짜>/{name}이 없다. "
            "먼저 `uv run python -m snapshot.reference`를 실행한다."
        )
    logger.info("using %s", path)
    return json.loads(path.read_text(encoding="utf-8"))


def run(settings: Settings, set_number: int, load_bigquery: bool) -> StaticBuild:
    list_tools = _read_latest(settings, LIST_TOOLS_FILE)
    combinations = _read_latest(settings, response_file(*ITEM_COMBINATIONS))
    logger.info("fetching %s", settings.cdragon_url)
    build = build_static(set_number, cdragon.fetch(settings.cdragon_url), list_tools, combinations)

    write_cache(settings.cache_dir, build, set_number)
    for table, rows in build.tables.items():
        logger.info("%s: %d rows", table, len(rows))
    logger.info(
        "unmatched: ids %d, emblem_traits %d → %s",
        len(build.unmatched),
        len(build.emblem_failures),
        settings.cache_dir / UNMATCHED_FILE,
    )
    if load_bigquery:
        bq.load_tables(settings, build.tables)
    return build


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(prog="python -m static.loader")
    parser.add_argument("--set", type=int, default=settings.tft_set, dest="set_number")
    parser.add_argument("--no-bigquery", action="store_true", help="캐시 파일만 쓴다")
    args = parser.parse_args()
    setup_logging()
    run(settings, args.set_number, load_bigquery=not args.no_bigquery)


if __name__ == "__main__":
    main()
