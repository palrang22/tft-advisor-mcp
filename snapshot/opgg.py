"""OP.GG MCP 클라이언트. OP.GG 호출은 이 모듈을 거친다.

- 모든 툴 호출에 `client_app`을 넣는다.
- 호출 사이 `OPGG_CALL_INTERVAL_SEC` 이상 쉰다 (`list_tools` 포함).
- 호출마다 timeout + 지수 백오프 재시도 (`common.retry`).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import AsyncExitStack
from types import TracebackType
from typing import Any, Self

from mcp import ClientSession, MCPError
from mcp.client.streamable_http import StreamableHTTPError, streamable_http_client

from common.config import Settings
from common.retry import RetryPolicy, retry_call_async

logger = logging.getLogger(__name__)

POLICY = RetryPolicy(timeout=60.0, attempts=4, base_delay=2.0, max_delay=30.0)


class OpggToolError(Exception):
    """툴이 `is_error=true`로 응답했다."""


RETRY_ON: tuple[type[BaseException], ...] = (MCPError, StreamableHTTPError, OpggToolError)


class OpggClient:
    """`async with OpggClient(settings) as c:` 형태로 쓴다. 세션 하나로 여러 번 호출한다."""

    def __init__(self, settings: Settings, policy: RetryPolicy = POLICY) -> None:
        self._settings = settings
        self._policy = policy
        self._stack = AsyncExitStack()
        self._session: ClientSession | None = None
        self._last_call: float | None = None

    async def __aenter__(self) -> Self:
        read, write = await self._stack.enter_async_context(
            streamable_http_client(self._settings.opgg_mcp_url)
        )
        session = await self._stack.enter_async_context(ClientSession(read, write))
        await retry_call_async(
            session.initialize, retry_on=RETRY_ON, policy=self._policy, name="opgg initialize"
        )
        self._session = session
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._session = None
        await self._stack.aclose()

    async def list_tools(self) -> dict[str, Any]:
        """`list_tools()` 결과를 JSON 덤프(camelCase) 형태의 dict로 돌려준다."""
        session = self._require_session()
        await self._wait_interval()
        result = await retry_call_async(
            session.list_tools, retry_on=RETRY_ON, policy=self._policy, name="opgg list_tools"
        )
        return result.model_dump(mode="json", by_alias=True, exclude_none=True)

    async def call_tool(self, tool: str, args: dict[str, Any] | None = None) -> str:
        """툴을 부르고 `content[0].text` 원문을 돌려준다."""
        session = self._require_session()
        arguments = {**(args or {}), "client_app": self._settings.opgg_client_app}

        async def once() -> str:
            await self._wait_interval()
            res = await session.call_tool(tool, arguments)
            text = res.content[0].text if res.content else ""
            if res.is_error:
                raise OpggToolError(f"{tool} {args}: {text[:300]}")
            json.loads(text)  # JSON이 아니면 여기서 ValueError (재시도 안 함)
            return text

        return await retry_call_async(
            once, retry_on=RETRY_ON, policy=self._policy, name=f"opgg {tool}"
        )

    def _require_session(self) -> ClientSession:
        if self._session is None:
            raise RuntimeError("OpggClient는 async with 안에서만 쓴다")
        return self._session

    async def _wait_interval(self) -> None:
        if self._last_call is not None:
            remaining = self._settings.opgg_call_interval_sec - (time.monotonic() - self._last_call)
            if remaining > 0:
                await asyncio.sleep(remaining)
        self._last_call = time.monotonic()
