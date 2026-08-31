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


# ── web_search (DuckDuckGo HTML faked) ───────────────────────────────
class _FakeSearchResp:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


class _FakeSearchClient:
    def __init__(self, text):
        self._text = text

    def get(self, url, params=None):
        return _FakeSearchResp(self._text)

    def post(self, url, data=None):
        return _FakeSearchResp(self._text)


_DDG_SAMPLE = """
<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fa&rut=x">
  First <b>result</b></a>
<a class="result__snippet" href="/x">Snippet <b>one</b>.</a>
<a class="result__a" href="https://example.org/b">Second result</a>
<a class="result__snippet" href="/y">Snippet two.</a>
"""


def test_web_search_parses_and_unwraps_results():
    from nexa.tools.web import WebSearchTool

    out = WebSearchTool(client=_FakeSearchClient(_DDG_SAMPLE)).run(query="python")
    assert "First result" in out
    assert "https://example.com/a" in out       # uddg redirect unwrapped
    assert "Snippet one." in out
    assert "Second result" in out


def test_web_search_needs_a_query():
    from nexa.tools.web import WebSearchTool

    assert "search for" in WebSearchTool(client=_FakeSearchClient("")).run().lower()


def test_web_search_open_browser_launches_google(monkeypatch):
    import nexa.tools.web as web

    launched = []
    monkeypatch.setattr(web, "_start", lambda url: launched.append(url))
    web.WebSearchTool(client=_FakeSearchClient(_DDG_SAMPLE)).run(
        query="today's news", open_browser=True
    )
    assert launched and "google.com/search?q=today" in launched[0]


# ── watch / streaming (launch monkeypatched) ─────────────────────────
def test_watch_resolves_alias_and_opens_search(monkeypatch):
    import nexa.tools.streaming as streaming

    launched = []
    monkeypatch.setattr(streaming, "_start", lambda url: launched.append(url))
    out = streaming.StreamingTool().run(service="disney", title="The Bear")
    assert launched == ["https://www.hotstar.com/in/search?q=The+Bear"]
    assert "jiohotstar" in out.lower()


def test_watch_no_title_opens_home(monkeypatch):
    import nexa.tools.streaming as streaming

    launched = []
    monkeypatch.setattr(streaming, "_start", lambda url: launched.append(url))
    streaming.StreamingTool().run(service="netflix")
    assert launched == ["https://www.netflix.com"]


def test_watch_unknown_service_asks():
    from nexa.tools.streaming import StreamingTool

    assert "which one" in StreamingTool().run(service="mubi").lower()


def test_watch_play_falls_back_when_automation_off(monkeypatch):
    import nexa.tools.streaming as streaming

    launched = []
    monkeypatch.setattr(streaming, "_start", lambda url: launched.append(url))
    monkeypatch.setattr(streaming.browser, "available", lambda: False)
    out = streaming.StreamingTool().run(
        service="netflix", title="Friends", action="play"
    )
    assert launched == ["https://www.netflix.com/search?q=Friends"]
    assert "friends" in out.lower()


# ── whatsapp send (no UI automation -> graceful fallback) ────────────
class _StubContacts:
    def reload(self):
        pass

    def resolve(self, query):
        from nexa.tools.contacts import Contact

        return Contact(name="Vrinda", phone="919876500000")

    def all(self):
        return []


def test_whatsapp_send_prefills_and_reports_manual_step(monkeypatch):
    import nexa.tools.whatsapp as whatsapp

    launched = []
    monkeypatch.setattr(whatsapp, "_start", lambda uri: launched.append(uri))
    monkeypatch.setattr(whatsapp.settings, "ALLOW_UI_AUTOMATION", False)
    monkeypatch.setattr(whatsapp.whatsapp_web, "available", lambda: False)

    tool = whatsapp.WhatsAppTool(contacts=_StubContacts())
    out = tool.run(contact="Vrinda", action="send", message="running late")
    assert launched and "text=running%20late" in launched[0]
    assert "typed" in out.lower()


def test_whatsapp_send_routes_to_web_when_available(monkeypatch):
    import nexa.tools.whatsapp as whatsapp

    calls = []
    monkeypatch.setattr(whatsapp.whatsapp_web, "available", lambda: True)
    monkeypatch.setattr(whatsapp.whatsapp_web, "send",
                        lambda name, msg: calls.append((name, msg)) or f'Sent to {name}: "{msg}"')
    monkeypatch.setattr(whatsapp, "_start", lambda uri: (_ for _ in ()).throw(AssertionError("used desktop")))

    out = whatsapp.WhatsAppTool(contacts=_StubContacts()).run(
        contact="Vrinda", action="send", message="on my way"
    )
    assert calls == [("Vrinda", "on my way")]
    assert "sent to vrinda" in out.lower()


def test_whatsapp_unread_needs_browser_link(monkeypatch):
    import nexa.tools.whatsapp as whatsapp

    monkeypatch.setattr(whatsapp.whatsapp_web, "available", lambda: False)
    out = whatsapp.WhatsAppTool(contacts=_StubContacts()).run(action="unread")
    assert "browser_automation" in out.lower() or "qr" in out.lower()


# ── gmail (not configured) ──────────────────────────────────────────
def test_gmail_not_configured(monkeypatch):
    from nexa.tools.gmail import GmailTool
    import nexa.tools.gmail as gmail

    monkeypatch.setattr(gmail.settings, "GMAIL_ADDRESS", "")
    monkeypatch.setattr(gmail.settings, "GMAIL_APP_PASSWORD", "")
    out = GmailTool().run(action="unread")
    assert "isn't set up" in out.lower()
    assert GmailTool().spec()["function"]["name"] == "gmail"
