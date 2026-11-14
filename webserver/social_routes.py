from tornado import web
from tornado.web import url
from social_tornado.handlers import AuthHandler, CompleteHandler, DisconnectHandler

from webserver.base.modules import MODULE_MULTIUSER, module_enabled
from webserver.social_pipeline import RegistrationClosed


class SocialLoginGateMixin:
    """社交登录属于「多用户支持」模块：关闭时直接 404，前端按钮已隐藏。"""

    def prepare(self):
        if not module_enabled(MODULE_MULTIUSER):
            raise web.HTTPError(404)
        super().prepare()


class GatedAuthHandler(SocialLoginGateMixin, AuthHandler):
    pass


class GatedCompleteHandler(SocialLoginGateMixin, CompleteHandler):
    def _complete(self, backend):
        try:
            super(GatedCompleteHandler, self)._complete(backend)
        except RegistrationClosed:
            self.redirect('/login?social_error=register_closed')


class GatedDisconnectHandler(SocialLoginGateMixin, DisconnectHandler):
    pass


SOCIAL_AUTH_ROUTES = [
    url(r'/auth/login/(?P<backend>[^/]+)/?', GatedAuthHandler, name='begin'),
    url(r'/auth/complete/(?P<backend>[^/]+).do', GatedCompleteHandler, name='complete'),
    url(r'/auth/disconnect/(?P<backend>[^/]+)/?', GatedDisconnectHandler,
        name='disconnect'),
    url(r'/auth/disconnect/(?P<backend>[^/]+)/(?P<association_id>\d+)/?',
        GatedDisconnectHandler, name='disconect_individual'),
]
