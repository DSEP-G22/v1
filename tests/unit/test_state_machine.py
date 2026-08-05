import pytest

from libs.domain.enums import TicketState
from libs.domain.state.machine import IllegalTransition, transition


def test_valid_forward_transition():
    assert transition(TicketState.RECEIVED, TicketState.PROCESSING) == TicketState.PROCESSING


def test_every_non_terminal_state_can_transition_to_failed():
    for state in TicketState:
        if state is TicketState.FAILED:
            continue
        assert transition(state, TicketState.FAILED) == TicketState.FAILED


def test_illegal_transition_raises():
    with pytest.raises(IllegalTransition):
        transition(TicketState.RECEIVED, TicketState.RESOLVED)


def test_terminal_states_have_no_further_transitions_besides_failed():
    with pytest.raises(IllegalTransition):
        transition(TicketState.CLOSED, TicketState.RECEIVED)
