"""Asynchronous search client for the Chinese Moegirlpedia wiki."""

from __future__ import annotations

from dataclasses import dataclass, replace
from html.parser import HTMLParser
import re
from typing import Any
from urllib.parse import parse_qsl, quote, urljoin, urlsplit, urlunsplit, urlencode


MOEGIRL_BASE_URL = "https://zh.moegirl.org.cn"
MOEGIRL_SEARCH_URL = f"{MOEGIRL_BASE_URL}/index.php?search="
DEFAULT_SEARCH_ENDPOINTS = (MOEGIRL_SEARCH_URL,)


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    score: float = 0.0


def _compact_text(value: str) -> str:
    return " ".join(str(value or "").split())


def _search_key(value: str) -> str:
    """Normalize text for matching while preserving Chinese characters."""

    return re.sub(r"[^\w\u3400-\u9fff]+", "", _compact_text(value).casefold())


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


class _GenericParser(HTMLParser):
    """Extract usable links from search pages without assuming a site layout."""

    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.results: list[SearchResult] = []
        self._current: dict[str, str] | None = None
        self._title_buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        attributes = dict(attrs)
        href = (attributes.get("href") or "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            return
        self._current = {"url": urljoin(self.base_url, href)}
        self._title_buffer = []

    def handle_data(self, data: str) -> None:
        if self._current is not None:
            self._title_buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or self._current is None:
            return
        title = _compact_text("".join(self._title_buffer))
        url = self._current["url"]
        self._current = None
        self._title_buffer = []
        if title and len(title) <= 200 and url not in {item.url for item in self.results}:
            self.results.append(SearchResult(title=title, url=url, snippet=""))


def parse_generic_html(html: str, base_url: str, limit: int = 5) -> list[SearchResult]:
    parser = _GenericParser(base_url)
    parser.feed(html)
    return parser.results[: max(1, limit)]


def score_search_result(query: str, result: SearchResult) -> float:
    """Return a deterministic relevance score in the range [0, 1]."""

    query_key = _search_key(query)
    if not query_key:
        return 0.0
    title_key = _search_key(result.title)
    snippet_key = _search_key(result.snippet)
    url_key = _search_key(result.url)
    if title_key == query_key:
        return 1.0
    if query_key in title_key:
        return 0.9
    if title_key and title_key in query_key:
        return 0.78
    if query_key in snippet_key:
        return 0.68
    if query_key in url_key:
        return 0.62
    return 0.0


def rank_search_results(query: str, results: list[SearchResult], limit: int = 5) -> list[SearchResult]:
    ranked = [replace(result, score=score_search_result(query, result)) for result in results]
    ranked.sort(key=lambda result: result.score, reverse=True)
    return ranked[: max(1, limit)]


def select_search_results(
    query: str,
    batches: list[list[SearchResult]],
    *,
    limit: int = 5,
    min_score: float = 0.72,
) -> list[SearchResult]:
    """Choose the first provider with a high match, otherwise best available."""

    best: list[SearchResult] = []
    best_score = -1.0
    for batch in batches:
        ranked = rank_search_results(query, batch, limit=limit)
        if not ranked:
            continue
        if ranked[0].score >= min_score:
            return ranked
        if ranked[0].score > best_score:
            best = ranked
            best_score = ranked[0].score
    return best


def _request_target(endpoint: str, query: str) -> tuple[str, dict[str, Any]]:
    """Build a request from a URL with either ``{query}`` or a blank parameter."""

    endpoint = str(endpoint or "").strip()
    if "{query}" in endpoint:
        return endpoint.replace("{query}", quote(query, safe="")), {}

    parsed = urlsplit(endpoint)
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    for index, (key, value) in enumerate(pairs):
        if value == "":
            pairs[index] = (key, query)
            return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(pairs), parsed.fragment)), {}
    if pairs:
        return endpoint, {"search": query}
    return endpoint, {"search": query}


def _parse_search_html(html: str, endpoint: str, limit: int) -> list[SearchResult]:
    host = urlsplit(endpoint).netloc.casefold()
    if host.endswith("moegirl.org.cn"):
        return parse_moegirl_html(html, limit=limit)
    return parse_generic_html(html, endpoint, limit=limit)


class WebSearchClient:
    def __init__(
        self,
        *,
        timeout: float = 8.0,
        endpoint: str | None = None,
        endpoints: list[str] | tuple[str, ...] | None = None,
    ) -> None:
        self.timeout = max(1.0, float(timeout))
        configured = endpoints if endpoints is not None else ([endpoint] if endpoint else None)
        self.endpoints = tuple(
            str(item).strip()
            for item in (configured or DEFAULT_SEARCH_ENDPOINTS)
            if str(item).strip()
        ) or DEFAULT_SEARCH_ENDPOINTS
        # Keep the old attribute available for integrations that inspected it.
        self.endpoint = self.endpoints[0]

    async def search(
        self,
        query: str,
        limit: int = 5,
        min_score: float = 0.72,
    ) -> list[SearchResult]:
        """Search providers in order and stop at the first high-confidence batch."""

        import aiohttp

        query = str(query or "").strip()
        if not query:
            return []
        timeout = aiohttp.ClientTimeout(total=self.timeout)
        headers = {"User-Agent": "AstrBot-MemeWiki/1.0 (+https://astrbot.app)"}
        batches: list[list[SearchResult]] = []
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            for endpoint in self.endpoints:
                try:
                    target, params = _request_target(endpoint, query)
                    async with session.get(target, params=params) as response:
                        response.raise_for_status()
                        html = await response.text(errors="ignore")
                    results = _parse_search_html(html, target, limit=limit)
                except Exception:
                    # A failed provider should never prevent trying the next one.
                    continue
                batches.append(results)
                selected = select_search_results(
                    query,
                    batches,
                    limit=limit,
                    min_score=min_score,
                )
                if selected and selected[0].score >= min_score:
                    return selected
        return select_search_results(query, batches, limit=limit, min_score=min_score)
