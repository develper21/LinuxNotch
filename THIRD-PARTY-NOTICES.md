# Third-party notices

This inventory records known upstream components. System dependency versions
and optional features vary by distribution; check each package's installed
license notices when redistributing a binary.

| Component | Use | License / attribution |
| --- | --- | --- |
| [Lost Island v1.7.2](https://github.com/MarcoZorn/lost-island/tree/v1.7.2) | Base GTK UI and services used by Linux Notch | MIT; copyright Marco Zorn. The applicable notice is retained in [`LICENSE`](LICENSE). |
| GNOME Shell helper extension | Optional Wayland integration | GPL-2.0-or-later; see [`gnome-extension/linux-notch@linuxnotch.org/LICENSE`](gnome-extension/linux-notch@linuxnotch.org/LICENSE). |
| Mochi character and bundled sound effects | Character artwork/animation and sound resources | Copyright attributed to Louis Raillé in [`packaging/sbom.spdx.json`](packaging/sbom.spdx.json); included for this integration under separate permission as recorded by the project. Not covered by the application MIT license. See [`ASSET-ATTRIBUTION.md`](ASSET-ATTRIBUTION.md). |
| PyGObject, GTK 4, libadwaita | Python bindings and desktop UI | LGPL-2.1-or-later. |
| Pycairo | Cairo Python bindings | LGPL-2.1-only OR MPL-1.1. |
| GStreamer and plugins | Local audio playback and optional audio spectrum | LGPL-family licenses; consult the installed distribution package notices. |
| gtk4-layer-shell | Optional Wayland layer-shell backend | MIT. |
| libX11 | Optional X11 backend | MIT/X11; consult the installed distribution package notices. |
| VTE, libsecret, NetworkManager, UPower, GLib, Cairo, PulseAudio utilities | Optional terminal, credential storage, desktop status, rendering, and audio integration | Distribution-provided components; consult the installed package notices for exact versions and licenses. |
| NumPy and OpenCV | Optional face-scan experiment | Python packages with their own licenses; consult the selected package metadata and notices. |
| OpenCV Zoo YuNet model | Optional face detection model, downloaded on request | MIT; pinned source and license links are in the [README](README.md#face-engine-experiment). |
| OpenCV Zoo SFace model | Optional face recognition model, downloaded on request | Apache-2.0; pinned source and license links are in the [README](README.md#face-engine-experiment). |

The generated dependency inventory is
[`packaging/sbom.spdx.json`](packaging/sbom.spdx.json). It is a starting point,
not a substitute for checking exact versions and notices in a release build.
