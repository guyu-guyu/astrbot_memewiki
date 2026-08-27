import unittest

from web_search import parse_duckduckgo_html


class WebSearchParserTests(unittest.TestCase):
    def test_duckduckgo_result_parser(self):
        html = (
            '<a class="result__a" href="https://example.com">Title</a>'
            '<a class="result__snippet">Snippet text</a>'
        )
        results = parse_duckduckgo_html(html)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "Title")
        self.assertEqual(results[0].url, "https://example.com")


if __name__ == "__main__":
    unittest.main()
