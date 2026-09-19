/**
 * 外观设置的应用层：把 store 里的外观状态落到「CSS 变量 + Vuetify 主题」。
 *
 * 为什么单独做一个插件而不是写在组件里：外观是全局的，登录页 / 错误页 / 欢迎页
 * 并没有挂载 AppHeader 与外观面板，但仍然需要正确的品牌色与深浅色。
 *
 * 首帧不闪烁由 app/src/app.html 的同步内联脚本负责（读 localStorage 缓存，
 * 在 CSSOM 构建前就把 CSS 变量与 data-* 属性落好）；本插件只做补齐与后续变更。
 */

import { applyAppearance, writeCache } from '~/utils/appearance';

// 会改变渲染结果的 mutation（需要重算 CSS 变量与 Vuetify 主题）；
// setSyncState / markSynced / setSiteTheme 之类的纯状态变更不在此列
const APPLY_MUTATIONS = [
    'appearance/setAppearance',
    'appearance/replaceAppearance',
    'appearance/adoptSiteTheme',
    // 重置为默认：要重新落地 CSS 变量，但**不能**写缓存（见下面的 CACHE_MUTATIONS）
    'appearance/resetAppearance',
];
// 需要写 localStorage 缓存的 mutation：缓存的语义是「用户自己保存过的外观」，
// 站点默认（adoptSiteTheme）与重置（resetAppearance）都不算 —— 前者会让用户被永久钉在
// 当时的站点默认上、管理员之后改 site_theme 就再也跟不动了；后者的目的正是**清掉**缓存、
// 让「站点默认」重新生效。
const CACHE_MUTATIONS = ['appearance/setAppearance', 'appearance/replaceAppearance'];

export default ({ store, app }) => {
    if (!process.client) return;

    const apply = () => applyAppearance(store.state.appearance, app.$vuetify);

    // CSS 变量部分不依赖 Vuetify，可立即生效；但 theme.dark / theme.primary 需要实例就绪。
    // @nuxtjs/vuetify 正常会先于本插件注入，这里仍做几次短重试兜底，避免深色主题下
    // 首屏停在浅色（那会让文字颜色错到下一次 mutation 才被纠正）。
    const applyWhenReady = (attempt) => {
        apply();
        if (!app.$vuetify && attempt < 5) {
            setTimeout(() => applyWhenReady(attempt + 1), 50);
        }
    };

    store.subscribe((mutation) => {
        const type = mutation.type;
        if (CACHE_MUTATIONS.indexOf(type) >= 0) {
            // 状态 → localStorage 缓存（app/src/app.html 的首帧脚本下次读它）
            writeCache(store.state.appearance);
        }
        if (APPLY_MUTATIONS.indexOf(type) >= 0) {
            apply();
        }
    });

    // 缓存 → state → CSS 变量 / Vuetify 主题
    store.dispatch('appearance/loadFromCache');
    applyWhenReady(0);
};
