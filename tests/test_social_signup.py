#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import unittest
from types import SimpleNamespace
from unittest import mock

from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

from webserver import models, social_pipeline
from webserver.models import Reader


SOCIAL_CONF = {
    "ALLOW_REGISTER": True,
    "ALLOW_NEW_USER_MANAGE_BOOK": True,
    "ALLOW_NEW_USER_PUSH_BOOK": True,
    "ENABLE_AUTO_NEW_USER_APPROVAL": True,
    "DEFAULT_READ_RANGE": {"mode": 0, "categories": "", "tags": ""},
}


def _conf(**kwargs):
    conf = dict(SOCIAL_CONF)
    conf.update(kwargs)
    return conf


def _social(username, uid="1", provider="qq"):
    return SimpleNamespace(
        provider=provider,
        uid=uid,
        extra_data={"username": username, "profile_image_url": ""},
    )


class TestSignupDefaults(unittest.TestCase):
    def test_defaults_allow_everything(self):
        user = Reader()
        user.apply_signup_defaults(_conf())
        self.assertEqual(user.permission, "")
        self.assertTrue(user.active)

    def test_defaults_restrict_new_users(self):
        user = Reader()
        user.apply_signup_defaults(
            _conf(
                ALLOW_NEW_USER_MANAGE_BOOK=False,
                ALLOW_NEW_USER_PUSH_BOOK=False,
                ENABLE_AUTO_NEW_USER_APPROVAL=False,
                DEFAULT_READ_RANGE={"mode": 2, "categories": "c1", "tags": "t1"},
            )
        )
        self.assertIn(Reader.DISABLE_MANAGE, user.permission)
        self.assertIn(Reader.DISABLE_PUSH, user.permission)
        self.assertFalse(user.active)
        self.assertEqual(user.read_limit, 2)
        self.assertEqual(user.limit_categories, "c1")
        self.assertEqual(user.limit_tags, "t1")


class TestRegistrationGate(unittest.TestCase):
    def test_new_user_rejected_when_register_closed(self):
        with mock.patch.dict(social_pipeline.CONF, {"ALLOW_REGISTER": False}):
            with self.assertRaises(social_pipeline.RegistrationClosed):
                social_pipeline.check_registration(SimpleNamespace(name="qq"), user=None)

    def test_new_user_allowed_when_register_open(self):
        with mock.patch.dict(social_pipeline.CONF, {"ALLOW_REGISTER": True}):
            self.assertIsNone(
                social_pipeline.check_registration(SimpleNamespace(name="qq"), user=None)
            )

    def test_bound_user_allowed_when_register_closed(self):
        with mock.patch.dict(social_pipeline.CONF, {"ALLOW_REGISTER": False}):
            self.assertIsNone(
                social_pipeline.check_registration(
                    SimpleNamespace(name="qq"), user=Reader()
                )
            )


class TestInitNewUser(unittest.TestCase):
    def _run(self, user, conf, is_new=True):
        user.social_auth = SimpleNamespace(all=lambda: [_social("Nick")])
        with mock.patch.object(Reader, "save"):
            with mock.patch.dict(social_pipeline.CONF, conf):
                social_pipeline.init_new_user(
                    None, SimpleNamespace(name="qq"), user=user, is_new=is_new
                )

    def test_new_user_gets_site_defaults(self):
        user = Reader()
        self._run(user, _conf())
        self.assertEqual(user.username, "Nick")
        self.assertEqual(user.extra["kindle_email"], "")
        self.assertTrue(user.active)

    def test_new_user_honours_approval_switch(self):
        user = Reader()
        self._run(user, _conf(ENABLE_AUTO_NEW_USER_APPROVAL=False))
        self.assertFalse(user.active)

    def test_existing_user_is_untouched(self):
        user = Reader()
        self._run(user, _conf(), is_new=False)
        self.assertIsNone(user.username)
        self.assertIsNone(user.active)


class TestSocialPipelineConfig(unittest.TestCase):
    def test_pipeline_runs_gate_before_create_user(self):
        from webserver.constants import SOCIAL_AUTH_PIPELINE

        pipeline = list(SOCIAL_AUTH_PIPELINE)
        self.assertLess(
            pipeline.index("webserver.social_pipeline.check_registration"),
            pipeline.index("social_core.pipeline.user.create_user"),
        )
        self.assertLess(
            pipeline.index("social_core.pipeline.social_auth.social_user"),
            pipeline.index("webserver.social_pipeline.check_registration"),
        )
        self.assertLess(
            pipeline.index("social_core.pipeline.social_auth.associate_user"),
            pipeline.index("webserver.social_pipeline.init_new_user"),
        )


class TestUniqueUsernames(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://")
        models.Base.metadata.create_all(engine)
        self.session = scoped_session(
            sessionmaker(bind=engine, autoflush=False, autocommit=False)
        )
        alice = Reader()
        alice.username = "alice"
        alice.name = "Alice"
        self.session.add(alice)
        self.session.commit()

    def tearDown(self):
        self.session.remove()

    def _new(self, username=None):
        user = Reader()
        user.username = username
        self.session.add(user)
        return user

    def test_username_check_is_case_insensitive(self):
        user = self._new("bob")
        self.assertFalse(user.username_available("ALICE"))
        self.assertTrue(user.username_available("ALICE2"))

    def test_username_check_excludes_self(self):
        alice = self.session.query(Reader).filter(Reader.username == "alice").first()
        self.assertTrue(alice.username_available("alice"))

    def test_ensure_unique_username_adds_suffix(self):
        user = self._new("Alice")
        user.ensure_unique_username()
        self.assertNotEqual(user.username, "Alice")
        self.assertTrue(user.username.startswith("Alice"))
        self.assertTrue(user.username_available(user.username))

    def test_check_and_update_ignores_taken_name(self):
        user = self._new("bob1")
        user.check_and_update(_social("alice"))
        self.assertEqual(user.username, "bob1")
        user.check_and_update(_social("carol"))
        self.assertEqual(user.username, "carol")

    def test_init_keeps_pipeline_username(self):
        user = self._new("alice123")
        user.init(_social("alice"))
        self.assertEqual(user.username, "alice123")

    def test_init_assigns_username_when_empty(self):
        user = self._new()
        user.init(_social("dave"))
        self.assertEqual(user.username, "dave")

    def test_new_social_user_renames_case_collision(self):
        user = self._new("ALICE")
        user.social_auth = SimpleNamespace(all=lambda: [_social("ALICE")])
        with mock.patch.object(Reader, "save"):
            with mock.patch.dict(social_pipeline.CONF, _conf()):
                social_pipeline.init_new_user(
                    None, SimpleNamespace(name="qq"), user=user, is_new=True
                )
        self.assertNotEqual(user.username.lower(), "alice")
        self.assertTrue(user.username_available(user.username))


if __name__ == "__main__":
    unittest.main()
