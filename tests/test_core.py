import unittest

from linux_notch.core.events import EventBus
from linux_notch.core.state import IslandState, IslandStateStore


class EventBusTests(unittest.TestCase):
    def test_subscribers_receive_events_and_can_unsubscribe(self):
        events = EventBus()
        received = []
        unsubscribe = events.subscribe("ready", received.append)
        events.publish("ready", 1)
        unsubscribe()
        events.publish("ready", 2)
        self.assertEqual(received, [1])


class StateTests(unittest.TestCase):
    def test_revision_changes_only_when_state_changes(self):
        state = IslandStateStore()
        self.assertEqual(state.snapshot().revision, 0)
        state.set(IslandState.PILL)
        self.assertEqual(state.snapshot().revision, 0)
        self.assertEqual(state.set(IslandState.EXPANDED).revision, 1)


if __name__ == "__main__":
    unittest.main()
