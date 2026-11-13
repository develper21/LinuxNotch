// SPDX-License-Identifier: GPL-2.0-or-later
import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Meta from 'gi://Meta';
import St from 'gi://St';
import cairo from 'cairo';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';

const HELPER_BUS_NAME = 'org.linuxnotch.GnomeHelper';
const HELPER_OBJECT_PATH = '/org/linuxnotch/GnomeHelper';
const HELPER_INTERFACE = 'org.linuxnotch.GnomeHelper';
const HELPER_XML = `
<node>
  <interface name="${HELPER_INTERFACE}">
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

const FACE_BUS_NAME = 'org.linuxnotch.FaceDaemon';
const FACE_OBJECT_PATH = '/org/linuxnotch/FaceDaemon';
const FACE_INTERFACE = 'org.linuxnotch.FaceDaemon';
const FACE_DAEMON_XML = `
<node>
  <interface name="${FACE_INTERFACE}">
    <method name="StartScan"/>
    <method name="StopScan"/>
    <method name="SetLocked">
      <arg type="b" name="locked" direction="in"/>
    </method>
    <method name="UserActivity"/>
    <signal name="ScanState">
      <arg type="s" name="state"/>
      <arg type="s" name="message"/>
    </signal>
    <signal name="ScanFrame">
      <arg type="d" name="x"/>
      <arg type="d" name="y"/>
      <arg type="d" name="width"/>
      <arg type="d" name="height"/>
      <arg type="a(dd)" name="landmarks"/>
    </signal>
    <signal name="ScanResult">
      <arg type="b" name="success"/>
      <arg type="d" name="score"/>
    </signal>
  </interface>
