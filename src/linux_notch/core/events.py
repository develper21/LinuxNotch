from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from threading import RLock
from typing import Any


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable[..., Any]]] = defaultdict(list)
        self._lock = RLock()

    def subscribe(self, event: str, handler: Callable[..., Any]) -> Callable[[], None]:
        with self._lock:
            self._handlers[event].append(handler)

        def unsubscribe() -> None:
            with self._lock:
                handlers = self._handlers[event]
                if handler in handlers:
                    handlers.remove(handler)

        return unsubscribe

    def publish(self, event: str, *args: Any, **kwargs: Any) -> None:
        with self._lock:
            handlers = tuple(self._handlers[event])
        for handler in handlers:
            handler(*args, **kwargs)
