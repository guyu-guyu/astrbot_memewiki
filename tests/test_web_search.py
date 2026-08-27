import unittest

from web_search import parse_moegirl_html


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


if __name__ == "__main__":
    unittest.main()
