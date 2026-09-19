/**
 * 外观设置 —— 共享常量与纯函数
 *
 * 「外观」的三层数据来源（优先级从高到低）：
 *   1. 服务端 user.extra["appearance"]（GET /api/user/info 的 user.appearance）
 *   2. 浏览器缓存 localStorage['appearance_settings']
 *   3. 本文件的默认值
 *
 * 白名单必须与后端 webserver/base/appearance.py 保持一致，
 * tests/test_user_appearance.py 里有对应的守卫用例。
 */

export const STORAGE_KEY = 'appearance_settings';
export const SCHEMA_VERSION = 1;

/** 顶栏 / 品牌面默认色：与改造前的硬编码 #003153 相同，保证默认外观零变化 */
export const DEFAULT_BRAND_COLOR = '#003153';
export const DEFAULT_ACCENT = '#1976D2';
export const DEFAULT_RADIUS = '4px';
export const DEFAULT_BACKGROUND = 'default';

/** 圆角：与 AppearanceMenu 的按钮、appearance.css 的 --app-radius 消费方一一对应 */
export const ALLOWED_RADII = ['0px', '4px', '8px', '16px'];

/** 背景图案：对应 appearance.css 的 html[data-bg-pattern="..."] */
export const ALLOWED_BACKGROUNDS = [
    'default',
    'cross',
    'left-diagonal',
    'right-diagonal',
    'aurora',
    'horizon',
    'glow',
    'mesh',
    'repeat-image-1',
    'repeat-image-2',
    'repeat-image-3',
    'repeat-image-4',
];

/** 侧栏图标配色：multi=保持现在的多彩（默认）/ theme=统一跟随主色 / custom=统一自定义色 */
export const SIDEBAR_ICON_MODES = ['multi', 'theme', 'custom'];

/** 顶栏颜色的预设色板（都偏深，保持白字可读；用户仍可自定义任意色） */
export const BRAND_COLOR_PRESETS = [
    { value: '#003153', label: 'appearance.brandDefault' },
    { value: '#0f172a', label: '' },
    { value: '#1f2937', label: '' },
    { value: '#4c1d95', label: '' },
    { value: '#7f1d1d', label: '' },
    { value: '#064e3b', label: '' },
    { value: '#78350f', label: '' },
    { value: '#0c4a6e', label: '' },
];

const HEX_COLOR = /^#[0-9a-fA-F]{6}$/;

export function defaults() {
    return {
        v: SCHEMA_VERSION,
        darkMode: true,
        brandColor: null,
        accent: DEFAULT_ACCENT,
        radius: DEFAULT_RADIUS,
        background: DEFAULT_BACKGROUND,
        sidebarIconMode: 'multi',
        sidebarIconColor: null,
    };
}

export function isHexColor(value) {
    return typeof value === 'string' && HEX_COLOR.test(value);
}

/** null / 空值代表「使用内置默认品牌色」 */
export function resolveBrandColor(value) {
    return isHexColor(value) ? value.toLowerCase() : DEFAULT_BRAND_COLOR;
}

/**
 * 按白名单过滤一个补丁，语义与后端 normalize_appearance() 一致：
 * 未知键与非法值一律丢弃（不覆盖基线里已有的值）。
 */
export function sanitize(patch, base) {
    const clean = Object.assign({}, base || {});
    if (!patch || typeof patch !== 'object' || Array.isArray(patch)) return clean;
    Object.keys(patch).forEach((key) => {
        const value = patch[key];
        switch (key) {
            case 'darkMode':
                if (typeof value === 'boolean') clean.darkMode = value;
                break;
            case 'brandColor':
            case 'sidebarIconColor':
                // null / '' 表示回到默认，属合法输入
                if (value === null || value === '') clean[key] = null;
                else if (isHexColor(value)) clean[key] = value.toLowerCase();
                break;
            case 'accent':
                if (isHexColor(value)) clean.accent = value.toLowerCase();
                break;
            case 'radius':
                if (ALLOWED_RADII.indexOf(value) >= 0) clean.radius = value;
                break;
            case 'background':
                if (ALLOWED_BACKGROUNDS.indexOf(value) >= 0) clean.background = value;
                break;
            case 'sidebarIconMode':
                if (SIDEBAR_ICON_MODES.indexOf(value) >= 0) clean.sidebarIconMode = value;
                break;
            default:
                break;
        }
    });
    return clean;
}

/** 只保留要落库/提交给服务端的字段 */
export function settingsOf(state) {
    return {
        v: state.v || SCHEMA_VERSION,
        darkMode: state.darkMode !== false,
        brandColor: isHexColor(state.brandColor) ? state.brandColor : null,
        accent: isHexColor(state.accent) ? state.accent : DEFAULT_ACCENT,
        radius: ALLOWED_RADII.indexOf(state.radius) >= 0 ? state.radius : DEFAULT_RADIUS,
        background: ALLOWED_BACKGROUNDS.indexOf(state.background) >= 0 ? state.background : DEFAULT_BACKGROUND,
        sidebarIconMode: SIDEBAR_ICON_MODES.indexOf(state.sidebarIconMode) >= 0 ? state.sidebarIconMode : 'multi',
        sidebarIconColor: isHexColor(state.sidebarIconColor) ? state.sidebarIconColor : null,
    };
}

