import functools
import http.server
import socketserver
import threading
import unittest
import urllib.request
from pathlib import Path


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A002 - matches stdlib signature
        return


class StaticServerSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        handler = functools.partial(QuietHandler, directory=str(Path("docs").resolve()))
        cls.server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler)
        cls.server.daemon_threads = True
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def get_text(self, path: str) -> str:
        with urllib.request.urlopen(f"{self.base_url}{path}", timeout=5) as response:
            self.assertEqual(response.status, 200)
            return response.read().decode("utf-8")

    def test_static_pages_and_data_load_over_http(self):
        html = self.get_text("/")
        index_json = self.get_text("/data/index.json")
        company_json = self.get_text("/data/companies/AAPL.json")
        self.assertIn("Stock Valuation Workspace", html)
        self.assertIn('"basePath": "/valuation/"', index_json)
        self.assertIn('"ticker": "AAPL"', company_json)


if __name__ == "__main__":
    unittest.main()
