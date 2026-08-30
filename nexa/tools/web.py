"""Search the web and hand the model the top results as text.

Keyless. Tries DuckDuckGo's HTML endpoints; for news-shaped queries (and as a
fallback when DuckDuckGo returns nothing) it reads Google News' RSS feed. With
open_browser=true it also opens the Google results page in the default browser.
"""

from __future__ import annotations

import html
import re
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urlparse
from xml.etree import ElementTree as ET

import httpx

from nexa.tools.apps import _start
from nexa.tools.base import Tool

_DDG_HTML = "https://html.duckduckgo.com/html/"
_DDG_LITE = "https://lite.duckduckgo.com/lite/"
_GNEWS = "https://news.google.com/rss/search"
_GOOGLE = "https://www.google.com/search?q="
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# html.duckduckgo.com -> result__a / result__snippet ;  lite -> result-link / result-snippet
_A_RE = re.compile(
    r'<a[^>]+class="[^"]*result(?:__a|-link)[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
    re.DOTALL | re.IGNORECASE,
)
_SNIP_RE = re.compile(
    r'class="[^"]*result(?:__snippet|-snippet)[^"]*"[^>]*>(.*?)</(?:a|td)>',
    re.DOTALL | re.IGNORECASE,
)
_NEWS_HINT = re.compile(
    r"\b(news|headline|headlines|breaking|latest|today'?s|this week|update[sd]?)\b",
    re.IGNORECASE,
)


def _text(resp: Any) -> str:
    """Decode a response body as UTF-8 (both endpoints serve UTF-8)."""
    raw = getattr(resp, "content", None)
    if isinstance(raw, (bytes, bytearray)):
        return raw.decode("utf-8", "replace")
    return resp.text


def _clean_text(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", s)).strip()


def _clean_url(href: str) -> str:
    """DDG wraps outbound links as //duckduckgo.com/l/?uddg=<encoded>."""
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg")
        if target:
            return unquote(target[0])
    return href


def _parse_ddg(html_text: str, limit: int) -> list[dict[str, str]]:
    anchors = _A_RE.findall(html_text)
    snippets = _SNIP_RE.findall(html_text)
    out: list[dict[str, str]] = []
    for i, (href, title) in enumerate(anchors):
        url = _clean_url(href)
        if not url or "duckduckgo.com" in urlparse(url).netloc:
            continue
        out.append(
            {
                "title": _clean_text(title) or "(no title)",
                "url": url,
                "snippet": _clean_text(snippets[i]) if i < len(snippets) else "",
            }
        )
        if len(out) >= limit:
            break
    return out


def _parse_news(xml_text: str, limit: int) -> list[dict[str, str]]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    out: list[dict[str, str]] = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        if not title:
            continue
        source_el = item.find("source")
        source = (source_el.text or "").strip() if source_el is not None else ""
        pub = (item.findtext("pubDate") or "").strip()
        meta = " - ".join(x for x in (source, pub) if x)
        out.append(
            {
                "title": title,
                "url": (item.findtext("link") or "").strip(),
                "snippet": meta,
            }
        )
        if len(out) >= limit:
            break
    return out


class WebSearchTool(Tool):
    name = "web_search"
    description = (
        "Search the web and get the top results as text - titles, snippets, "
        "links - so you can read them and answer in your own words. Use for "
        "current facts, news, headlines, prices, definitions ('what does X "
        "mean'), or when the user says 'look this up' / 'search for X'. Set "
        "open_browser=true ONLY when the user explicitly asks to open or show "
        "the results in the browser."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to search for."},
            "open_browser": {
                "type": "boolean",
                "description": "Also open the Google results page in the browser. Default false.",
            },
        },
        "required": ["query"],
    }

    def __init__(self, client: httpx.Client | None = None, max_results: int = 6) -> None:
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(12.0),
            headers={"User-Agent": _UA, "Accept-Language": "en-US,en;q=0.9"},
            follow_redirects=True,
        )
        self._max = max_results

    # ------------------------------------------------------------------
    def _ddg(self, query: str) -> list[dict[str, str]]:
        for url in (_DDG_HTML, _DDG_LITE):
            try:
                resp = self._client.post(url, data={"q": query, "kl": "us-en"})
                resp.raise_for_status()
            except Exception:  # noqa: BLE001 - try the next endpoint
                continue
            hits = _parse_ddg(_text(resp), self._max)
            if hits:
                return hits
        return []

    def _news(self, query: str) -> list[dict[str, str]]:
        try:
            resp = self._client.get(
                _GNEWS,
                params={"q": query, "hl": "en-IN", "gl": "IN", "ceid": "IN:en"},
            )
            resp.raise_for_status()
        except Exception:  # noqa: BLE001
            return []
        return _parse_news(_text(resp), self._max)

    # ------------------------------------------------------------------
    def run(
        self,
        query: str | None = None,
        open_browser: bool = False,
        **kwargs: Any,
    ) -> str:
        q = (query or "").strip()
        if not q:
            return "What should I search for?"

        opened = ""
        if open_browser:
            try:
                _start(_GOOGLE + quote_plus(q))
                opened = " (opened Google in your browser)"
            except Exception:  # noqa: BLE001
                pass

        news_first = bool(_NEWS_HINT.search(q))
        results = self._news(q) if news_first else self._ddg(q)
        label = "Latest news" if news_first and results else "Top results"
        if not results:
            results = self._ddg(q) if news_first else self._news(q)
            if results and not news_first:
                label = "Latest news"
        if not results:
            return f"I couldn't get search results for '{q}'.{opened}"

        lines = [f"{label} for '{q}':"]
        for i, r in enumerate(results, 1):
            snip = f" - {r['snippet']}" if r["snippet"] else ""
            lines.append(f"{i}. {r['title']}{snip} ({r['url']})")
        return "\n".join(lines) + opened