/** 统一后的侧栏图标色；返回 null 表示「保持现状的多彩」 */
export function unifiedIconColor(settings) {
    if (!settings) return null;
    if (settings.sidebarIconMode === 'theme') {
        return isHexColor(settings.accent) ? settings.accent : DEFAULT_ACCENT;
    }
    if (settings.sidebarIconMode === 'custom') {
        if (isHexColor(settings.sidebarIconColor)) return settings.sidebarIconColor;
        return isHexColor(settings.accent) ? settings.accent : DEFAULT_ACCENT;
    }
    return null;
}

/** WCAG 相对亮度 */
function relativeLuminance(color) {
    const hex = resolveBrandColor(color);
    const channels = [1, 3, 5].map((index) => parseInt(hex.substr(index, 2), 16) / 255);
    const linear = channels.map((c) => (c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4)));
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
}

/**
 * 背景是否偏亮 —— 决定顶栏文字/图标该用深色还是浅色。
 *
 * 分界点取相对亮度 0.179：白字(1.05) 与黑字(0.05) 对同一底色的对比度
 *     (1.05)/(L+0.05) = (L+0.05)/(0.05)  →  L = sqrt(0.05×1.05) − 0.05 ≈ 0.179
 * 在这里相等，所以判据等价于「永远选对比度更高的那一种前景色」。
 * 不要改成拍脑袋的亮度阈值（例如 0.45）：那样 #4CAF50 这类中等亮度的品牌色
 * 会被判成深底、配白字，实际对比度只有约 2.9:1，达不到 WCAG AA。
 * 注意 app/src/app.html 的内联脚本里有一份等价的同步实现，改这里要一起改。
 */
export function isLightBackground(color) {
    return relativeLuminance(color) > 0.179;
}

/** 顶栏前景色：跟着品牌色亮度走，避免浅色顶栏配白字看不清 */
export function navForeground(color) {
    return isLightBackground(color) ? 'rgba(0, 0, 0, 0.87)' : 'rgba(255, 255, 255, 0.87)';
}

/**
 * 站点默认深浅色（sys.theme / localStorage['site_theme']）→ 布尔。
 *
 * 判据是「不等于 'light' 就算深色」，即站点没设置过时回落到内置默认（深色）。
 * app/src/app.html 的首帧内联脚本、AppHeader / login / welcome / error 全部走这一条，
 * 之前有的用 `!== 'light'`、有的用 `=== 'dark'`，首次访问（site_theme 还没落盘）时
 * 两者结论相反，会白白闪一下。
 */
export function siteThemeIsDark(theme) {
    return theme !== 'light';
}

export function readCache() {
    if (typeof localStorage === 'undefined') return null;
    try {
        const raw = localStorage.getItem(STORAGE_KEY);
        if (!raw) return null;
        const parsed = JSON.parse(raw);
        if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null;
        return settingsOf(sanitize(parsed, defaults()));
    } catch (e) {
        return null;
    }
}

export function writeCache(settings) {
    if (typeof localStorage === 'undefined') return;
    try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(settingsOf(settings)));
    } catch (e) {
        // 隐私模式等写不进去：外观本次仍然生效，只是刷新后回到默认
    }
}

/**
 * 删掉本机缓存，使这个浏览器回到「从未保存过外观」的状态。
 *
 * 缓存的有无本身就是语义的一部分：AppHeader / login / welcome / error 都只在本机
 * **没有**缓存时才采用站点默认 sys.theme。「重置为默认」必须真正删掉它，否则用户会被
 * 永久钉死在重置那一刻的内置默认上，管理员之后改站点默认也跟不动。
 */
export function removeCache() {
    if (typeof localStorage === 'undefined') return;
    try {
        localStorage.removeItem(STORAGE_KEY);
    } catch (e) {
        // 与 writeCache 同理：删不掉就当作没缓存过，不影响本次渲染
    }
}

/**
 * 把外观落到「CSS 变量 + Vuetify 主题」两层。
 * 仅客户端可用；app/src/app.html 里有一段等价的同步脚本负责首帧不闪烁。
 */
export function applyAppearance(settings, vuetify) {
    if (typeof document === 'undefined') return;
    const s = settingsOf(Object.assign(defaults(), settings || {}));
    const root = document.documentElement;
    const dark = s.darkMode !== false;
    const brand = resolveBrandColor(s.brandColor);

    root.style.setProperty('--app-nav-bg', brand);
    root.style.setProperty('--app-nav-fg', navForeground(brand));
    // 主色沿用既有变量名（appearance.css 的背景渐变已经在消费它，不引入同义别名）
    root.style.setProperty('--primary-color', s.accent);
    root.style.setProperty('--app-radius', s.radius);
    root.style.setProperty('--dot-color', dark ? 'rgba(255, 255, 255, 0.12)' : 'rgba(0, 0, 0, 0.12)');

    const iconColor = unifiedIconColor(s);
    if (iconColor) root.style.setProperty('--app-sidebar-icon', iconColor);
    else root.style.removeProperty('--app-sidebar-icon');

    root.setAttribute('data-sidebar-icon', s.sidebarIconMode);
    root.setAttribute('data-bg-pattern', s.background);
    root.setAttribute('data-appearance-dark', dark ? '1' : '0');
    // 深色时给 <html> 铺底色，避免首帧（.theme--dark 由 JS 设置）白闪；浅色时清掉
    root.style.backgroundColor = dark ? '#121212' : '';

    if (vuetify && vuetify.theme && vuetify.theme.themes) {
        vuetify.theme.dark = dark;
        if (vuetify.theme.themes.light) vuetify.theme.themes.light.primary = s.accent;
        if (vuetify.theme.themes.dark) vuetify.theme.themes.dark.primary = s.accent;
    }
}
