"""
fsm.py — Lightweight Finite State Machine framework.
Each State is an ABC with enter / tick / exit lifecycle.
StateMachine manages transitions and dispatches ticks.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Optional, Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from villager import Villager


class State(ABC):
    """Base class for every FSM state."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique name used as the transition key."""

    @abstractmethod
    def enter(self, villager: Villager) -> None:
        """Called once when this state becomes active."""

    @abstractmethod
    def tick(self, villager: Villager, ctx: object) -> Optional[str]:
        """Called every simulation tick.

        *ctx* is the ``SimulationManager`` (typed as object to avoid
        circular imports).  Return the name of the next state to
        transition, or ``None`` to stay in the current state.
        """

    @abstractmethod
    def exit(self, villager: Villager) -> None:
        """Called once when leaving this state."""


class StateMachine:
    """Holds registered States and manages the current one."""

    def __init__(self) -> None:
        self._states: Dict[str, State] = {}
        self._current: Optional[State] = None
        self._current_name: str = ""

    # ── registration ──────────────────────────────
    def add(self, state: State) -> "StateMachine":
        self._states[state.name] = state
        return self

    # ── lifecycle ─────────────────────────────────
    def start(self, initial: str, villager: Villager) -> None:
        self._current_name = initial
        self._current = self._states[initial]
        self._current.enter(villager)

    def tick(self, villager: Villager, ctx: object) -> None:
        if self._current is None:
            return
        next_name = self._current.tick(villager, ctx)
        if next_name is not None and next_name in self._states:
            self._transition(next_name, villager)

    def force(self, state_name: str, villager: Villager) -> None:
        """Force an immediate transition (bypasses current state's tick)."""
        if state_name in self._states and state_name != self._current_name:
            self._transition(state_name, villager)

    # ── helpers ───────────────────────────────────
    def _transition(self, name: str, villager: Villager) -> None:
        if self._current is not None:
            self._current.exit(villager)
        self._current_name = name
        self._current = self._states[name]
        self._current.enter(villager)

    @property
    def current_state(self) -> str:
        return self._current_name