import unittest
from types import SimpleNamespace
from unittest.mock import patch

from web_search import (
    DEFAULT_SEARCH_ENDPOINTS,
    SearchResult,
    _request_target,
    parse_generic_html,
    parse_moegirl_html,
    rank_search_results,
    select_search_results,
)


class WebSearchParserTests(unittest.TestCase):
    def test_moegirl_search_result_parser(self):
        html = (
            '<li class="mw-search-result">'
            '<div class="mw-search-result-heading">'
            '<a href="/示例">示例梗</a>'
            '</div>'
            '<div class="searchresult">这是一个<span class="searchmatch">梗</span>。</div>'
            '</li>'
        )
        results = parse_moegirl_html(html)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "示例梗")
        self.assertEqual(results[0].url, "https://zh.moegirl.org.cn/示例")
        self.assertEqual(results[0].snippet, "这是一个梗。")

    def test_moegirl_exact_article_parser(self):
        html = (
            "<title>破防 - 萌娘百科 万物皆可萌的百科全书</title>"
            '<meta name="description" content="心理防线被突破。">'
            '<link rel="canonical" href="https://zh.moegirl.org.cn/%E7%A0%B4%E9%98%B2">'
        )
        results = parse_moegirl_html(html)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "破防")
        self.assertEqual(results[0].snippet, "心理防线被突破。")

    def test_default_endpoint_and_query_template(self):
        self.assertEqual(
            DEFAULT_SEARCH_ENDPOINTS[0],
            "https://zh.moegirl.org.cn/index.php?search=",
        )
        target, params = _request_target(DEFAULT_SEARCH_ENDPOINTS[0], "破防 梗")
        self.assertIn("search=%E7%A0%B4%E9%98%B2+%E6%A2%97", target)
        self.assertEqual(params, {})

    def test_generic_parser_and_relevance_ranking(self):
        html = '<nav><a href="/login">登录</a></nav><main><a href="/meme">破防</a></main>'
        results = parse_generic_html(html, "https://example.test/search?q=")
        ranked = rank_search_results("破防", results)
        self.assertEqual(ranked[0].title, "破防")
        self.assertEqual(ranked[0].score, 1.0)

    def test_fallback_selects_first_high_match_batch(self):
        low = [SearchResult("无关结果", "https://one.test/a", "没有关键词")]
        high = [SearchResult("破防", "https://two.test/a", "心理防线被突破")]
        selected = select_search_results("破防", [low, high], min_score=0.72)
        self.assertEqual(selected[0].url, "https://two.test/a")

    def test_fallback_returns_best_available_batch(self):
        first = [SearchResult("破防相关", "https://one.test/a", "")]
        second = [SearchResult("普通页面", "https://two.test/a", "提到了破防")]
        selected = select_search_results("破防", [second, first], min_score=1.01)
        self.assertEqual(selected[0].url, "https://one.test/a")

    def test_client_requests_next_endpoint_after_low_match(self):
        calls = []
        pages = [
            '<a href="/unrelated">无关结果</a>',
            '<a href="/meme">破防</a>',
        ]

        class FakeResponse:
            def __init__(self, html):
                self.html = html

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            def raise_for_status(self):
                return None

            async def text(self, errors="ignore"):
                return self.html

        class FakeSession:
            def __init__(self, **_kwargs):
                self.index = 0

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            def get(self, target, params):
                calls.append((target, params))
                page = pages[self.index]
                self.index += 1
                return FakeResponse(page)

        fake_aiohttp = SimpleNamespace(
            ClientTimeout=lambda total: total,
            ClientSession=lambda **kwargs: FakeSession(**kwargs),
        )

        async def run_search():
            from web_search import WebSearchClient

            client = WebSearchClient(
                endpoints=[
                    "https://one.test/search?q=",
                    "https://two.test/search?q=",
                ]
            )
            return await client.search("破防")

        with patch.dict("sys.modules", {"aiohttp": fake_aiohttp}):
            results = __import__("asyncio").run(run_search())
        self.assertEqual(len(calls), 2)
        self.assertIn("q=%E7%A0%B4%E9%98%B2", calls[0][0])
        self.assertEqual(results[0].url, "https://two.test/meme")


if __name__ == "__main__":
    unittest.main()
