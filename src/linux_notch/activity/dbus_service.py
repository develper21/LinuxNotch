from __future__ import annotations

import json
from typing import Any

from linux_notch.activity.schema import ActivityValidationError, decode_json
from linux_notch.activity.store import ActivityStore

BUS_NAME = "org.linuxnotch.Notch1"
OBJECT_PATH = "/org/linuxnotch/Notch1"
INTERFACE = "org.linuxnotch.Notch1"
INTROSPECTION_XML = """
<node>
  <interface name="org.linuxnotch.Notch1">
    <method name="StartActivity">
      <arg type="s" name="json" direction="in"/>
      <arg type="s" name="activity_id" direction="out"/>
    </method>
    <method name="UpdateActivity">
      <arg type="s" name="activity_id" direction="in"/>
      <arg type="s" name="json_patch" direction="in"/>
    </method>
    <method name="EndActivity">
      <arg type="s" name="activity_id" direction="in"/>
      <arg type="s" name="final_state" direction="in"/>
    </method>
    <signal name="ActivityAction">
      <arg type="s" name="activity_id"/>
      <arg type="s" name="action_id"/>
    </signal>
  </interface>
</node>
"""


class ActivityDBusService:
    def __init__(self, store: ActivityStore | None = None, on_activities_changed=None) -> None:
        import gi

        gi.require_version("Gio", "2.0")
        from gi.repository import Gio, GLib

        self._gio = Gio
        self._glib = GLib
        self.store = store or ActivityStore()
        self._on_activities_changed = on_activities_changed
        self._owner_id = 0
        self._registration_id = 0
        self._connection: Any | None = None
        self._node_info = Gio.DBusNodeInfo.new_for_xml(INTROSPECTION_XML)
        self._expiry_source = 0

    def start(self) -> None:
        if self._owner_id:
            return
        self._owner_id = self._gio.bus_own_name(
            self._gio.BusType.SESSION,
            BUS_NAME,
            self._gio.BusNameOwnerFlags.NONE,
            self._on_bus_acquired,
            self._on_name_acquired,
            self._on_name_lost,
        )

    def _on_bus_acquired(self, connection: Any, _name: str) -> None:
        self._connection = connection
        self._registration_id = connection.register_object(
            OBJECT_PATH,
            self._node_info.interfaces[0],
            self._on_method_call,
            None,
            None,
        )
        self._expiry_source = self._glib.timeout_add_seconds(30, self._expire_activities)

    def _on_name_acquired(self, _connection: Any, _name: str) -> None:
        return None

    def _on_name_lost(self, _connection: Any, name: str) -> None:
        print(f"linux-notch: could not own D-Bus name {name}", flush=True)

    def _on_method_call(
        self,
        _connection: Any,
        sender: str,
        _object_path: str,
        _interface_name: str,
        method_name: str,
        parameters: Any,
        invocation: Any,
    ) -> None:
        try:
            if method_name == "StartActivity":
                (payload,) = parameters.unpack()
                activity_id = self.store.start(sender, decode_json(payload))
                self._notify_activities_changed()
                invocation.return_value(self._glib.Variant("(s)", (activity_id,)))
            elif method_name == "UpdateActivity":
                activity_id, payload = parameters.unpack()
                self.store.update(sender, activity_id, decode_json(payload))
                self._notify_activities_changed()
                invocation.return_value(self._glib.Variant("()", ()))
            elif method_name == "EndActivity":
                activity_id, final_state = parameters.unpack()
                self.store.end(sender, activity_id, final_state)
                self._notify_activities_changed()
                invocation.return_value(self._glib.Variant("()", ()))
            else:
                invocation.return_dbus_error(
                    "org.linuxnotch.Error.UnknownMethod", f"Unknown method {method_name}"
                )
        except KeyError as error:
            invocation.return_dbus_error("org.linuxnotch.Error.NotFound", str(error))
        except (ActivityValidationError, ValueError, UnicodeError) as error:
            invocation.return_dbus_error("org.linuxnotch.Error.InvalidActivity", str(error))

    def emit_action(self, activity_id: str, action_id: str) -> None:
        if self._connection is None:
            raise RuntimeError("Activity D-Bus service is not connected")
        self._connection.emit_signal(
            None,
            OBJECT_PATH,
            INTERFACE,
            "ActivityAction",
            self._glib.Variant("(ss)", (activity_id, action_id)),
        )

    def _notify_activities_changed(self) -> None:
        if self._on_activities_changed is not None:
            self._on_activities_changed(self.store.list_active())

    def _expire_activities(self) -> bool:
        self.store.expire()
        return True

    def stop(self) -> None:
        if self._expiry_source:
            self._glib.source_remove(self._expiry_source)
            self._expiry_source = 0
        if self._connection is not None and self._registration_id:
            self._connection.unregister_object(self._registration_id)
        self._registration_id = 0
        self._connection = None
        if self._owner_id:
            self._gio.bus_unown_name(self._owner_id)
            self._owner_id = 0


def encode_activity(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
