# SPDX-License-Identifier: MIT
"""Unit tests of tools/http_records.py: the replay paths, and run()."""
import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import http_records


class Paths(unittest.TestCase):
    def test_url_path(self):
        self.assertEqual(http_records.url_path("https://pypi.org/simple/rich/"), "https/pypi.org/simple/rich")
        self.assertEqual(http_records.url_path("https://pypi.org:443/simple/"), "https/pypi.org/simple")
        self.assertEqual(http_records.url_path("http://mirror.test:8080/a//b"), "http/mirror.test:8080/a/b")
        self.assertEqual(http_records.url_path("https://files.test/f.whl?x=1"), "https/files.test/f.whl")

    def test_index_path(self):
        self.assertEqual(http_records.index_path("https://pypi.org/simple/rich/"), "https/pypi.org/simple/rich/index.html")

    def test_successful_gets(self):
        records = [
            {"method": "GET", "url": "https://a.test/f", "status": 200, "hash": "sha256-a"},
            {"method": "GET", "url": "https://a.test/r", "status": 302, "location": "/f"},
            {"method": "HEAD", "url": "https://a.test/h", "status": 200},
        ]
        self.assertEqual(list(http_records.successful_gets(records)), ["https://a.test/f"])


class Run(unittest.TestCase):
    def test_run_sorts_and_dedups(self):
        records = '{"method": "GET", "url": "https://a.test/f", "status": 200, "hash": "sha256-a"}\n\n'

        def handle(records):
            url = records[0]["url"]
            return [url, url], [
                http_records.inline_entry("https/a.test/z/index.html", "z"),
                http_records.file_entry(url, records[0]["hash"]),
            ]

        stdin, sys.stdin = sys.stdin, io.StringIO(records)
        out = io.StringIO()
        try:
            with redirect_stdout(out):
                http_records.run(handle)
        finally:
            sys.stdin = stdin
        result = json.loads(out.getvalue())
        self.assertEqual(result["claimed"], ["https://a.test/f"])
        self.assertEqual([e["path"] for e in result["entries"]], ["https/a.test/f", "https/a.test/z/index.html"])


if __name__ == "__main__":
    unittest.main()
