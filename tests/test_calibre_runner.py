#!/usr/bin/env python3

import asyncio
import threading
import time
import unittest

from webserver.handlers.base import BaseHandler
from webserver.services.perf_monitor import PerfMonitor


def make_handler():
    handler = object.__new__(BaseHandler)
    handler.db_lock = threading.RLock()
    return handler


class TestRunCalibre(unittest.TestCase):

    def hold_lock(self, handler):
        held, release = threading.Event(), threading.Event()

        def holder():
            with handler.db_lock:
                held.set()
                release.wait(5)

        thread = threading.Thread(target=holder)
        thread.start()
        held.wait(5)
        self.addCleanup(thread.join)
        self.addCleanup(release.set)
        return release

    def test_read_variant_does_not_wait_for_db_lock(self):
        handler = make_handler()
        self.hold_lock(handler)

        async def main():
            return await asyncio.wait_for(handler.run_calibre_read_async(lambda: "ok"), 2)

        self.assertEqual(asyncio.run(main()), "ok")

    def test_locked_variant_waits_for_db_lock(self):
        handler = make_handler()
        release = self.hold_lock(handler)

        async def main():
            task = asyncio.ensure_future(handler.run_calibre_async(lambda: "ok"))
            await asyncio.sleep(0.2)
            blocked = not task.done()
            release.set()
            return blocked, await asyncio.wait_for(task, 2)

        blocked, result = asyncio.run(main())
        self.assertTrue(blocked)
        self.assertEqual(result, "ok")

    def test_both_variants_record_timing_and_pass_arguments(self):
        handler = make_handler()
        monitor = PerfMonitor.instance()
        monitor.reset()
        monitor.enabled = True
        self.addCleanup(setattr, monitor, "enabled", False)

        def work(a, b=0):
            return a + b

        async def main():
            return await handler.run_calibre_read_async(work, 1, b=2), await handler.run_calibre_async(work, 3)

        self.assertEqual(asyncio.run(main()), (3, 3))
        self.assertEqual(monitor.snapshot()["calibre"]["work"]["run"]["count"], 2)

    def test_exceptions_propagate(self):
        handler = make_handler()

        def boom():
            raise ValueError("x")

        with self.assertRaises(ValueError):
            asyncio.run(handler.run_calibre_read_async(boom))


class TestRecordStage(unittest.TestCase):

    def test_record_stage_in_snapshot(self):
        monitor = PerfMonitor.instance()
        monitor.reset()
        monitor.enabled = True
        self.addCleanup(setattr, monitor, "enabled", False)
        monitor.record_stage("x", 5.0)
        with monitor.stage("y"):
            time.sleep(0.001)
        stages = monitor.snapshot()["stages"]
        self.assertEqual(stages["x"]["count"], 1)
        self.assertEqual(stages["y"]["count"], 1)


if __name__ == "__main__":
    unittest.main()
