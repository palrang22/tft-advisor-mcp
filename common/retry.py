"""외부 호출(OP.GG, CDragon, BigQuery)용 timeout + 지수 백오프 재시도 래퍼.

- 동기: `fn(timeout)` 형태로 부른다. timeout은 호출하는 클라이언트(httpx, BigQuery)에 그대로 넘긴다.
- 비동기: `asyncio.timeout`으로 감싸고, 시간 초과(`TimeoutError`)도 재시도 대상에 넣는다.
- 재시도할 예외는 호출부가 `retry_on`으로 명시한다. 파싱 오류 같은 버그는 재시도하지 않는다.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetryPolicy:
    timeout: float = 30.0
    attempts: int = 4
    base_delay: float = 1.0
    max_delay: float = 30.0

    def __post_init__(self) -> None:
        if self.timeout <= 0:
            raise ValueError("timeout must be > 0")
        if self.attempts < 1:
            raise ValueError("attempts must be >= 1")
        if self.base_delay < 0 or self.max_delay < 0:
            raise ValueError("delays must be >= 0")

    def delay(self, attempt: int) -> float:
        """`attempt`번째(1부터) 실패 뒤 대기 시간: base * 2^(attempt-1), 상한 max_delay."""
        return min(self.max_delay, self.base_delay * 2 ** (attempt - 1))


DEFAULT_POLICY = RetryPolicy()


def retry_call[T](
    fn: Callable[[float], T],
    *,
    retry_on: tuple[type[BaseException], ...],
    policy: RetryPolicy = DEFAULT_POLICY,
    name: str = "call",
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    for attempt in range(1, policy.attempts + 1):
        try:
            return fn(policy.timeout)
        except retry_on as exc:
            if attempt == policy.attempts:
                logger.error("%s failed after %d attempts: %r", name, attempt, exc)
                raise
            wait = policy.delay(attempt)
            logger.warning(
                "%s failed (attempt %d/%d): %r; retrying in %.1fs",
                name, attempt, policy.attempts, exc, wait,
            )
            sleep(wait)
    raise AssertionError("unreachable")


async def retry_call_async[T](
    fn: Callable[[], Awaitable[T]],
    *,
    retry_on: tuple[type[BaseException], ...],
    policy: RetryPolicy = DEFAULT_POLICY,
    name: str = "call",
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> T:
    catch = (*retry_on, TimeoutError)
    for attempt in range(1, policy.attempts + 1):
        try:
            async with asyncio.timeout(policy.timeout):
                return await fn()
        except catch as exc:
            if attempt == policy.attempts:
                logger.error("%s failed after %d attempts: %r", name, attempt, exc)
                raise
            wait = policy.delay(attempt)
            logger.warning(
                "%s failed (attempt %d/%d): %r; retrying in %.1fs",
                name, attempt, policy.attempts, exc, wait,
            )
            await sleep(wait)
    raise AssertionError("unreachable")
