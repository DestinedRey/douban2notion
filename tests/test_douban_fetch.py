"""Network failures must retry the current page, then fail visibly."""

import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import douban


def response(status, payload):
    value = requests.Response()
    value.status_code = status
    value._content = json.dumps(payload).encode()
    return value


class DoubanFetchTest(unittest.TestCase):
    @patch("retrying.time.sleep")
    def test_transient_failure_retries_only_the_current_page(self, sleep):
        replies = [response(200, {"interests": ["first"]}),
                   response(503, {}), response(200, {"interests": ["second"]}),
                   response(200, {"interests": []})]
        offsets = []
        def get(url, **kwargs):
            offsets.append(kwargs["params"]["start"])
            self.assertEqual(kwargs["timeout"], (10, 30))
            return replies.pop(0)
        with patch("douban.requests.get", side_effect=get):
            self.assertEqual(douban.fetch_subjects("test", "movie", "done"), ["first", "second"])
        self.assertEqual(offsets, [0, 50, 50, 100])
        sleep.assert_called_once()

    @patch("retrying.time.sleep")
    def test_timeout_stops_after_three_attempts(self, sleep):
        with patch("douban.requests.get", side_effect=requests.Timeout("test timeout")) as get:
            with self.assertRaises(requests.Timeout):
                douban.fetch_subjects("test", "movie", "done")
        self.assertEqual(get.call_count, 3)

    @patch("retrying.time.sleep")
    def test_invalid_response_is_not_treated_as_an_empty_library(self, sleep):
        with patch("douban.requests.get", return_value=response(200, {"error": "unavailable"})) as get:
            with self.assertRaises(ValueError):
                douban.fetch_subjects("test", "book", "done")
        self.assertEqual(get.call_count, 3)


if __name__ == "__main__":
    unittest.main()
