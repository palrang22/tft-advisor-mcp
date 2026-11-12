"""환경 변수 로드. 코드에서 환경 변수를 읽는 곳은 이 파일 하나다.

우선순위: 프로세스 환경 변수 > 레포 루트 `.env` > 기본값.
경로 값은 상대 경로면 레포 루트 기준으로 푼다 (Claude Desktop처럼 cwd가 다른 곳에서 띄워도 같게).
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

ROOT_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT_DIR / ".env"


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True)

    # GCP
    gcp_project: str | None = None
    bq_dataset: str = "tft"
    bq_location: str = "asia-northeast3"

    # OP.GG MCP (스냅샷 잡에서만 사용)
    opgg_mcp_url: str = "https://mcp-api.op.gg/mcp"
    opgg_client_app: str = "tft-advisor-mcp-snapshot/0.1"
    opgg_call_interval_sec: float = 1.0

    # 세트 / 정적 데이터
    tft_set: int = 18
    cdragon_url: str = "https://raw.communitydragon.org/latest/cdragon/tft/ko_kr.json"

    # 통계 기준값
    low_sample_n: int = 100
    smoothing_k: int = 30

    # 로컬 경로
    snapshot_dir: Path = Path("data/snapshots")
    cache_dir: Path = Path("data/cache")

    # 서빙
    data_backend: Literal["bigquery", "cache"] = "bigquery"
    serve_port: int = 8080
    api_key: str | None = None
    cors_origins: tuple[str, ...] = ("http://localhost:3000",)
    mcp_rate_limit_per_min: int = 60

    # 로깅
    log_level: str = "INFO"

    @field_validator("opgg_call_interval_sec")
    @classmethod
    def _interval_at_least_one_sec(cls, v: float) -> float:
        if v < 1.0:
            raise ValueError("OPGG_CALL_INTERVAL_SEC는 1초 이상이어야 한다")
        return v

    @field_validator("snapshot_dir", "cache_dir")
    @classmethod
    def _resolve_from_root(cls, v: Path) -> Path:
        return v if v.is_absolute() else ROOT_DIR / v

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_csv(cls, v: object) -> object:
        if isinstance(v, str):
            return tuple(s.strip() for s in v.split(",") if s.strip())
        return v

    @field_validator("log_level")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()


def parse_env_file(path: Path) -> dict[str, str]:
    """`KEY=VALUE` 파일을 읽는다. 줄 주석, 값 뒤 ` #` 주석, 따옴표를 처리한다."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        elif value.startswith("#"):
            value = ""
        else:
            for sep in (" #", "\t#"):
                idx = value.find(sep)
                if idx != -1:
                    value = value[:idx].rstrip()
        values[key] = value
    return values


def load_settings(env: dict[str, str] | None = None, env_file: Path = ENV_FILE) -> Settings:
    """`.env`와 환경 변수를 합쳐 `Settings`를 만든다. 빈 값은 미설정으로 본다."""
    merged = parse_env_file(env_file)
    merged.update(os.environ if env is None else env)
    fields = Settings.model_fields
    data = {
        name: merged[name.upper()]
        for name in fields
        if merged.get(name.upper(), "") != ""
    }
    return Settings(**data)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()
