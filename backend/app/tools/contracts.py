from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from time import monotonic
from typing import Generic, TypeVar
from uuid import UUID, uuid4


T = TypeVar("T")


class ToolStatus(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class ToolErrorCode(str, Enum):
    INVALID_INPUT = "INVALID_INPUT"
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
    RESOURCE_UNREADABLE = "RESOURCE_UNREADABLE"
    SECURITY_VIOLATION = "SECURITY_VIOLATION"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    TIMEOUT = "TIMEOUT"
    OUTPUT_INVALID = "OUTPUT_INVALID"
    CLEANUP_FAILED = "CLEANUP_FAILED"


@dataclass(frozen=True)
class ToolError:
    code: ToolErrorCode
    safe_message: str
    retryable: bool = False
    affected_resource_id: UUID | None = None


@dataclass(frozen=True)
class ToolExecutionMetadata:
    invocation_id: UUID
    tool_name: str
    tool_version: str
    started_at: datetime
    completed_at: datetime
    duration_ms: float


@dataclass(frozen=True)
class ToolResult(Generic[T]):
    status: ToolStatus
    metadata: ToolExecutionMetadata
    data: T | None = None
    error: ToolError | None = None
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        success = self.status is ToolStatus.SUCCEEDED
        if success != (self.data is not None) or success == (self.error is not None):
            raise ValueError("ToolResult must contain exactly one of data or error.")


@dataclass
class ToolInvocation:
    tool_name: str
    tool_version: str
    invocation_id: UUID = field(default_factory=uuid4)
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    _started_monotonic: float = field(default_factory=monotonic, repr=False)

    def metadata(self) -> ToolExecutionMetadata:
        completed_at = datetime.now(timezone.utc)
        return ToolExecutionMetadata(
            invocation_id=self.invocation_id,
            tool_name=self.tool_name,
            tool_version=self.tool_version,
            started_at=self.started_at,
            completed_at=completed_at,
            duration_ms=max(0.0, (monotonic() - self._started_monotonic) * 1000),
        )

    def succeeded(self, data: T, *, warnings: tuple[str, ...] = ()) -> ToolResult[T]:
        return ToolResult(
            status=ToolStatus.SUCCEEDED,
            data=data,
            error=None,
            warnings=warnings,
            metadata=self.metadata(),
        )

    def failed(self, error: ToolError, *, warnings: tuple[str, ...] = ()) -> ToolResult[T]:
        return ToolResult(
            status=ToolStatus.FAILED,
            data=None,
            error=error,
            warnings=warnings,
            metadata=self.metadata(),
        )
