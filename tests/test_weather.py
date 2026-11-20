import io
import json
import unittest
from unittest.mock import patch

from linux_notch.services.weather import WeatherService


class WeatherServiceTests(unittest.TestCase):
    def setUp(self):
        self.payload = {
            "current_condition": [{
                "temp_C": "24",
                "weatherDesc": [{"value": "Sunny"}],
                "weatherCode": "113",
            }],
        }

    def test_city_weather_is_loaded_and_emitted(self):
        service = WeatherService(" New Delhi ")
        with (
            patch(
                "linux_notch.services.weather.urllib.request.urlopen",
                return_value=io.BytesIO(json.dumps(self.payload).encode()),
            ) as urlopen,
            patch(
                "linux_notch.services.weather.GLib.idle_add",
                side_effect=lambda callback: callback(),
            ),
        ):
            service._fetch()

        urlopen.assert_called_once_with(
            "https://wttr.in/New%20Delhi?format=j1",
            timeout=8,
        )
        self.assertEqual(service.temp, "24°")
        self.assertEqual(service.desc, "Sunny")
        self.assertEqual(service.icon, "weather-clear-symbolic")
        self.assertEqual(service.error, "")

    def test_weather_failure_is_reported_instead_of_silently_discarded(self):
        service = WeatherService("Invalid City")
        changes = []
        service.connect("changed", lambda _s, temp, desc, _icon:
                        changes.append((temp, desc)))
        with (
            patch(
                "linux_notch.services.weather.urllib.request.urlopen",
                side_effect=OSError("network unavailable"),
            ),
            patch(
                "linux_notch.services.weather.GLib.idle_add",
                side_effect=lambda callback: callback(),
            ),
        ):
            service._fetch()

        self.assertEqual(service.temp, "—")
        self.assertEqual(service.desc, "Weather unavailable")
        self.assertEqual(service.error, "network unavailable")
        self.assertEqual(changes, [("—", "Weather unavailable")])


if __name__ == "__main__":
    unittest.main()
