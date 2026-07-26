"""Ticket state machine. Pure function, no persistence."""

from __future__ import annotations

from libs.domain.enums import TicketState

_T = TicketState


class IllegalTransition(ValueError):
    def __init__(self, current: TicketState, target: TicketState) -> None:
        super().__init__(f"illegal transition {current.value} -> {target.value}")
        self.current = current
        self.target = target


_FORWARD: dict[TicketState, set[TicketState]] = {
    _T.RECEIVED: {_T.PROCESSING},
    _T.PROCESSING: {_T.AGGREGATED},
    _T.AGGREGATED: {_T.TRIAGED},
    _T.TRIAGED: {_T.DIAGNOSED},
    _T.DIAGNOSED: {_T.READY_FOR_AGENT},
    _T.READY_FOR_AGENT: {_T.IN_REVIEW},
    _T.IN_REVIEW: {_T.AWAITING_APPROVAL, _T.READY_FOR_AGENT},
    _T.AWAITING_APPROVAL: {_T.RESOLVED, _T.IN_REVIEW},
    _T.RESOLVED: {_T.CLOSED},
    _T.CLOSED: set(),
    _T.FAILED: set(),
}

# Every state may additionally transition to FAILED.
ALLOWED: dict[TicketState, set[TicketState]] = {
    state: targets | {_T.FAILED} if state is not _T.FAILED else targets
    for state, targets in _FORWARD.items()
}


def transition(current: TicketState, target: TicketState) -> TicketState:
    if target not in ALLOWED.get(current, set()):
        raise IllegalTransition(current, target)
    return target
