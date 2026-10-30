// 功能模块关闭时的页面级守卫。
//
// 页面 HTML 由 SpaStaticHandler 直出（继承 web.StaticFileHandler，不经过
// BaseHandler），后端拦不到「打开页面」这一下，所以页面级跳转只能在前端做。
// 这里只管 UX，真正的安全边界仍在后端的 ModuleGateMixin / module_enabled。
//
// 模块状态随站点信息下发（sys.modules），与导航、详情页按钮、设置区块读的是
// 同一份快照，避免「入口没了但页面还能打开」这种错位。
import { isLoginPublicPath } from "~/utils/loginPublicPaths";

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
            path.startsWith("/admin/user-memos/") ||
            path === "/expected" ||
            path.startsWith("/expected/") ||
            path === "/admin/all-expected" ||
            path.startsWith("/admin/all-expected/") ||
            path === "/soledbooks" ||
            path.startsWith("/soledbooks/") ||
            path === "/booklists" ||
            path.startsWith("/booklists/") ||
            path.startsWith("/booklist/"),
    },
    {
        id: "physical",
        test: (path) => path === "/printbooks" || path.startsWith("/printbooks/"),
    },
    {
        id: "users",
        test: (path) =>
            path === "/signup" ||
            path.startsWith("/signup/") ||
            path === "/admin/users" ||
            path.startsWith("/admin/users/"),
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
    // 未登录且站点开了「必须登录」时，非公开页交给 require_login 处理：
    // 它会送去 /login?next=…，我们再跳一次 "/" 会把 next 丢掉。
    // 公开页（如 /signup）在 require_login 里被直接放行，必须由这里兜住，
    // 否则「必须登录 + 关闭用户模块」时注册页仍会渲染。
    const user = (info && info.user) || app.store.state.user || {};
    const allow = (info && info.sys && info.sys.allow) || {};
    if (!user.is_login && allow.require_login === true && !isLoginPublicPath(route.path)) {
        return;
    }
    redirect("/");
}