</node>`;

const FaceDaemonProxy = Gio.DBusProxy.makeProxyWrapper(FACE_DAEMON_XML);

const NOTCH_WIDTH = 280;
const NOTCH_HEIGHT = 76;
const NOTCH_RADIUS = 20;
const NOTCH_EAR = 16;
const LOCK_GRACE_COOLDOWN_US = 1500000; // 1.5 seconds cooldown after lock

function drawIslandShape(cr, width, height, radius, ear, opacity = 1.0) {
    if (width <= 0 || height <= 0)
        return;

    ear = Math.min(Math.max(ear, 0), width / 2);
    radius = Math.min(Math.max(radius, 0), (width - 2 * ear) / 2, height / 2);

    cr.newPath();
    if (ear > 0) {
        cr.moveTo(0, 0);
        cr.arc(0, ear, ear, -Math.PI / 2, 0);
        cr.lineTo(ear, height - radius);
    } else {
        cr.moveTo(0, 0);
        cr.lineTo(0, height - radius);
    }

    if (radius > 0) {
        cr.arcNegative(
            ear + radius,
            height - radius,
            radius,
            Math.PI,
            Math.PI / 2
        );
    } else {
        cr.lineTo(ear, height);
    }

    cr.lineTo(width - ear - radius, height);
    if (radius > 0) {
        cr.arcNegative(
            width - ear - radius,
            height - radius,
            radius,
            Math.PI / 2,
            0
        );
    } else {
        cr.lineTo(width - ear, height);
    }

    if (ear > 0) {
        cr.lineTo(width - ear, ear);
        cr.arc(width, ear, ear, Math.PI, -Math.PI / 2);
    } else {
        cr.lineTo(width, 0);
    }

    cr.closePath();
    cr.setSourceRGBA(0, 0, 0, opacity);
    cr.fill();
}

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
        this._targetPositionId = 0;
        this._targetSizeId = 0;
        this._positioning = false;
        this._hiddenByUs = false;
        this._connections = [];
        this._watchedWindows = new Map();
        this._syncSource = 0;
        this._locked = Main.screenShield.locked;

        // Lock screen notch state
        this._lockNotch = null;
        this._drawingArea = null;
        this._statusLabel = null;
        this._unlockTimer = 0;
        this._retractTimer = 0;
        this._lockTimestamp = 0;
        this._scanActive = false;
        this._lockScanSuccess = false;
        this._lockScanFailed = false;
        this._latestFrame = null;
        this._latestLandmarks = null;
        this._faceDaemon = null;
        this._faceSignalIds = [];
        this._dialogSignalIds = [];

        this._dbus = Gio.DBusExportedObject.wrapJSObject(HELPER_XML, this);
        this._dbus.export(Gio.DBus.session, HELPER_OBJECT_PATH);
        this._nameOwner = Gio.bus_own_name_on_connection(
            Gio.DBus.session, HELPER_BUS_NAME, Gio.BusNameOwnerFlags.REPLACE, null, null);

        this._connect(Main.layoutManager, 'monitors-changed', () => {
            this._sync();
            this._emit('MonitorsChanged');
        });
        this._connect(global.display, 'window-created', (_display, window) => {
            this._watchWindow(window);
            this._sync();
            this._scheduleSync();
        });
        this._connect(Main.screenShield, 'locked-changed', () => {
            const locked = Main.screenShield.locked;
            if (locked !== this._locked) {
                this._locked = locked;
                this._emit('ShellLocked', new GLib.Variant('(b)', [locked]));
                this._onLockedChanged(locked);
            }
        });
        this._connect(Main.layoutManager, 'startup-complete', () => this._sync());
        for (const window of global.display.get_tab_list(Meta.TabList.NORMAL_ALL, null))
            this._watchWindow(window);

        this._initFaceDaemonProxy();
        if (this._locked)
            this._onLockedChanged(true);
    }

    _initFaceDaemonProxy() {
        try {
            this._faceDaemon = new FaceDaemonProxy(
                Gio.DBus.session,
                FACE_BUS_NAME,
                FACE_OBJECT_PATH,
                (proxy, error) => {
                    if (error) {
                        console.debug(`[LinuxNotch] FaceDaemon not available: ${error.message}`);
                        return;
                    }
                    this._subscribeFaceSignals();
                }
            );
        } catch (e) {
            console.debug(`[LinuxNotch] Could not create FaceDaemon proxy: ${e}`);
        }
    }

    _subscribeFaceSignals() {
        if (!this._faceDaemon)
            return;

        const idState = this._faceDaemon.connectSignal('ScanState', (_p, _sender, [state, message]) => {
            this._onFaceState(state, message);
        });
        const idFrame = this._faceDaemon.connectSignal('ScanFrame', (_p, _sender, [x, y, w, h, landmarks]) => {
            this._onFaceFrame(x, y, w, h, landmarks);
        });
        const idResult = this._faceDaemon.connectSignal('ScanResult', (_p, _sender, [success, score]) => {
            this._onFaceResult(success, score);
        });
        this._faceSignalIds.push(idState, idFrame, idResult);
    }

    _onLockedChanged(locked) {
        if (this._faceDaemon) {
            try {
                this._faceDaemon.SetLockedRemote(locked, (_res, _err) => {});
            } catch (e) {
                console.debug(`[LinuxNotch] SetLocked failed: ${e}`);
            }
        }

        if (locked) {
            // When screen locks: Record lock time, reset state, and wait for user to wake/open unlock prompt
            this._lockTimestamp = GLib.get_monotonic_time();
            this._scanActive = false;
            this._lockScanSuccess = false;
            this._lockScanFailed = false;
            this._hideLockNotch(true);
            this._setupLockDialogListeners();
        } else {
            // When screen unlocks: Hide notch immediately, cancel active scan and cleanup listeners
            this._scanActive = false;
            this._lockScanSuccess = false;
            this._lockScanFailed = false;
            this._cleanupLockDialogListeners();
            this._hideLockNotch(true);
        }
    }

    _setupLockDialogListeners() {
        this._cleanupLockDialogListeners();

        // 1. Listen for wake-up-screen on screenShield
        const wakeId = Main.screenShield.connect('wake-up-screen', () => {
            this._onUnlockPromptOpened();
        });
        this._dialogSignalIds.push([Main.screenShield, wakeId]);

        const dialog = Main.screenShield?._dialog;
        if (!dialog)
            return;

        // 2. Listen for transition from Clock to Prompt (adjustment value > 0.05)
        if (dialog._adjustment) {
            const adjId = dialog._adjustment.connect('notify::value', () => {
                if (dialog._adjustment.value > 0.05)
                    this._onUnlockPromptOpened();
            });
            this._dialogSignalIds.push([dialog._adjustment, adjId]);
        }

        // 3. Listen for promptBox becoming visible
        if (dialog._promptBox) {
            const visId = dialog._promptBox.connect('notify::visible', () => {
                if (dialog._promptBox.visible)
                    this._onUnlockPromptOpened();
            });
            this._dialogSignalIds.push([dialog._promptBox, visId]);
        }

        // 4. Listen for user interaction events on the lock dialog (key press or click)
        const eventId = dialog.connect('captured-event', (_actor, event) => {
            const type = event.type();
            if (type === Clutter.EventType.KEY_PRESS || type === Clutter.EventType.BUTTON_PRESS) {
                this._onUnlockPromptOpened();
            }
            return Clutter.EVENT_PROPAGATE;
        });
        this._dialogSignalIds.push([dialog, eventId]);
    }

    _cleanupLockDialogListeners() {
        for (const [obj, id] of this._dialogSignalIds) {
            try {
                obj.disconnect(id);
            } catch (_e) {}
        }
        this._dialogSignalIds = [];
    }

    _onUnlockPromptOpened() {
        if (!this._locked)
            return;

        // Cooldown: Do not auto-scan if lock happened less than 1.5 seconds ago (e.g. user just pressed Super+L)
        const elapsedUs = GLib.get_monotonic_time() - this._lockTimestamp;
        if (elapsedUs < LOCK_GRACE_COOLDOWN_US)
            return;

        // Avoid re-triggering while a scan is already running or if scan already succeeded
        if (this._scanActive || this._lockScanSuccess)
            return;

        this._scanActive = true;
        this._showLockNotch();
    }

    _ensureLockNotch() {
        if (this._lockNotch)
            return;

        this._lockNotch = new St.Widget({
            name: 'linux-notch-lock-widget',
            reactive: false,
            can_focus: false,
            width: NOTCH_WIDTH,
            height: NOTCH_HEIGHT,
            visible: false,
        });

        this._drawingArea = new St.DrawingArea({
            width: NOTCH_WIDTH,
            height: NOTCH_HEIGHT,
        });
        this._drawingArea.connect('repaint', (area) => {
            const cr = area.get_context();
            drawIslandShape(cr, NOTCH_WIDTH, NOTCH_HEIGHT, NOTCH_RADIUS, NOTCH_EAR, 0.96);
            this._drawNotchContent(cr, NOTCH_WIDTH, NOTCH_HEIGHT);
            cr.$dispose();
        });
        this._lockNotch.add_child(this._drawingArea);

        this._statusLabel = new St.Label({
            text: 'Starting face scan...',
            style: 'color: rgba(255, 255, 255, 0.85); font-size: 11px; font-weight: 500; text-align: center;',
            x_align: Clutter.ActorAlign.CENTER,
            y_align: Clutter.ActorAlign.END,
            y_expand: true,
        });
        this._statusLabel.set_position(0, NOTCH_HEIGHT - 22);
        this._statusLabel.set_size(NOTCH_WIDTH, 18);
        this._lockNotch.add_child(this._statusLabel);
    }

    _drawNotchContent(cr, width, _height) {
        const cx = width / 2;
        const cy = 27;

        if (this._lockScanSuccess) {
            // Success: Green check circle
            cr.save();
            cr.arc(cx, cy, 13, 0, 2 * Math.PI);
            cr.setSourceRGBA(0.19, 0.82, 0.35, 1.0);
            cr.fill();

            cr.moveTo(cx - 5.5, cy + 0.2);
            cr.lineTo(cx - 1.5, cy + 4.5);
            cr.lineTo(cx + 5.5, cy - 3.8);
            cr.setLineWidth(2.4);
            cr.setLineCap(cairo.LineCap.ROUND);
            cr.setLineJoin(cairo.LineJoin.ROUND);
            cr.setSourceRGBA(1.0, 1.0, 1.0, 1.0);
            cr.stroke();
            cr.restore();
            return;
        }

        if (this._lockScanFailed) {
            // Fail: Soft alert lock/dot
            cr.save();
            cr.arc(cx, cy, 13, 0, 2 * Math.PI);
            cr.setSourceRGBA(1.0, 0.27, 0.23, 0.9);
            cr.fill();

            cr.moveTo(cx, cy - 5.5);
            cr.lineTo(cx, cy + 1.5);
            cr.setLineWidth(2.2);
            cr.setLineCap(cairo.LineCap.ROUND);
            cr.setSourceRGBA(1.0, 1.0, 1.0, 1.0);
            cr.stroke();

            cr.arc(cx, cy + 5.2, 1.2, 0, 2 * Math.PI);
            cr.fill();
            cr.restore();
            return;
        }

        // Live scanning
        cr.save();
        if (this._latestFrame) {
            // Face outline
            cr.arc(cx, cy, 14, 0, 2 * Math.PI);
            cr.setLineWidth(1.8);
            cr.setSourceRGBA(0.2, 0.78, 1.0, 0.9);
            cr.stroke();

            // 5 landmark dots
            if (this._latestLandmarks && this._latestLandmarks.length >= 5) {
                cr.setSourceRGBA(1.0, 1.0, 1.0, 0.95);
                for (const pt of this._latestLandmarks) {
                    const px = cx + (pt[0] - 0.5) * 26;
                    const py = cy + (pt[1] - 0.5) * 26;
                    cr.arc(px, py, 1.6, 0, 2 * Math.PI);
                    cr.fill();
                }
            }
        } else {
            // Idle guide outline
            cr.arc(cx, cy, 13, 0, 2 * Math.PI);
            cr.setLineWidth(1.4);
            cr.setSourceRGBA(1.0, 1.0, 1.0, 0.35);
            cr.stroke();

            cr.arc(cx - 4, cy - 3, 1.4, 0, 2 * Math.PI);
            cr.arc(cx + 4, cy - 3, 1.4, 0, 2 * Math.PI);
            cr.setSourceRGBA(1.0, 1.0, 1.0, 0.45);
            cr.fill();

            cr.arc(cx, cy + 1, 4.5, 0.2 * Math.PI, 0.8 * Math.PI);
            cr.stroke();
        }
        cr.restore();
    }

    _showLockNotch() {
        this._ensureLockNotch();
        this._clearLockTimers();
        this._lockScanSuccess = false;
        this._lockScanFailed = false;
        this._latestFrame = null;
        this._latestLandmarks = null;
        this._statusLabel.set_text('Looking for face...');
        this._statusLabel.style = 'color: rgba(255, 255, 255, 0.85); font-size: 11px; font-weight: 500; text-align: center;';

        const monitors = Main.layoutManager.monitors;
        const primaryIdx = global.display.get_primary_monitor();
        const monitor = monitors[primaryIdx] ?? Main.layoutManager.primaryMonitor ?? monitors[0];
        if (!monitor)
            return;

        const targetX = Math.round(monitor.x + (monitor.width - NOTCH_WIDTH) / 2);
        const targetY = monitor.y;

        const parent = Main.screenShield._dialog ?? Main.uiGroup;
        if (this._lockNotch.get_parent() !== parent) {
            this._lockNotch.get_parent()?.remove_child(this._lockNotch);
            parent.add_child(this._lockNotch);
        }

        this._lockNotch.set_position(targetX, targetY - NOTCH_HEIGHT);
        this._lockNotch.set_opacity(0);
        this._lockNotch.show();
        this._drawingArea.queue_repaint();

        this._lockNotch.ease({
            y: targetY,
            opacity: 255,
            duration: 450,
            mode: Clutter.AnimationMode.EASE_OUT_BACK,
        });

        if (this._faceDaemon) {
            try {
                this._faceDaemon.StartScanRemote((_res, err) => {
                    if (err) {
                        console.debug(`[LinuxNotch] StartScan failed: ${err.message}`);
                    }
                });
            } catch (e) {
                console.debug(`[LinuxNotch] StartScan error: ${e}`);
            }
        }
    }

    _hideLockNotch(immediate = false) {
        this._clearLockTimers();
        if (!this._lockNotch)
            return;

        if (immediate) {
            this._lockNotch.hide();
            this._lockNotch.set_opacity(0);
            return;
        }

        const monitors = Main.layoutManager.monitors;
        const primaryIdx = global.display.get_primary_monitor();
        const monitor = monitors[primaryIdx] ?? Main.layoutManager.primaryMonitor ?? monitors[0];
        const targetY = monitor ? monitor.y - NOTCH_HEIGHT : -NOTCH_HEIGHT;

        this._lockNotch.ease({
            y: targetY,
            opacity: 0,
            duration: 350,
            mode: Clutter.AnimationMode.EASE_IN_QUAD,
            onComplete: () => {
                this._lockNotch.hide();
            },
        });
    }

    _clearLockTimers() {
        if (this._unlockTimer) {
            GLib.source_remove(this._unlockTimer);
            this._unlockTimer = 0;
        }
        if (this._retractTimer) {
            GLib.source_remove(this._retractTimer);
            this._retractTimer = 0;
        }
    }

    _onFaceState(_state, message) {
        if (!this._lockNotch || !this._lockNotch.visible || this._lockScanSuccess)
            return;
        if (this._statusLabel)
            this._statusLabel.set_text(message);
        if (this._drawingArea)
            this._drawingArea.queue_repaint();
    }

    _onFaceFrame(x, y, w, h, landmarks) {
        if (!this._lockNotch || !this._lockNotch.visible || this._lockScanSuccess)
            return;
        this._latestFrame = [x, y, w, h];
        this._latestLandmarks = landmarks;
        if (this._drawingArea)
            this._drawingArea.queue_repaint();
    }

    _onFaceResult(success, _score) {
        if (!this._lockNotch || !this._lockNotch.visible)
            return;

        if (success) {
            this._lockScanSuccess = true;
            this._lockScanFailed = false;
            this._statusLabel.set_text('Welcome');
            this._statusLabel.style = 'color: #30d158; font-size: 12px; font-weight: 700; text-align: center;';
            if (this._drawingArea)
                this._drawingArea.queue_repaint();

            // ~400 ms baad unlock (Phase 0 ka kaam karne wala tareeka)
            this._unlockTimer = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 400, () => {
                this._unlockTimer = 0;
                if (Main.screenShield) {
                    Main.screenShield.deactivate(true);
                }
                return GLib.SOURCE_REMOVE;
            });
        } else {
            this._lockScanSuccess = false;
            this._lockScanFailed = true;
            this._statusLabel.set_text('Face not recognized. Enter password');
            this._statusLabel.style = 'color: #ff453a; font-size: 11px; font-weight: 600; text-align: center;';
            if (this._drawingArea)
                this._drawingArea.queue_repaint();

            // 3 second baad notch wapas upar chala jaye aur scanActive reset karein
            this._retractTimer = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 3000, () => {
                this._retractTimer = 0;
                this._hideLockNotch(false);
                this._scanActive = false; // Allow re-attempting scan on subsequent interaction
                return GLib.SOURCE_REMOVE;
            });
        }
    }

    Attach(appId, monitor, marginTop) {
        this._appId = appId;
        this._monitor = monitor;
        this._marginTop = Math.max(0, marginTop);
        this._sync();
        this._scheduleSync();
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

    _scheduleSync() {
        if (!this._appId || this._attachedWindow || this._syncSource)
            return;
        let attempts = 40;
        this._syncSource = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 50, () => {
            this._sync();
            if (this._attachedWindow || --attempts === 0) {
                this._syncSource = 0;
                return GLib.SOURCE_REMOVE;
            }
            return GLib.SOURCE_CONTINUE;
        });
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
                    wasAbove: target.is_above?.() ?? false,
                };
                target.make_above();
                this._targetPositionId = target.connect('position-changed', () => {
                    if (!this._positioning)
                        this._sync();
                });
                this._targetSizeId = target.connect('size-changed', () => {
                    if (!this._positioning)
                        this._sync();
                });
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

        const frame = target.get_frame_rect();
        const width = frame.width > 0 ? frame.width : this._width;
        const x = Math.round(geometry.x + (geometry.width - width) / 2);
        const y = Math.round(geometry.y + this._marginTop);

        if (frame.x !== x || frame.y !== y) {
            this._positioning = true;
            target.move_frame(false, x, y);
            this._positioning = false;
        }

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
        if (this._targetPositionId)
            target.disconnect(this._targetPositionId);
        if (this._targetSizeId)
            target.disconnect(this._targetSizeId);
        const actor = target.get_compositor_private();
        if (this._hiddenByUs)
            actor?.show();
        if (state && !state.wasAbove)
            target.unmake_above();
        if (state)
            target.move_frame(false, state.x, state.y);
        this._attachedWindow = null;
        this._attachedState = null;
        this._targetPositionId = 0;
        this._targetSizeId = 0;
        this._positioning = false;
        this._hiddenByUs = false;
    }

    _emit(name, parameters = new GLib.Variant('()', [])) {
        if (this._dbus)
            this._dbus.emit_signal(name, parameters);
    }

    disable() {
        this._cleanupLockDialogListeners();
        this._clearLockTimers();
        if (this._lockNotch) {
            this._lockNotch.destroy();
            this._lockNotch = null;
            this._drawingArea = null;
            this._statusLabel = null;
        }
        if (this._faceDaemon) {
            for (const id of this._faceSignalIds)
                this._faceDaemon.disconnectSignal(id);
            this._faceSignalIds = [];
            this._faceDaemon = null;
        }
        if (this._syncSource) {
            GLib.source_remove(this._syncSource);
            this._syncSource = 0;
        }
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
