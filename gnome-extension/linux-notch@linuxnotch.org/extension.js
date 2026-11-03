// SPDX-License-Identifier: GPL-2.0-or-later
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Meta from 'gi://Meta';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';

const BUS_NAME = 'org.linuxnotch.GnomeHelper';
const OBJECT_PATH = '/org/linuxnotch/GnomeHelper';
const INTERFACE = 'org.linuxnotch.GnomeHelper';
const XML = `
<node>
  <interface name="${INTERFACE}">
    <method name="Attach">
      <arg type="s" name="app_id" direction="in"/>
      <arg type="s" name="monitor" direction="in"/>
      <arg type="i" name="margin_top" direction="in"/>
    </method>
    <method name="SetSize">
      <arg type="i" name="width" direction="in"/>
      <arg type="i" name="height" direction="in"/>
    </method>
    <method name="SetFullscreenPolicy">
      <arg type="s" name="policy" direction="in"/>
    </method>
    <signal name="MonitorsChanged"/>
    <signal name="FullscreenChanged">
      <arg type="b" name="active"/>
    </signal>
    <signal name="ShellLocked">
      <arg type="b" name="locked"/>
    </signal>
  </interface>
</node>`;

export default class LinuxNotchExtension extends Extension {
    enable() {
        this._appId = '';
        this._monitor = '';
        this._marginTop = 0;
        this._width = 320;
        this._height = 80;
        this._fullscreenPolicy = 'hide';
        this._attachedWindow = null;
        this._attachedState = null;
        this._hiddenByUs = false;
        this._connections = [];
        this._watchedWindows = new Map();
        this._locked = false;
        this._dbus = Gio.DBusExportedObject.wrapJSObject(XML, this);
        this._dbus.export(Gio.DBus.session, OBJECT_PATH);
        this._nameOwner = Gio.bus_own_name_on_connection(
            Gio.DBus.session, BUS_NAME, Gio.BusNameOwnerFlags.REPLACE, null, null);
        this._connect(Main.layoutManager, 'monitors-changed', () => {
            this._sync();
            this._emit('MonitorsChanged');
        });
        this._connect(global.display, 'window-created', (_display, window) => {
            this._watchWindow(window);
            this._sync();
        });
        this._connect(Main.screenShield, 'locked-changed', () => {
            const locked = Main.screenShield.locked;
            if (locked !== this._locked) {
                this._locked = locked;
                this._emit('ShellLocked', new GLib.Variant('(b)', [locked]));
            }
        });
        this._connect(Main.layoutManager, 'startup-complete', () => this._sync());
        for (const window of global.display.get_tab_list(Meta.TabList.NORMAL_ALL, null))
            this._watchWindow(window);
    }

    Attach(appId, monitor, marginTop) {
        this._appId = appId;
        this._monitor = monitor;
        this._marginTop = Math.max(0, marginTop);
        this._sync();
    }

    SetSize(width, height) {
        if (width < 1 || height < 1)
            throw new Error('Window dimensions must be positive');
        this._width = width;
        this._height = height;
        this._sync();
    }

    SetFullscreenPolicy(policy) {
        if (policy !== 'hide' && policy !== 'show')
            throw new Error('Fullscreen policy must be hide or show');
        this._fullscreenPolicy = policy;
        this._sync();
    }

    _connect(object, signal, callback) {
        this._connections.push([object, object.connect(signal, callback)]);
    }

    _watchWindow(window) {
        if (this._watchedWindows.has(window))
            return;
        const id = window.connect('notify::fullscreen', () => this._sync());
        this._watchedWindows.set(window, id);
    }

    _findTarget() {
        const windows = global.display.get_tab_list(Meta.TabList.NORMAL_ALL, null);
        return windows.find(window => {
            const appId = window.get_gtk_application_id?.() ?? '';
            return appId === this._appId ||
                (window.get_wm_class?.() ?? '') === this._appId;
        }) ?? null;
    }

    _sync() {
        if (!this._appId)
            return;
        const target = this._findTarget();
        if (target !== this._attachedWindow) {
            this._restoreAttachedWindow();
            if (target) {
                this._attachedWindow = target;
                const frame = target.get_frame_rect();
                this._attachedState = {
                    x: frame.x,
                    y: frame.y,
                    width: frame.width,
                    height: frame.height,
                    wasAbove: target.is_above?.() ?? false,
                };
                target.make_above();
            }
        }
        if (!target)
            return;

        const monitors = Main.layoutManager.monitors;
        let monitorIndex = global.display.get_primary_monitor();
        if (this._monitor) {
            const selected = monitors.findIndex(monitor => monitor.connector === this._monitor);
            if (selected >= 0)
                monitorIndex = selected;
        }
        const geometry = monitors[monitorIndex];
        if (!geometry)
            return;
        const x = Math.round(geometry.x + (geometry.width - this._width) / 2);
        const y = Math.round(geometry.y + this._marginTop);
        target.move_frame(false, x, y);
        target.resize(false, this._width, this._height);

        const fullscreen = global.display.get_tab_list(
            Meta.TabList.NORMAL_ALL, null).some(window =>
            window !== target && window.get_monitor() === monitorIndex &&
            window.is_fullscreen());
        const actor = target.get_compositor_private();
        if (actor) {
            if (this._fullscreenPolicy === 'hide' && fullscreen && !this._hiddenByUs) {
                actor.hide();
                this._hiddenByUs = true;
            } else if (this._hiddenByUs && (this._fullscreenPolicy === 'show' || !fullscreen)) {
                actor.show();
                this._hiddenByUs = false;
            }
        }
        this._emit('FullscreenChanged', new GLib.Variant('(b)', [fullscreen]));
    }

    _restoreAttachedWindow() {
        const target = this._attachedWindow;
        const state = this._attachedState;
        if (!target)
            return;
        const actor = target.get_compositor_private();
        if (this._hiddenByUs)
            actor?.show();
        if (state && !state.wasAbove)
            target.unmake_above();
        if (state) {
            target.resize(false, state.width, state.height);
            target.move_frame(false, state.x, state.y);
        }
        this._attachedWindow = null;
        this._attachedState = null;
        this._hiddenByUs = false;
    }

    _emit(name, parameters = new GLib.Variant('()', [])) {
        if (this._dbus)
            this._dbus.emit_signal(name, parameters);
    }

    disable() {
        for (const [object, id] of this._connections)
            object.disconnect(id);
        this._connections = [];
        for (const [window, id] of this._watchedWindows)
            window.disconnect(id);
        this._watchedWindows.clear();
        this._restoreAttachedWindow();
        this._appId = '';
        if (this._dbus) {
            this._dbus.unexport();
            this._dbus = null;
        }
        if (this._nameOwner) {
            Gio.bus_unown_name(this._nameOwner);
            this._nameOwner = 0;
        }
    }
}
