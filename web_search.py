"""Small asynchronous DuckDuckGo HTML search client used by Meme Wiki."""

from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str


class _DuckDuckGoParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[SearchResult] = []
        self._current: dict[str, str] | None = None
        self._mode: str | None = None
        self._buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        if "result__a" in classes:
            self._current = {
                "title": "",
                "url": urljoin(
                    "https://duckduckgo.com", attributes.get("href") or ""
                ),
            }
            self._mode = "title"
            self._buffer = []
        elif "result__snippet" in classes and self._current is not None:
            self._mode = "snippet"
            self._buffer = []

    def handle_data(self, data: str) -> None:
        if self._current is not None and self._mode:
            self._buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or self._current is None or self._mode is None:
            return
        text = " ".join("".join(self._buffer).split())
        if self._mode == "title":
            self._current["title"] = text
        elif self._mode == "snippet":
            self._current["snippet"] = text
            if self._current.get("title") and self._current.get("url"):
                self.results.append(
                    SearchResult(
                        title=self._current["title"],
                        url=self._current["url"],
                        snippet=self._current.get("snippet", ""),
                    )
                )
            self._current = None
        self._mode = None
        self._buffer = []


def parse_duckduckgo_html(html: str, limit: int = 5) -> list[SearchResult]:
    parser = _DuckDuckGoParser()
    parser.feed(html)
    return parser.results[: max(1, limit)]


class WebSearchClient:
    def __init__(
        self,
        *,
        timeout: float = 8.0,
        endpoint: str = "https://html.duckduckgo.com/html/",
    ) -> None:
        self.timeout = max(1.0, float(timeout))
        self.endpoint = endpoint

    async def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        """Search the web; failures are allowed to bubble to the plugin boundary."""

        import aiohttp

        params: dict[str, Any] = {"q": f"{query} 梗 含义 用法", "kl": "cn-zh"}
        timeout = aiohttp.ClientTimeout(total=self.timeout)
        headers = {"User-Agent": "AstrBot-MemeWiki/1.0 (+https://astrbot.app)"}
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(self.endpoint, params=params) as response:
                response.raise_for_status()
                html = await response.text(errors="ignore")
        return parse_duckduckgo_html(html, limit=limit)
