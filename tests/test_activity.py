import unittest

from linux_notch.activity.schema import ActivityValidationError, normalize_activity
from linux_notch.activity.store import ActivityStore


def activity(**overrides):
    value = {
        "schema": 1,
        "app": "build-runner",
        "title": "Deploy",
        "state": "running",
        "progress": {"done": 1, "total": 3},
        "ttl_seconds": 30,
    }
    value.update(overrides)
    return value


class ActivitySchemaTests(unittest.TestCase):
    def test_normalizes_activity_and_ignores_unknown_fields(self):
        parsed = normalize_activity(activity(unknown_field="ignored"))
        self.assertEqual(parsed["app"], "build-runner")
        self.assertNotIn("unknown_field", parsed)

    def test_rejects_oversized_text_and_invalid_progress(self):
        with self.assertRaises(ActivityValidationError):
            normalize_activity(activity(title="x" * 121))
        with self.assertRaises(ActivityValidationError):
            normalize_activity(activity(progress={"done": 4, "total": 3}))

    def test_rejects_unsupported_schema_and_invalid_app_identifier(self):
        with self.assertRaises(ActivityValidationError):
            normalize_activity(activity(schema=2))
        with self.assertRaises(ActivityValidationError):
            normalize_activity(activity(app="../unsafe"))


class ActivityStoreTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.store = ActivityStore(clock=lambda: self.now)

    def test_activity_id_allows_followup_from_a_new_cli_process(self):
        activity_id = self.store.start(":1.5", activity())
        self.assertTrue(activity_id.startswith("act_"))
        updated = self.store.update(":1.6", activity_id, {"state": "done"})
        self.assertEqual(updated["state"], "done")
        self.assertEqual(len(self.store.list_active("build-runner")), 1)

    def test_end_removes_activity_from_active_view_and_rejects_updates(self):
        activity_id = self.store.start(":1.5", activity())
        self.store.end(":1.5", activity_id, "success")
        self.assertEqual(self.store.list_active("build-runner"), [])
        with self.assertRaises(ActivityValidationError):
            self.store.update(":1.5", activity_id, {"title": "late update"})

    def test_activity_expires_without_a_followup_update(self):
        self.store.start(":1.5", activity(ttl_seconds=2))
        self.now = 102.0
        self.assertEqual(self.store.list_active(), [])

    def test_client_activity_quota(self):
        for index in range(10):
            self.store.start(":1.5", activity(title=f"build {index}"))
        with self.assertRaises(ActivityValidationError):
            self.store.start(":1.5", activity(title="overflow"))
        self.store.start(":1.6", activity(app="other-app"))

    def test_application_quota_is_shared_across_dbus_clients(self):
        for index in range(10):
            self.store.start(f":1.{index}", activity())
        with self.assertRaises(ActivityValidationError):
            self.store.start(":1.50", activity())

    def test_update_does_not_extend_ttl_unless_ttl_is_changed(self):
        activity_id = self.store.start(":1.5", activity(ttl_seconds=5))
        self.now = 104.0
        self.store.update(":1.5", activity_id, {"state": "building"})
        self.now = 105.0
        self.assertEqual(self.store.list_active(), [])


if __name__ == "__main__":
    unittest.main()
