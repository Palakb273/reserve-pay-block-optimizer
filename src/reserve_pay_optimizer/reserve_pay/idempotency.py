"""Deterministic idempotency coordination for financial mutations."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Callable, Generic, TypeVar

from reserve_pay_optimizer.reserve_pay.errors import IdempotencyConflictError

T = TypeVar("T")


def payload_fingerprint(payload: dict[str, object]) -> str:
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class _StoredResult(Generic[T]):
    fingerprint: str
    result: T


class IdempotencyRegistry:
    """In-memory Phase-10 registry; a persistent implementation can replace it later."""

    def __init__(self) -> None:
        self._records: dict[tuple[str, str], _StoredResult[object]] = {}

    def execute(
        self,
        operation: str,
        key: str,
        payload: dict[str, object],
        action: Callable[[], T],
    ) -> T:
        fingerprint = payload_fingerprint(payload)
        record_key = (operation, key)
        existing = self._records.get(record_key)
        if existing is not None:
            if existing.fingerprint != fingerprint:
                raise IdempotencyConflictError(
                    "The idempotency key was already used with a different payload.",
                    safe_metadata={"operation": operation},
                )
            return existing.result  # type: ignore[return-value]
        result = action()
        self._records[record_key] = _StoredResult(fingerprint, result)
        return result
