"""Credential-free execution audit events."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class ReservePayAuditEventType(StrEnum):
    BLOCK_CREATE_REQUESTED = "block_create_requested"
    BLOCK_AUTHORIZED = "block_authorized"
    BLOCK_AUTHORIZATION_FAILED = "block_authorization_failed"
    BLOCK_INCREASE_REQUESTED = "block_increase_requested"
    BLOCK_INCREASE_AUTHORIZED = "block_increase_authorized"
    BLOCK_INCREASE_FAILED = "block_increase_failed"
    BLOCK_DEBIT_REQUESTED = "block_debit_requested"
    BLOCK_DEBITED = "block_debited"
    BLOCK_DEBIT_FAILED = "block_debit_failed"
    BLOCK_RELEASE_REQUESTED = "block_release_requested"
    BLOCK_RELEASED = "block_released"
    BLOCK_RELEASE_FAILED = "block_release_failed"
    BLOCK_STATUS_REFRESHED = "block_status_refreshed"
    RECONCILIATION_REQUIRED = "reconciliation_required"


@dataclass(frozen=True, slots=True)
class ReservePayAuditEvent:
    event_type: ReservePayAuditEventType
    recorded_at: datetime
    transaction_id: str
    block_id: str | None = None
    provider: str | None = None
    operation_key_fingerprint: str | None = None
    error_code: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "event_type": self.event_type.value,
            "recorded_at": self.recorded_at.isoformat(),
            "transaction_id": self.transaction_id,
            "block_id": self.block_id,
            "provider": self.provider,
            "operation_key_fingerprint": self.operation_key_fingerprint,
            "error_code": self.error_code,
        }
