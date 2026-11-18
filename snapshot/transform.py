"""clean·mart SQL 실행.

    uv run python -m snapshot.transform [--date YYYY-MM-DD]

- `sql/clean/<table>.sql` → 그날 `snapshot_date` 파티션을 통째로 바꾼다 (재실행해도 중복 없음).
- `sql/mart/<table>.sql` → 테이블 전체를 그날 데이터로 바꾼다. `--date`가 `raw_opgg`의 최신
  날짜일 때만 만든다 (mart는 최신 스냅샷 기준).
- `--date`를 안 주면 `raw_opgg`의 최신 날짜.

SQL은 데이터셋 이름 없이 테이블 이름만 쓴다(기본 데이터셋). 쓸 수 있는 매개변수:
`@snapshot_date`(DATE), `@set_number`(INT64, `TFT_SET`), `@low_sample_n`(INT64, `LOW_SAMPLE_N`).
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
from dataclasses import dataclass
from pathlib import Path

from google.api_core.exceptions import NotFound, ServerError, TooManyRequests
from google.cloud import bigquery

from common.config import ROOT_DIR, Settings, get_settings
from common.log import setup_logging
from common.retry import RetryPolicy, retry_call
from snapshot.bq import RAW_TABLE
from static.bq import POLICY

logger = logging.getLogger(__name__)

SQL_DIR = ROOT_DIR / "sql"
STAGES = ("clean", "mart")
RETRY_ON = (ServerError, TooManyRequests, OSError)


@dataclass(frozen=True)
class Step:
    stage: str
    table: str
    sql: str


def load_steps(sql_dir: Path = SQL_DIR) -> list[Step]:
    """clean 전부 → mart 전부. 같은 단계 안의 SQL은 서로 의존하지 않는다."""
    return [
        Step(stage, path.stem, path.read_text(encoding="utf-8"))
        for stage in STAGES
        for path in sorted((sql_dir / stage).glob("*.sql"))
    ]


def raw_dates(client: bigquery.Client, table_id: str) -> list[dt.date]:
    """`raw_opgg`에 적재된 `snapshot_date` 파티션 날짜 (오름차순)."""
    partitions = [p for p in client.list_partitions(table_id) if p.isdigit()]
    return sorted(dt.datetime.strptime(p, "%Y%m%d").date() for p in partitions)


def _job_config(
    client: bigquery.Client, step: Step, table_id: str, date: dt.date, settings: Settings
) -> tuple[str, bigquery.QueryJobConfig]:
    config = bigquery.QueryJobConfig(
        default_dataset=f"{settings.gcp_project}.{settings.bq_dataset}",
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        query_parameters=[
            bigquery.ScalarQueryParameter("snapshot_date", "DATE", date),
            bigquery.ScalarQueryParameter("set_number", "INT64", settings.tft_set),
            bigquery.ScalarQueryParameter("low_sample_n", "INT64", settings.low_sample_n),
        ],
    )
    if step.stage == "mart":
        return table_id, config

    config.time_partitioning = bigquery.TimePartitioning(
        type_=bigquery.TimePartitioningType.DAY, field="snapshot_date"
    )
    try:
        client.get_table(table_id)
    except NotFound:
        return table_id, config  # 처음에는 테이블을 만든다 (결과가 그날 하루치뿐이다)
    # 있으면 그날 파티션만 바꾼다. 다른 날짜 행이 섞이면 BigQuery가 실패시킨다.
    config.schema_update_options = [bigquery.SchemaUpdateOption.ALLOW_FIELD_ADDITION]
    return f"{table_id}${date:%Y%m%d}", config


def run_step(
    client: bigquery.Client,
    step: Step,
    date: dt.date,
    settings: Settings,
    policy: RetryPolicy = POLICY,
) -> int:
    table_id = f"{settings.gcp_project}.{settings.bq_dataset}.{step.table}"

    def once(timeout: float) -> int:
        destination, config = _job_config(client, step, table_id, date, settings)
        config.destination = destination
        job = client.query(step.sql, job_config=config, timeout=timeout)
        return job.result(timeout=timeout).total_rows or 0

    rows = retry_call(once, retry_on=RETRY_ON, policy=policy, name=f"bq {step.table}")
    logger.info("%s.%s: %d rows (%s)", step.stage, step.table, rows, date)
    return rows


def run_transform(
    settings: Settings, date: dt.date | None = None, policy: RetryPolicy = POLICY
) -> dict[str, int]:
    """clean(그날 파티션)과 mart(최신 날짜일 때)를 만들고 테이블별 행 수를 돌려준다."""
    if not settings.gcp_project:
        raise ValueError("GCP_PROJECT가 비어 있다 (.env)")
    client = bigquery.Client(project=settings.gcp_project, location=settings.bq_location)
    raw_id = f"{settings.gcp_project}.{settings.bq_dataset}.{RAW_TABLE}"
    dates = retry_call(
        lambda _timeout: raw_dates(client, raw_id),
        retry_on=RETRY_ON,
        policy=policy,
        name="bq raw partitions",
    )
    if not dates:
        raise ValueError(f"{raw_id}에 적재된 스냅샷이 없다. 먼저 snapshot.run --load")
    latest = dates[-1]
    date = date or latest
    if date not in dates:
        raise ValueError(f"{date} 스냅샷이 {raw_id}에 없다 (적재된 날짜: {dates[0]}~{latest})")

    counts: dict[str, int] = {}
    for step in load_steps():
        if step.stage == "mart" and date != latest:
            logger.info("mart.%s: 건너뜀 (%s는 최신 날짜 %s가 아니다)", step.table, date, latest)
            continue
        counts[step.table] = run_step(client, step, date, settings, policy)
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m snapshot.transform")
    parser.add_argument(
        "--date",
        type=dt.date.fromisoformat,
        default=None,
        help="YYYY-MM-DD (기본: raw_opgg 최신 날짜)",
    )
    args = parser.parse_args()
    settings = get_settings()
    setup_logging()
    run_transform(settings, args.date)


if __name__ == "__main__":
    main()
