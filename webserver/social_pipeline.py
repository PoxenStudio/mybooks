# -*- coding: UTF-8 -*-

from social_core.exceptions import AuthException

from webserver import loader

CONF = loader.get_settings()


class RegistrationClosed(AuthException):
    pass


def check_registration(backend, user=None, *args, **kwargs):
    if user:
        return None
    if not CONF.get("ALLOW_REGISTER", False):
        raise RegistrationClosed(backend, "registration closed")
    return None


def init_new_user(strategy, backend, user=None, is_new=False, *args, **kwargs):
    if not user or not is_new:
        return None
    socials = user.social_auth.all()
    if socials:
        user.init(socials[0])
    user.apply_signup_defaults(CONF)
    user.ensure_unique_username()
    user.save()
    return None
