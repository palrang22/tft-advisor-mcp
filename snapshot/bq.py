"""스냅샷 폴더 → BigQuery `raw_opgg` 배치 로드.

`snapshot_date` 파티션 하나를 통째로 바꾼다(WRITE_TRUNCATE). 같은 날짜를 다시 적재해도 중복이 없다.
"""

from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path
from typing import Any

from google.api_core.exceptions import ServerError, TooManyRequests
from google.cloud import bigquery

from common.config import Settings
from common.retry import RetryPolicy, retry_call
from snapshot.store import read_manifest
from static.bq import POLICY, load_rows

logger = logging.getLogger(__name__)

RAW_TABLE = "raw_opgg"

F = bigquery.SchemaField

RAW_SCHEMA = [
    F("snapshot_date", "DATE", mode="REQUIRED"),
    F("fetched_at", "TIMESTAMP"),
    F("tool", "STRING", mode="REQUIRED"),
    F("args", "JSON"),
    F("payload", "STRING"),
    F("status", "STRING", mode="REQUIRED"),
    F("error", "STRING"),
    F("source_updated_at", "TIMESTAMP"),
]


def raw_rows(folder: Path, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """manifest의 호출 하나 = 행 하나. 성공한 호출은 저장된 응답 원문을 `payload`에 넣는다."""
    rows: list[dict[str, Any]] = []
    for call in manifest["calls"]:
        ok = call["status"] == "ok"
        rows.append(
            {
                "snapshot_date": manifest["snapshot_date"],
                "fetched_at": call["fetched_at"],
                "tool": call["tool"],
                "args": call["args"],
                "payload": (folder / call["file"]).read_text(encoding="utf-8") if ok else None,
                "status": call["status"],
                "error": call["error"],
                "source_updated_at": manifest["source_updated_at"],
            }
        )
    return rows


def load_snapshot(settings: Settings, folder: Path, policy: RetryPolicy = POLICY) -> int:
    """`folder`의 스냅샷을 `raw_opgg`에 적재하고 행 수를 돌려준다."""
    if not settings.gcp_project:
        raise ValueError("GCP_PROJECT가 비어 있다 (.env)")
    manifest = read_manifest(folder)
    if manifest is None:
        raise ValueError(f"{folder}에 manifest.json이 없다. 먼저 스냅샷을 받는다.")
    if manifest["finished_at"] is None:
        raise ValueError(f"{folder}의 스냅샷이 끝나지 않았다. 다시 실행해서 마저 받는다.")
    rows = raw_rows(folder, manifest)

    client = bigquery.Client(project=settings.gcp_project, location=settings.bq_location)
    table_id = f"{settings.gcp_project}.{settings.bq_dataset}.{RAW_TABLE}"
    table = bigquery.Table(table_id, schema=RAW_SCHEMA)
    table.time_partitioning = bigquery.TimePartitioning(
        type_=bigquery.TimePartitioningType.DAY, field="snapshot_date"
    )
    table.clustering_fields = ["tool"]
    retry_call(
        lambda timeout: client.create_table(table, exists_ok=True, timeout=timeout),
        retry_on=(ServerError, TooManyRequests, OSError),
        policy=policy,
        name=f"bq create {table_id}",
    )

    partition = dt.date.fromisoformat(manifest["snapshot_date"]).strftime("%Y%m%d")
    load_rows(client, f"{table_id}${partition}", RAW_SCHEMA, rows, policy)
    logger.info("loaded %d rows into %s (partition %s)", len(rows), table_id, partition)
    return len(rows)
