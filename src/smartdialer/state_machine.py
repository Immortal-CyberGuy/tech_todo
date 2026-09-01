from __future__ import annotations

from .enums import AgentState, CallState

AGENT_TRANSITIONS: dict[AgentState, set[AgentState]] = {
    AgentState.OFFLINE: {AgentState.AVAILABLE, AgentState.PAUSED},
    AgentState.AVAILABLE: {AgentState.RESERVED, AgentState.PAUSED, AgentState.OFFLINE},
    AgentState.RESERVED: {
        AgentState.DIALING,
        AgentState.AVAILABLE,
        AgentState.OFFLINE,
    },
    AgentState.DIALING: {
        AgentState.CONNECTED,
        AgentState.AVAILABLE,
        AgentState.WRAP_UP,
        AgentState.OFFLINE,
    },
    AgentState.CONNECTED: {AgentState.WRAP_UP, AgentState.OFFLINE},
    AgentState.WRAP_UP: {AgentState.AVAILABLE, AgentState.RESERVED, AgentState.OFFLINE},
    AgentState.PAUSED: {AgentState.AVAILABLE, AgentState.OFFLINE},
}

CALL_TRANSITIONS: dict[CallState, set[CallState]] = {
    CallState.QUEUED: {CallState.RESERVED, CallState.CANCELLED},
    CallState.RESERVED: {CallState.INITIATED, CallState.FAILED, CallState.CANCELLED},
    CallState.INITIATED: {
        CallState.RINGING,
        CallState.ANSWERED,
        CallState.CONNECTED,
        CallState.COMPLETED,
        CallState.FAILED,
        CallState.CANCELLED,
    },
    CallState.RINGING: {
        CallState.ANSWERED,
        CallState.CONNECTED,
        CallState.COMPLETED,
        CallState.FAILED,
        CallState.CANCELLED,
    },
    CallState.ANSWERED: {
        CallState.CONNECTED,
        CallState.COMPLETED,
        CallState.FAILED,
        CallState.CANCELLED,
    },
    CallState.CONNECTED: {CallState.COMPLETED, CallState.FAILED},
    CallState.COMPLETED: set(),
    CallState.FAILED: set(),
    CallState.CANCELLED: set(),
}

TERMINAL_CALL_STATES = {CallState.COMPLETED, CallState.FAILED, CallState.CANCELLED}


def can_agent_transition(current: AgentState, new_state: AgentState) -> bool:
    return current == new_state or new_state in AGENT_TRANSITIONS[current]


def can_call_transition(current: CallState, new_state: CallState) -> bool:
    return current == new_state or new_state in CALL_TRANSITIONS[current]


def assert_agent_transition(current: AgentState, new_state: AgentState) -> None:
    if not can_agent_transition(current, new_state):
        raise ValueError(f"Invalid agent transition: {current.value} -> {new_state.value}")


def assert_call_transition(current: CallState, new_state: CallState) -> None:
    if not can_call_transition(current, new_state):
        raise ValueError(f"Invalid call transition: {current.value} -> {new_state.value}")


def is_terminal_call_state(state: CallState) -> bool:
    return state in TERMINAL_CALL_STATES

