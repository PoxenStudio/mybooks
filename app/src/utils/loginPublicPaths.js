// 「必须登录才能访问」(REQUIRE_LOGIN) 下的公开路由清单。
// 路由守卫（middleware/require-login.js）与 $backend 的 need_login 跳转共用这一份，
// 避免两处清单不同步（例如守卫放行 /welcome，而 $backend 还把它弹去登录页）。
export const LOGIN_PUBLIC_PATHS = [
    "/login",
    "/logout",
    "/signup",
    "/welcome",
    "/install",
    "/starting",
];
export const LOGIN_PUBLIC_PREFIXES = [
    // 邮箱激活成功页（后端 /api/active/<user>/<code> 校验完 302 到这里，此时还没登录）
    "/active/",
    // 分享落地页：分享链接优先于「必须登录」，页面本身不含书籍内容，内容由后端按逐本
    // 分享授权校验（见 webserver/handlers/base.py 的 share_grant_allows_path）。
    // 漏掉这一条会让匿名访客打开 /s/<token> 时被守卫弹回 /login，分享链接直接失效。
    "/s/",
];

export function normalizePath(path) {
    // /login/ 与 /login 是同一页（后端 StaticFileHandler 还会把 /login 301 到 /login/）
    const p = (path || "/").replace(/\/+$/, "");
    return p || "/";
}

export function isLoginPublicPath(path) {
    const p = normalizePath(path);
    return LOGIN_PUBLIC_PATHS.includes(p) || LOGIN_PUBLIC_PREFIXES.some((prefix) => p.startsWith(prefix));
}
