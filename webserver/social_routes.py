from tornado import web
from tornado.web import url
from social_tornado.handlers import AuthHandler, CompleteHandler, DisconnectHandler

from webserver.base.modules import MODULE_USERS, module_enabled


class SocialLoginGateMixin:
    """社交登录属于「用户与账号」模块：关闭时直接 404，前端按钮已隐藏。"""

    def prepare(self):
        if not module_enabled(MODULE_USERS):
            raise web.HTTPError(404)
        super().prepare()


class GatedAuthHandler(SocialLoginGateMixin, AuthHandler):
    pass


class GatedCompleteHandler(SocialLoginGateMixin, CompleteHandler):
    pass


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
