"""Weather status and tile backed by wttr.in.

Fetches start when the island becomes visible and reuse cached data for
30 minutes. The request runs off the GTK thread.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.parse
import urllib.request

from gi.repository import GLib, GObject

TTL = 30 * 60
logger = logging.getLogger(__name__)

# wttr.in weather codes → (emoji-free label, symbolic icon)
_ICONS = {
    "113": "weather-clear-symbolic",
    "116": "weather-few-clouds-symbolic",
    "119": "weather-overcast-symbolic",
    "122": "weather-overcast-symbolic",
    "143": "weather-fog-symbolic",
    "248": "weather-fog-symbolic",
    "260": "weather-fog-symbolic",
}


class WeatherService(GObject.Object):
    __gsignals__ = {
        # temp string ("21°"), description, icon name
        "changed": (GObject.SignalFlags.RUN_FIRST, None, (str, str, str)),
    }

    def __init__(self, city: str = ""):
        super().__init__()
        self.city = city
        self.temp = ""
        self.desc = ""
        self.icon = "weather-clear-symbolic"
        self.error = ""
        self._stamp = 0.0
        self._busy = False

    def request(self):
        """Refresh if stale; emits `changed` when data lands."""
        if self._busy or time.time() - self._stamp < TTL:
            if self.temp:
                self.emit("changed", self.temp, self.desc, self.icon)
            return
        self._busy = True
        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self):
        city = self.city.strip()
        url = f"https://wttr.in/{urllib.parse.quote(city, safe='')}?format=j1"
        try:
            with urllib.request.urlopen(url, timeout=8) as r:
                data = json.load(r)
            now = data["current_condition"][0]
            temp = f"{now['temp_C']}°"
            desc = now["weatherDesc"][0]["value"]
            weather_code = int(now["weatherCode"])
            code = str(weather_code)
        except (
            OSError,
            TimeoutError,
            json.JSONDecodeError,
            KeyError,
            IndexError,
            TypeError,
            ValueError,
        ) as error:
            error_message = str(error)
            logger.warning(
                "Weather request failed for %s: %s",
                city or "automatic location",
                error_message,
            )

            def failed():
                self.error = error_message
                self.temp = "—"
                self.desc = "Weather unavailable"
                self._busy = False
                self.emit("changed", self.temp, self.desc, self.icon)
                return False

            GLib.idle_add(failed)
            return
        icon = _ICONS.get(code)
        if icon is None:
            # coarse buckets: thunder, snow, rain, default clouds
            if weather_code in (200, 386, 389, 392, 395):
                icon = "weather-storm-symbolic"
            elif weather_code >= 320:
                icon = "weather-snow-symbolic"
            elif weather_code >= 263:
                icon = "weather-showers-symbolic"
            else:
                icon = "weather-few-clouds-symbolic"

        def done():
            self.temp, self.desc, self.icon = temp, desc, icon
            self.error = ""
            self._stamp = time.time()
            self._busy = False
            self.emit("changed", temp, desc, icon)
            return False
        GLib.idle_add(done)
