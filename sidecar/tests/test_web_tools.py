import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

from tools import web_tools


class WebToolsTests(unittest.TestCase):
    def test_web_search_uses_exa_mcp_results(self) -> None:
        exa = Mock(
            text=(
                'data: {"result":{"content":[{"type":"text","text":"'
                'Title: Cancer therapy paper\\n'
                'URL: https://example.com/paper\\n'
                'Published: 2026-05-28T00:00:00.000Z\\n'
                'Highlights:\\nPromising treatment result.'
                '"}]}}\n'
            )
        )
        exa.raise_for_status.return_value = None

        with patch.object(web_tools.requests, "post", return_value=exa):
            result = web_tools.web_search("latest cancer treatment paper", max_results=3)

        self.assertTrue(result["ok"])
        self.assertEqual(result["provider"], "exa_mcp")
        self.assertEqual(result["results"][0]["url"], "https://example.com/paper")

    def test_web_search_falls_back_to_parallel_mcp_results(self) -> None:
        parallel = Mock(
            text=(
                '{"jsonrpc":"2.0","id":1,"result":{"content":[{"type":"text","text":'
                '"{\\"results\\":[{\\"url\\":\\"https://example.com/r\\",'
                '\\"title\\":\\"Parallel result\\",\\"publish_date\\":\\"2026-05-01\\",'
                '\\"excerpts\\":[\\"snippet\\"]}]}"'
                '}]}}'
            )
        )
        parallel.raise_for_status.return_value = None

        with patch.object(web_tools.requests, "post", return_value=parallel):
            result = web_tools.web_search("transformer architecture paper", max_results=3)

        self.assertTrue(result["ok"])
        self.assertEqual(result["provider"], "parallel_mcp")
        self.assertEqual(result["results"][0]["title"], "Parallel result")

    def test_web_search_parses_duckduckgo_html_results(self) -> None:
        html = """
        <html><body>
          <a class="result__a" href="/l/?kh=-1&amp;uddg=https%3A%2F%2Fexample.com%2Fpost">Example title</a>
          <a class="result__snippet">Short result snippet</a>
        </body></html>
        """
        response = Mock(text=html)
        response.raise_for_status.return_value = None

        with patch.object(web_tools.requests, "post", side_effect=[Exception("exa down"), Exception("parallel down")]):
            with patch.object(web_tools, "_academic_fallback_search", return_value=[]):
                with patch.object(web_tools.requests, "get", return_value=response):
                    result = web_tools.web_search("example", max_results=3)

        self.assertTrue(result["ok"])
        self.assertEqual(result["results"][0]["title"], "Example title")
        self.assertEqual(result["results"][0]["url"], "https://example.com/post")
        self.assertEqual(result["results"][0]["snippet"], "Short result snippet")

    def test_web_search_falls_back_to_arxiv_when_primary_empty(self) -> None:
        duck = Mock(text="<html></html>")
        duck.raise_for_status.return_value = None
        arxiv = Mock(
            text="""
            <feed xmlns="http://www.w3.org/2005/Atom">
              <entry>
                <id>https://arxiv.org/abs/2501.00663</id>
                <title>Titans: Learning to Memorize at Test Time</title>
                <summary>Transformer architecture paper.</summary>
                <published>2025-01-01T00:00:00Z</published>
              </entry>
            </feed>
            """
        )
        arxiv.raise_for_status.return_value = None

        with patch.object(web_tools.requests, "post", side_effect=[Exception("parallel down"), Exception("exa down")]):
            with patch.object(web_tools.requests, "get", side_effect=[arxiv]):
                result = web_tools.web_search("Titans learning memorize test time arxiv 2025", max_results=3)

        self.assertTrue(result["ok"])
        self.assertEqual(result["provider"], "academic_fallback")
        self.assertEqual(result["results"][0]["source"], "arxiv.org")

    def test_web_search_falls_back_to_pubmed_when_primary_fails(self) -> None:
        duck_error = Exception("network blocked")
        arxiv = Mock(text="<feed xmlns=\"http://www.w3.org/2005/Atom\"></feed>")
        arxiv.raise_for_status.return_value = None
        esearch = Mock()
        esearch.raise_for_status.return_value = None
        esearch.json.return_value = {"esearchresult": {"idlist": ["123"]}}
        esummary = Mock()
        esummary.raise_for_status.return_value = None
        esummary.json.return_value = {
            "result": {
                "123": {
                    "title": "New cancer treatment trial.",
                    "fulljournalname": "Journal",
                    "pubdate": "2026",
                }
            }
        }

        with patch.object(web_tools.requests, "post", side_effect=[Exception("exa down"), Exception("parallel down")]):
            with patch.object(web_tools.requests, "get", side_effect=[esearch, esummary]):
                result = web_tools.web_search("latest cancer treatment paper", max_results=3)

        self.assertTrue(result["ok"])
        self.assertEqual(result["provider"], "academic_fallback")
        self.assertEqual(result["results"][0]["url"], "https://pubmed.ncbi.nlm.nih.gov/123/")

    def test_web_fetch_rejects_non_http_urls(self) -> None:
        result = web_tools.web_fetch("file:///etc/passwd")

        self.assertFalse(result["ok"])
        self.assertIn("http", result["error"])


if __name__ == "__main__":
    unittest.main()
