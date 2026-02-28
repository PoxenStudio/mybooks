/**
 * theme.js — 全局主题切换插件
 *
 * 注册后在所有组件中暴露：
 *   this.$setTheme(name, persist?)   — 切换主题（默认持久化用户偏好）
 *   this.$getTheme()                 — 获取当前主题名
 *   this.$setSiteDefaultTheme(name)  — 记录管理员全站默认（不覆盖用户偏好）
 *
 * localStorage 键：
 *   user_theme  — 用户个人偏好（优先级最高）
 *   site_theme  — 管理员全站默认（次级）
 */

const USER_KEY    = 'user_theme';
const SITE_KEY    = 'site_theme';
const DEFAULT     = 'light';
const VALID_THEMES = new Set(['light', 'dark']);

// 主题元数据缓存（从 /themes/index.json 加载）
let _themeIndex = null;

async function loadThemeIndex() {
  if (_themeIndex) return _themeIndex;
  try {
    const res = await fetch('/themes/index.json');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    _themeIndex = await res.json();
  } catch (e) {
    // 静默降级：使用内置默认值
    _themeIndex = [
      { name: 'light', label: '浅色', vuetify_dark: false },
      { name: 'dark',  label: '深色', vuetify_dark: true  },
    ];
  }
  // 填充有效集合
  _themeIndex.forEach(t => VALID_THEMES.add(t.name));
  return _themeIndex;
}

/**
 * 同步 Vuetify 语义色：从已激活的 CSS 变量读取，写入 $vuetify.theme.themes
 * 须在 data-theme attribute 更新且浏览器完成样式重算后调用。
 */
function syncVuetifySemanticColors(vuetify, themeName) {
  const style = getComputedStyle(document.documentElement);
  const get   = v => style.getPropertyValue(v).trim();

  const semanticMap = {
    primary:   '--tb-color-primary',
    secondary: '--tb-color-secondary',
    accent:    '--tb-color-accent',
    error:     '--tb-color-error',
    warning:   '--tb-color-warning',
    info:      '--tb-color-info',
    success:   '--tb-color-success',
  };

  const target = vuetify.theme.themes[themeName];
  if (!target) return;

  for (const [vuetifyKey, cssVar] of Object.entries(semanticMap)) {
    const val = get(cssVar);
    if (val) target[vuetifyKey] = val;
  }
}

export default ({ app }, inject) => {
  /**
   * 切换主题
   * @param {string}  name     主题名称，如 'light' / 'dark'
   * @param {boolean} persist  是否将选择持久化到 localStorage（默认 true）
   */
  const setTheme = async (name, persist = true) => {
    // 参数校验与降级
    const index = await loadThemeIndex();
    const meta  = index.find(t => t.name === name);
    if (!meta) {
      console.warn(`[theme] Unknown theme "${name}", falling back to "${DEFAULT}"`);
      return setTheme(DEFAULT, persist);
    }

    // 1. 设置 HTML attribute → 驱动 :root[data-theme] CSS 变量
    document.documentElement.setAttribute('data-theme', name);

    // 2. 持久化用户选择
    if (persist) {
      try { localStorage.setItem(USER_KEY, name); } catch (_) {}
    }

    // 3. 同步 Vuetify dark flag（控制 .theme--dark / .theme--light class）
    app.$vuetify.theme.dark = meta.vuetify_dark;

    // 4. 等浏览器完成样式重算后同步 Vuetify 语义色
    await new Promise(resolve => requestAnimationFrame(resolve));
    syncVuetifySemanticColors(app.$vuetify, name);
  };

  /**
   * 获取当前激活的主题名
   */
  const getTheme = () =>
    (typeof document !== 'undefined'
      ? document.documentElement.getAttribute('data-theme')
      : null) || DEFAULT;

  /**
   * 设置管理员全站默认主题（写入 site_theme）。
   * 仅当用户尚未设置个人偏好时才实际切换显示。
   */
  const setSiteDefaultTheme = (name) => {
    try { localStorage.setItem(SITE_KEY, name); } catch (_) {}
    const userPref = (() => { try { return localStorage.getItem(USER_KEY); } catch (_) { return null; } })();
    if (!userPref) {
      // 不记录为用户偏好（persist = false），只切换显示
      return setTheme(name, false);
    }
  };

  inject('setTheme',            setTheme);
  inject('getTheme',            getTheme);
  inject('setSiteDefaultTheme', setSiteDefaultTheme);
};
