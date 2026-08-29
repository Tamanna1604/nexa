"""Tool registry dispatch + clock/weather behaviour (weather HTTP is faked)."""

from __future__ import annotations

import re

from nexa.tools import ClockTool, ToolRegistry, WeatherTool, current_time_string


# ── clock ────────────────────────────────────────────────────────────
def test_current_time_string_shape():
    s = current_time_string()
    # "Friday, 29 August 2026, 03:42 PM ..." -> day, date, time present
    assert re.match(r"[A-Z][a-z]+day, \d{1,2} [A-Z][a-z]+ \d{4}, \d{2}:\d{2} [AP]M", s)


def test_clock_tool_offset():
    tool = ClockTool()
    now = tool.run()
    later = tool.run(offset_hours=3)
    assert now != later          # 3 hours ahead reads differently


# ── registry ─────────────────────────────────────────────────────────
def test_registry_specs_and_dispatch():
    reg = ToolRegistry([ClockTool()])
    specs = reg.specs()
    assert specs[0]["function"]["name"] == "get_datetime"
    assert "AM" in reg.run("get_datetime", {}) or "PM" in reg.run("get_datetime", {})


def test_registry_unknown_tool_is_safe():
    reg = ToolRegistry([ClockTool()])
    assert reg.run("nope", {}).startswith("[error")


def test_registry_tool_exception_is_caught():
    class Boom(ClockTool):
        name = "boom"
        def run(self, **kw):  # noqa: D401
            raise ValueError("kaboom")

    reg = ToolRegistry([Boom()])
    assert "kaboom" in reg.run("boom", {})


# ── weather (faked HTTP) ─────────────────────────────────────────────
class _FakeResp:
    def __init__(self, payload):
        self._p = payload
    def json(self):
        return self._p


class _FakeClient:
    def __init__(self, geo, forecast):
        self._geo, self._forecast = geo, forecast
    def get(self, url, params=None):
        return _FakeResp(self._geo if "geocoding" in url else self._forecast)


def test_weather_formats_conditions():
    geo = {"results": [{"name": "Pune", "country": "India", "latitude": 18.5, "longitude": 73.8}]}
    forecast = {"current": {
        "temperature_2m": 24.3, "apparent_temperature": 25.0,
        "relative_humidity_2m": 60, "weather_code": 2, "wind_speed_10m": 11.2,
    }}
    tool = WeatherTool("Pune", client=_FakeClient(geo, forecast))
    out = tool.run()
    assert "Pune, India" in out
    assert "partly cloudy" in out
    assert "24°C" in out


def test_weather_unknown_place():
    tool = WeatherTool("Pune", client=_FakeClient({"results": []}, {}))
    assert "couldn't find" in tool.run(location="Zzzxxx").lower()


# ── open_app (launch is monkeypatched) ───────────────────────────────
def test_open_app_resolves_alias_and_launches(monkeypatch):
    import nexa.tools.apps as apps

    launched = []
    monkeypatch.setattr(apps, "_start", lambda target: launched.append(target))
    out = apps.OpenAppTool().run(app="WhatsApp")
    assert launched == ["whatsapp:"]        # alias resolved
    assert "opening whatsapp" in out.lower()


def test_open_app_unknown_falls_through_to_name(monkeypatch):
    import nexa.tools.apps as apps

    launched = []
    monkeypatch.setattr(apps, "_start", lambda target: launched.append(target))
    apps.OpenAppTool().run(app="someweirdapp")
    assert launched == ["someweirdapp"]     # no alias -> hand the bare name to the OS


def test_open_app_missing_arg():
    from nexa.tools.apps import OpenAppTool

    assert "which app" in OpenAppTool().run().lower()


def test_open_app_launch_failure_is_reported(monkeypatch):
    import nexa.tools.apps as apps

    def boom(_):
        raise FileNotFoundError()

    monkeypatch.setattr(apps, "_start", boom)
    assert "couldn't find" in apps.OpenAppTool().run(app="ghost").lower()
