"""Asynchronous search client for the Chinese Moegirlpedia wiki."""

from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin


MOEGIRL_BASE_URL = "https://zh.moegirl.org.cn"
MOEGIRL_SEARCH_URL = f"{MOEGIRL_BASE_URL}/index.php"


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str


def _compact_text(value: str) -> str:
    return " ".join(str(value or "").split())


def _article_title(value: str) -> str:
    title = _compact_text(value)
    for suffix in (" - 萌娘百科 万物皆可萌的百科全书", " - 萌娘百科"):
        if title.endswith(suffix):
            title = title[: -len(suffix)]
            break
    return title.strip()


class _MoegirlParser(HTMLParser):
    """Extract search results and article metadata without executing page JS."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[SearchResult] = []
        self.page_title = ""
        self.description = ""
        self.canonical_url = ""
        self._title_buffer: list[str] = []
        self._capture_page_title = False
        self._current: dict[str, str] | None = None
        self._capture_result_title = False
        self._capture_result_snippet = False
        self._result_title_buffer: list[str] = []
        self._result_snippet_buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())

        if tag == "title":
            self._capture_page_title = True
            self._title_buffer = []
            return
        if tag == "meta":
            name = (attributes.get("name") or "").casefold()
            property_name = (attributes.get("property") or "").casefold()
            if name == "description" or property_name == "og:description":
                self.description = _compact_text(attributes.get("content") or "")
            return
        if tag == "link" and (attributes.get("rel") or "").casefold() == "canonical":
            self.canonical_url = urljoin(MOEGIRL_BASE_URL, attributes.get("href") or "")
            return
        if tag == "li" and "mw-search-result" in classes:
            self._current = {"title": "", "url": "", "snippet": ""}
            self._result_title_buffer = []
            self._result_snippet_buffer = []
            return
        if self._current is None:
            return
        if tag == "a" and attributes.get("href"):
            # Search result entries put the target article in the heading link.
            if not self._current["url"]:
                self._current["url"] = urljoin(MOEGIRL_BASE_URL, attributes["href"] or "")
                self._capture_result_title = True
                self._result_title_buffer = []
        elif tag == "div" and "searchresult" in classes:
            self._capture_result_snippet = True
            self._result_snippet_buffer = []

    def handle_data(self, data: str) -> None:
        if self._capture_page_title:
            self._title_buffer.append(data)
        if self._current is not None:
            if self._capture_result_title:
                self._result_title_buffer.append(data)
            if self._capture_result_snippet:
                self._result_snippet_buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "title" and self._capture_page_title:
            self.page_title = _article_title("".join(self._title_buffer))
            self._capture_page_title = False
            self._title_buffer = []
        if self._current is None:
            return
        if tag == "a" and self._capture_result_title:
            self._current["title"] = _compact_text("".join(self._result_title_buffer))
            self._capture_result_title = False
            self._result_title_buffer = []
        elif tag == "div" and self._capture_result_snippet:
            self._current["snippet"] = _compact_text("".join(self._result_snippet_buffer))
            self._capture_result_snippet = False
            self._result_snippet_buffer = []
        elif tag == "li":
            title = self._current.get("title", "")
            url = self._current.get("url", "")
            if title and url:
                self.results.append(
                    SearchResult(
                        title=title,
                        url=url,
                        snippet=self._current.get("snippet", ""),
                    )
                )
            self._current = None
            self._capture_result_title = False
            self._capture_result_snippet = False


def parse_moegirl_html(html: str, limit: int = 5) -> list[SearchResult]:
    parser = _MoegirlParser()
    parser.feed(html)
    if parser.results:
        return parser.results[: max(1, limit)]

    # An exact search redirects to the article page. Use the canonical link and
    # meta description as a compact, useful result for the LLM.
    if parser.page_title and not parser.page_title.startswith("搜索结果") and parser.canonical_url:
        return [
            SearchResult(
                title=parser.page_title,
                url=parser.canonical_url,
                snippet=parser.description,
            )
        ][: max(1, limit)]
    return []


class WebSearchClient:
    def __init__(
        self,
        *,
        timeout: float = 8.0,
        endpoint: str = MOEGIRL_SEARCH_URL,
    ) -> None:
        self.timeout = max(1.0, float(timeout))
        self.endpoint = endpoint

    async def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        """Search Moegirlpedia; failures are handled by the plugin boundary."""

        import aiohttp

        params: dict[str, Any] = {"search": str(query or "").strip()}
        timeout = aiohttp.ClientTimeout(total=self.timeout)
        headers = {"User-Agent": "AstrBot-MemeWiki/1.0 (+https://astrbot.app)"}
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(self.endpoint, params=params) as response:
                response.raise_for_status()
                html = await response.text(errors="ignore")
        return parse_moegirl_html(html, limit=limit)
