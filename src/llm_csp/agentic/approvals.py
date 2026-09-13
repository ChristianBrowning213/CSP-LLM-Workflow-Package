"""Typed approval requests and centralized gate transitions."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Iterable, Mapping

from .models import (
    ActorRole,
    ApprovalCategory,
    ApprovalStatus,
    JSONMapping,
    _freeze,
    _jsonable,
    _non_empty,
    _require_mapping,
    _strict_payload,
    _utc_timestamp,
)


@dataclass(frozen=True, slots=True)
class ApprovalRequest:
    approval_id: str
    category: ApprovalCategory
    reason: str
    proposed_change: JSONMapping
    requested_by: ActorRole
    request_ref: str
    created_at: str
    status: ApprovalStatus = ApprovalStatus.PENDING
    decided_at: str | None = None
    decided_by: ActorRole | None = None

    def __post_init__(self) -> None:
        for value, name in ((self.approval_id, "approval_id"), (self.reason, "reason"),
                            (self.request_ref, "request_ref")):
            _non_empty(value, name)
        object.__setattr__(self, "category", ApprovalCategory(self.category))
        object.__setattr__(self, "requested_by", ActorRole(self.requested_by))
        object.__setattr__(self, "status", ApprovalStatus(self.status))
        object.__setattr__(self, "proposed_change", _freeze(_require_mapping(self.proposed_change, "proposed_change")))
        if not self.proposed_change:
            raise ValueError("proposed_change must identify the exact requested change")
        _utc_timestamp(self.created_at, "created_at")
        if self.status is ApprovalStatus.PENDING:
            if self.decided_at is not None or self.decided_by is not None:
                raise ValueError("pending approval cannot have decision metadata")
        elif self.decided_at is None or self.decided_by is None:
            raise ValueError("decided approval requires decided_at and decided_by")
        if self.decided_at is not None:
            _utc_timestamp(self.decided_at, "decided_at")
        if self.decided_by is not None:
            object.__setattr__(self, "decided_by", ActorRole(self.decided_by))
        if self.status in {ApprovalStatus.APPROVED, ApprovalStatus.REJECTED} and self.decided_by is not ActorRole.USER:
            raise ValueError("only USER may approve or reject a request")

    def to_dict(self) -> dict[str, Any]:
        return _jsonable({name: getattr(self, name) for name in self.__dataclass_fields__})

    @classmethod
    def from_dict(cls, value: Any) -> "ApprovalRequest":
        p = _strict_payload(value, set(cls.__dataclass_fields__),
                            {"approval_id", "category", "reason", "proposed_change", "requested_by", "request_ref", "created_at"})
        return cls(**p)


def action_requires_approval(category: ApprovalCategory | None) -> bool:
    if category is None:
        return False
    ApprovalCategory(category)
    return True


def has_required_approval(
    category: ApprovalCategory,
    approvals: Iterable[ApprovalRequest],
    *,
    request_ref: str,
    proposed_change: Mapping[str, Any],
) -> bool:
    expected = ApprovalCategory(category)
    expected_change = _freeze(_require_mapping(proposed_change, "proposed_change"))
    return any(
        item.category is expected
        and item.request_ref == request_ref
        and item.proposed_change == expected_change
        and item.status is ApprovalStatus.APPROVED
        for item in approvals
    )


def transition_approval(
    request: ApprovalRequest,
    status: ApprovalStatus,
    *,
    decided_by: ActorRole,
    decided_at: str,
) -> ApprovalRequest:
    target = ApprovalStatus(status)
    actor = ActorRole(decided_by)
    if request.status is not ApprovalStatus.PENDING or target is ApprovalStatus.PENDING:
        raise ValueError(f"illegal approval transition: {request.status.value} -> {target.value}")
    return replace(request, status=target, decided_by=actor, decided_at=decided_at)


__all__ = ["ApprovalRequest", "action_requires_approval", "has_required_approval", "transition_approval"]
