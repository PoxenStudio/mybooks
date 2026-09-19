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

// 只有这两个 mutation 会改变渲染结果；同步状态（appearance/setSyncState 等）不触发重算
const APPLY_MUTATIONS = ['appearance/setAppearance', 'appearance/replaceAppearance'];

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
        if (APPLY_MUTATIONS.indexOf(mutation.type) < 0) return;
        // 状态 → localStorage 缓存（首帧脚本下次读它）
        writeCache(store.state.appearance);
        apply();
    });

    // 缓存 → state → CSS 变量 / Vuetify 主题
    store.dispatch('appearance/loadFromCache');
    applyWhenReady(0);
};
