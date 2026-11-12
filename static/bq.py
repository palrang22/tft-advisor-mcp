"""static_* 테이블 BigQuery 적재. 배치 로드 + WRITE_TRUNCATE (테이블 전체를 새 값으로 바꾼다)."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any

from google.api_core.exceptions import ServerError, TooManyRequests
from google.cloud import bigquery

from common.config import Settings
from common.retry import RetryPolicy, retry_call

logger = logging.getLogger(__name__)

POLICY = RetryPolicy(timeout=300.0, attempts=4, base_delay=2.0, max_delay=30.0)

F = bigquery.SchemaField

SCHEMAS: dict[str, list[bigquery.SchemaField]] = {
    "static_units": [
        F("set_number", "INT64", mode="REQUIRED"),
        F("api_name", "STRING", mode="REQUIRED"),
        F("name_ko", "STRING"),
        F("cost", "INT64"),
        F("traits", "STRING", mode="REPEATED"),
        F("role", "STRING"),
    ],
    "static_traits": [
        F("set_number", "INT64", mode="REQUIRED"),
        F("api_name", "STRING", mode="REQUIRED"),
        F("name_ko", "STRING"),
        F("breakpoints", "INT64", mode="REPEATED"),
        F("desc_ko", "STRING"),
    ],
    "static_items": [
        F("set_number", "INT64", mode="REQUIRED"),
        F("api_name", "STRING", mode="REQUIRED"),
        F("name_ko", "STRING"),
        F("components", "STRING", mode="REPEATED"),
        F("kind", "STRING", mode="REQUIRED"),
        F("emblem_trait", "STRING"),
    ],
    "static_augments": [
        F("set_number", "INT64", mode="REQUIRED"),
        F("api_name", "STRING", mode="REQUIRED"),
        F("name_ko", "STRING"),
        F("desc_ko", "STRING"),
    ],
    "static_aliases": [
        F("alias", "STRING", mode="REQUIRED"),
        F("canonical_name_ko", "STRING", mode="REQUIRED"),
        F("type", "STRING", mode="REQUIRED"),
    ],
    "static_id_map": [
        F("opgg_id", "STRING", mode="REQUIRED"),
        F("api_name", "STRING"),  # CDragon에 대응 항목이 없으면 NULL
        F("type", "STRING", mode="REQUIRED"),
        F("name_ko", "STRING"),
        F("match_method", "STRING", mode="REQUIRED"),
    ],
}


def load_tables(
    settings: Settings,
    tables: Mapping[str, Sequence[Mapping[str, Any]]],
    policy: RetryPolicy = POLICY,
) -> None:
    if not settings.gcp_project:
        raise ValueError("GCP_PROJECT가 비어 있다 (.env)")
    client = bigquery.Client(project=settings.gcp_project, location=settings.bq_location)
    for table, rows in tables.items():
        table_id = f"{settings.gcp_project}.{settings.bq_dataset}.{table}"
        _load_one(client, table_id, SCHEMAS[table], [dict(r) for r in rows], policy)
        logger.info("loaded %d rows into %s", len(rows), table_id)


def _load_one(
    client: bigquery.Client,
    table_id: str,
    schema: list[bigquery.SchemaField],
    rows: list[dict[str, Any]],
    policy: RetryPolicy,
) -> None:
    job_config = bigquery.LoadJobConfig(
        schema=schema,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
    )

    def once(timeout: float) -> None:
        job = client.load_table_from_json(rows, table_id, job_config=job_config, timeout=timeout)
        job.result(timeout=timeout)

    retry_call(
        once,
        retry_on=(ServerError, TooManyRequests, OSError),
        policy=policy,
        name=f"bq load {table_id}",
    )
