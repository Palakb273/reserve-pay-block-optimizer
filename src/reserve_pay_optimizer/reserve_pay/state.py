"""Reserve block lifecycle rules shared by every provider."""

from enum import StrEnum

from reserve_pay_optimizer.reserve_pay.errors import InvalidReserveStateError


class ReserveBlockStatus(StrEnum):
    PENDING = "pending"
    AUTHORIZED = "authorized"
    PARTIALLY_DEBITED = "partially_debited"
    DEBITED = "debited"
    RELEASED = "released"
    FAILED = "failed"


_ALLOWED_TRANSITIONS = {
    ReserveBlockStatus.PENDING: {
        ReserveBlockStatus.AUTHORIZED,
        ReserveBlockStatus.FAILED,
    },
    ReserveBlockStatus.AUTHORIZED: {
        ReserveBlockStatus.AUTHORIZED,
        ReserveBlockStatus.PARTIALLY_DEBITED,
        ReserveBlockStatus.DEBITED,
        ReserveBlockStatus.RELEASED,
    },
    ReserveBlockStatus.PARTIALLY_DEBITED: {
        ReserveBlockStatus.PARTIALLY_DEBITED,
        ReserveBlockStatus.DEBITED,
        ReserveBlockStatus.RELEASED,
    },
    ReserveBlockStatus.DEBITED: set(),
    ReserveBlockStatus.RELEASED: set(),
    ReserveBlockStatus.FAILED: set(),
}


def ensure_transition_allowed(
    current: ReserveBlockStatus,
    target: ReserveBlockStatus,
) -> None:
    if target not in _ALLOWED_TRANSITIONS[current]:
        raise InvalidReserveStateError(
            f"Reserve block cannot transition from {current.value} to {target.value}.",
            safe_metadata={"current_status": current.value, "target_status": target.value},
        )
