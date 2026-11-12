"""MCP·REST 공통 응답. JSON은 공백 없이 직렬화하고 없는 메타데이터는 생략한다."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Envelope[T](BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)

    source: Literal["opgg_snapshot", "static", "calc"]
    set_number: int = Field(alias="set", ge=1)
    results: T
    snapshot_date: date | None = None
    source_updated_at: datetime | None = None
    n: int | None = Field(default=None, ge=0)
    low_sample: bool = False
    is_estimate: bool = False
    notes: list[str] = Field(default_factory=list)

    def to_json(self) -> str:
        return self.model_dump_json(by_alias=True, exclude_none=True)
