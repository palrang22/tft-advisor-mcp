"""표준 logging 설정. 출력은 stderr로만 보낸다 (MCP stdio는 stdout을 프로토콜에 쓴다)."""

from __future__ import annotations

import logging
import sys

from common.config import get_settings

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def setup_logging(level: str | None = None) -> None:
    """루트 로거를 stderr 핸들러 하나로 설정한다. 여러 번 불러도 핸들러가 늘지 않는다.

    `level`이 없으면 `LOG_LEVEL` 설정값을 쓴다.
    """
    if level is None:
        level = get_settings().log_level
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    logging.basicConfig(level=level.upper(), handlers=[handler], force=True)
