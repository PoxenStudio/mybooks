// 功能模块关闭时的页面级守卫。
//
// 页面 HTML 由 SpaStaticHandler 直出（继承 web.StaticFileHandler，不经过
// BaseHandler），后端拦不到「打开页面」这一下，所以页面级跳转只能在前端做。
// 这里只管 UX，真正的安全边界仍在后端的 ModuleGateMixin / module_enabled。
//
// 模块状态随站点信息下发（sys.modules），与导航、详情页按钮、设置区块读的是
// 同一份快照，避免「入口没了但页面还能打开」这种错位。
const ROUTE_MODULES = [
    {
        id: "audio",
        test: (path) =>
            path === "/audiobooks" ||
            path.startsWith("/audiobooks/") ||
            path.startsWith("/audio/") ||
            path === "/toolbox/mimo_tts" ||
            path.startsWith("/toolbox/mimo_tts/"),
    },
    {
        id: "community",
        test: (path) =>
            path === "/memos" ||
            path.startsWith("/memos/") ||
            path === "/admin/user-memos" ||
            path === "/expected" ||
            path.startsWith("/expected/") ||
            path === "/admin/all-expected" ||
            path === "/soledbooks" ||
            path.startsWith("/soledbooks/") ||
            path === "/booklists" ||
            path.startsWith("/booklists/") ||
            path.startsWith("/booklist/"),
    },
];

export default async function ({ app, route, redirect }) {
    if (process.server) {
        return;
    }
    const hit = ROUTE_MODULES.find((item) => item.test(route.path));
    if (!hit) {
        return;
    }

    const stored = (app.store.state.sys && app.store.state.sys.modules) || {};
    if (stored[hit.id] === false) {
        redirect("/");
        return;
    }
    if (stored[hit.id] === true) {
        return;
    }

    // 首屏 store 里还没有 sys：等一次 /user/info（60s TTL，不会每页都打接口）
    const info =
        typeof app.$ensureSession === "function" ? await app.$ensureSession() : null;
    const modules = (info && info.sys && info.sys.modules) || stored;
    if (modules[hit.id] !== false) {
        return;
    }
    // 未登录且站点开了「必须登录」时不在这里跳：require_login 会把用户送去
    // /login?next=…，我们再跳一次 "/" 会把 next 丢掉，登录后回不到原页面。
    // 其它情况（游客可访问的站点）仍按模块关闭处理。
    const user = (info && info.user) || app.store.state.user || {};
    const allow = (info && info.sys && info.sys.allow) || {};
    if (!user.is_login && allow.require_login === true) {
        return;
    }
    redirect("/");
}
