"""어댑터가 프로토콜별 오류로 변환하는 도메인 예외."""

from __future__ import annotations


class DomainError(Exception):
    """core 계산·데이터 접근 실패의 공통 타입."""


class InvalidInput(DomainError):
    """형식은 맞지만 계산할 수 없는 입력 상태."""


class UnknownName(DomainError):
    """알 수 없는 이름 또는 ID. 후보는 어댑터가 표시할 수 있다."""

    def __init__(self, message: str, candidates: list[str] | None = None) -> None:
        super().__init__(message)
        self.candidates = candidates or []


class MissingSetData(DomainError):
    """사람이 채우는 세트 수치가 없거나 잘못되었다."""


class DataUnavailable(DomainError):
    """필요한 정적 데이터·통계가 없다. 값을 추측하지 않는다."""
