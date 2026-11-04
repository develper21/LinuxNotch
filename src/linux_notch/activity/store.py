from __future__ import annotations

import secrets
import time
from collections import defaultdict, deque
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from linux_notch.activity.schema import (
    MAX_ACTIVE_PER_CLIENT,
    MAX_ACTIVE_PER_APP,
    MAX_STARTS_PER_MINUTE,
    MAX_UPDATES_PER_MINUTE,
    ActivityValidationError,
    normalize_activity,
    normalize_patch,
    validate_activity_id,
)

RATE_WINDOW_SECONDS = 60.0


@dataclass(frozen=True)
class Activity:
    activity_id: str
    app: str
    client: str
    data: dict[str, Any]
    expires_at: float
    ended: bool = False


class ActivityStore:
    def __init__(self, clock=time.monotonic) -> None:
        self._clock = clock
        self._activities: dict[str, Activity] = {}
        self._requests: dict[tuple[str, str], deque[float]] = defaultdict(deque)

    def start(self, client: str, value: dict[str, Any]) -> str:
        now = self._clock()
        self.expire(now)
        data = normalize_activity(value)
        self._check_rate(client, data["app"], "start", MAX_STARTS_PER_MINUTE, now)
        owned = sum(
            activity.client == client and not activity.ended
            for activity in self._activities.values()
        )
        same_app = sum(
            activity.data["app"] == data["app"] and not activity.ended
            for activity in self._activities.values()
        )
        if owned >= MAX_ACTIVE_PER_CLIENT or same_app >= MAX_ACTIVE_PER_APP:
            raise ActivityValidationError("A client or app may have at most 10 active activities")
        activity_id = f"act_{secrets.token_urlsafe(18)}"
        self._activities[activity_id] = Activity(
            activity_id=activity_id,
            app=data["app"],
            client=client,
            data=data,
            expires_at=now + data["ttl_seconds"],
        )
        return activity_id

    def update(self, client: str, activity_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        now = self._clock()
        self.expire(now)
        activity_id = validate_activity_id(activity_id)
        existing = self._find_activity(activity_id)
        self._check_rate(
            client, existing.data["app"], "update", MAX_UPDATES_PER_MINUTE, now
        )
        if existing.ended:
            raise ActivityValidationError("Activity has already ended")
        data = normalize_patch(patch, existing.data)
        expires_at = existing.expires_at
        if "ttl_seconds" in patch:
            expires_at = now + data["ttl_seconds"]
        updated = Activity(
            activity_id,
            existing.app,
            existing.client,
            data,
            expires_at,
        )
        self._activities[activity_id] = updated
        return dict(data)

    def end(self, client: str, activity_id: str, final_state: str) -> dict[str, Any]:
        updated = self.update(client, activity_id, {"state": final_state})
        activity = self._activities[activity_id]
        self._activities[activity_id] = Activity(
            activity.activity_id,
            activity.app,
            activity.client,
            activity.data,
            activity.expires_at,
            ended=True,
        )
        return updated

    def list_active(self, owner: str | None = None) -> list[Activity]:
        self.expire()
        return [
            Activity(
                item.activity_id,
                item.app,
                item.client,
                deepcopy(item.data),
                item.expires_at,
                item.ended,
            )
            for item in self._activities.values()
            if not item.ended and (owner is None or item.app == owner)
        ]

    def expire(self, now: float | None = None) -> list[str]:
        current = self._clock() if now is None else now
        expired = [
            activity_id
            for activity_id, activity in self._activities.items()
            if activity.expires_at <= current
        ]
        for activity_id in expired:
            del self._activities[activity_id]
        return expired

    def _find_activity(self, activity_id: str) -> Activity:
        activity = self._activities.get(activity_id)
        if activity is None:
            raise KeyError("Activity does not exist or has expired")
        return activity

    def _check_rate(
        self,
        owner: str,
        app: str,
        operation: str,
        limit: int,
        now: float,
    ) -> None:
        keys = ((owner, operation), (f"app:{app}", operation))
        for key in keys:
            events = self._requests[key]
            while events and now - events[0] >= RATE_WINDOW_SECONDS:
                events.popleft()
            if len(events) >= limit:
                raise ActivityValidationError("Activity API rate limit exceeded")
        for key in keys:
            self._requests[key].append(now)
