#!/usr/bin/env python3

import asyncio
import os
import tempfile
import threading
import types
import unittest

from sqlalchemy import create_engine, text
from sqlalchemy.orm import scoped_session, sessionmaker

from webserver.handlers.base import BaseHandler


class TestRunSqliteAsync(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        engine = create_engine("sqlite:///" + os.path.join(self.tmp, "t.db"))
        self.scoped = scoped_session(sessionmaker(bind=engine))
        self.scoped.execute(text("CREATE TABLE t (v INTEGER)"))
        self.scoped.execute(text("INSERT INTO t VALUES (7)"))
        self.scoped.commit()
        self.handler = types.SimpleNamespace(settings={"ScopedSession": self.scoped})

    def tearDown(self):
        self.scoped.remove()

    def test_runs_in_worker_thread_with_own_session(self):
        main_session = self.scoped()

        def job(session, extra):
            return threading.current_thread().name, session is main_session, session.execute(text("SELECT v FROM t")).scalar() + extra

        name, same, value = asyncio.run(BaseHandler.run_sqlite_async(self.handler, job, 1))
        self.assertNotEqual(name, threading.current_thread().name)
        self.assertFalse(same)
        self.assertEqual(value, 8)

    def test_ioloop_not_blocked_while_job_runs(self):
        release = threading.Event()

        def job(_session):
            release.wait(5)
            return "done"

        async def main():
            task = asyncio.ensure_future(BaseHandler.run_sqlite_async(self.handler, job))
            await asyncio.sleep(0.05)
            alive = not task.done()
            release.set()
            return alive, await task

        alive, result = asyncio.run(main())
        self.assertTrue(alive)
        self.assertEqual(result, "done")


if __name__ == "__main__":
    unittest.main()
