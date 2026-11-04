from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from threading import RLock


class IslandState(StrEnum):
    PILL = "pill"
    PEEK = "peek"
    EXPANDED = "expanded"


@dataclass(frozen=True)
class StateSnapshot:
    state: IslandState
    revision: int


class IslandStateStore:
    def __init__(self) -> None:
        self._state = IslandState.PILL
        self._revision = 0
        self._lock = RLock()

    def set(self, state: IslandState) -> StateSnapshot:
        with self._lock:
            if state != self._state:
                self._state = state
                self._revision += 1
            return StateSnapshot(self._state, self._revision)

    def snapshot(self) -> StateSnapshot:
        with self._lock:
            return StateSnapshot(self._state, self._revision)
