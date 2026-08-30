"""Provider-neutral Reserve Pay execution contract."""

from typing import Protocol, runtime_checkable

from reserve_pay_optimizer.reserve_pay.models import (
    BlockStatusResult,
    CreateBlockRequest,
    CreateBlockResult,
    DebitBlockRequest,
    DebitBlockResult,
    GetBlockStatusRequest,
    IncreaseBlockRequest,
    IncreaseBlockResult,
    ProviderCapabilities,
    ReleaseBlockRequest,
    ReleaseBlockResult,
    ReserveProviderName,
)


@runtime_checkable
class ReservePayProvider(Protocol):
    name: ReserveProviderName
    capabilities: ProviderCapabilities

    def create_block(self, request: CreateBlockRequest) -> CreateBlockResult: ...

    def increase_block(self, request: IncreaseBlockRequest) -> IncreaseBlockResult: ...

    def debit_block(self, request: DebitBlockRequest) -> DebitBlockResult: ...

    def release_block(self, request: ReleaseBlockRequest) -> ReleaseBlockResult: ...

    def get_block_status(self, request: GetBlockStatusRequest) -> BlockStatusResult: ...
