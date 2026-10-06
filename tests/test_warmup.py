#!/usr/bin/env python3

import threading
import unittest
from unittest import mock

from webserver.services import warmup


class TestWarmup(unittest.TestCase):

    def run_warmup(self, recommend=None, **patches):
        legacy = mock.Mock()
        cache = mock.Mock()
        cache.all_book_ids.return_value = set(range(100))
        session = mock.Mock()
        with mock.patch.object(warmup.time, "sleep"):
            warmup.run(legacy, cache, threading.RLock(), recommend, session, 0)
        return legacy, cache, session

    def test_warms_metadata_without_searching(self):
        legacy, cache, _ = self.run_warmup()
        legacy.get_data_as_dict.assert_called_once()
        self.assertEqual(len(legacy.get_data_as_dict.call_args.kwargs["ids"]), 20)
        cache.search.assert_not_called()

    def test_failure_does_not_stop_other_steps(self):
        legacy = mock.Mock()
        legacy.get_data_as_dict.side_effect = RuntimeError("boom")
        cache = mock.Mock()
        cache.all_book_ids.return_value = {1}
        recommend = mock.Mock()
        with mock.patch.object(warmup.time, "sleep"):
            warmup.run(legacy, cache, threading.RLock(), recommend, mock.Mock(), 0)
        recommend.home.assert_called_once()

    def test_recommend_warmed_and_session_removed(self):
        recommend = mock.Mock()
        _, _, session = self.run_warmup(recommend=recommend)
        recommend.home.assert_called_once()
        session.remove.assert_called_once()

    def test_recommend_failure_still_removes_session(self):
        recommend = mock.Mock()
        recommend.home.side_effect = RuntimeError("boom")
        _, _, session = self.run_warmup(recommend=recommend)
        session.remove.assert_called_once()

    def test_start_returns_daemon_thread(self):
        with mock.patch.object(warmup, "run"):
            thread = warmup.start(None, None, None, None, None, 0)
            thread.join(1)
        self.assertTrue(thread.daemon)


if __name__ == "__main__":
    unittest.main()
