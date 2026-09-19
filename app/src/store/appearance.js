/**
 * 外观设置的运行时唯一真值
 *
 * 为什么要有这层：顶栏品牌色、侧栏图标配色、深浅色、圆角、背景图案原本散落在
 * AppHeader / AppearanceMenu 各自的 data 里，且只有 localStorage。集中到 store 后
 * 「面板改 → 状态变 → CSS 变量与 Vuetify 主题跟着变」是一条单向链路，
 * 落库（服务端）与落缓存（localStorage）都由 plugins/appearance.js 订阅 mutation 完成。
 *
 * syncState 取值：
 *   idle      初始
 *   local     仅保存在本机（未登录）
 *   unsynced  已登录，但账号里还没有这套外观设置
 *   saving    正在同步
 *   ok        已同步到账号
 *   failed    同步失败（本地已生效，稍后会重试）
 */

import { defaults, sanitize, settingsOf, readCache } from '~/utils/appearance';

/** 显式命名空间：state 落在 $store.state.appearance，mutation 名为 appearance/xxx */
export const namespaced = true;

export const state = () => Object.assign(defaults(), {
    syncState: 'idle',
    synced: false,
});

export const getters = {
    /** 可提交给服务端的完整设置（不含 syncState 等纯本地字段） */
    settings: (state) => settingsOf(state),
    /** 是否处于「侧栏图标统一着色」模式 */
    unifiedIcons: (state) => state.sidebarIconMode === 'theme' || state.sidebarIconMode === 'custom',
};

export const mutations = {
    /** 补丁式更新：非法值会被 sanitize 丢掉，不影响已有值 */
    setAppearance(state, patch) {
        Object.assign(state, settingsOf(sanitize(patch, state)));
    },
    /** 整体替换（读缓存 / 服务端下发 / 重置时用） */
    replaceAppearance(state, settings) {
        Object.assign(state, settingsOf(sanitize(settings, defaults())));
    },
    /**
     * 采用站点默认深浅色（管理员设置的 sys.theme），由 AppHeader 在
     * 「本机没有外观缓存」时调用，**不**写 localStorage 缓存（缓存语义见 plugins/appearance.js）。
     *
     * 为什么要走 mutation 而不是像以前那样直接改 $vuetify.theme.dark：
     * 深浅色的运行时真值在 store，只改 Vuetify 会让两者长期不一致 —— 面板的选中态会错位，
     * 而且用户之后动任何一项外观都会触发 applyAppearance()，用 store 里的旧值把整站主题盖回去。
     */
    adoptSiteTheme(state, dark) {
        state.darkMode = Boolean(dark);
    },
    setSyncState(state, value) {
        state.syncState = value;
    },
    markSynced(state, value) {
        state.synced = Boolean(value);
    },
};

export const actions = {
    /**
     * 启动时把浏览器缓存灌进 state。
     * 首帧的 CSS 变量已由 app/src/app.html 的内联脚本落好，这里只补齐 Vuex 与 Vuetify 主题。
     */
    loadFromCache({ commit }) {
        const cached = readCache();
        if (cached) commit('replaceAppearance', cached);
    },

    /**
     * 账号级外观覆盖本地（数据来自 GET /api/user/info 的 user.appearance）。
     * 服务端返回 {} 表示用户没保存过 —— 这时保持「本地缓存 / 站点默认」不动，
     * 仅把状态标成「尚未上传」，绝不擅自把本地值写进账号。
     * @return {boolean} 是否应用了服务端的值
     */
    applyFromServer({ commit }, serverAppearance) {
        if (!serverAppearance || typeof serverAppearance !== 'object' || Array.isArray(serverAppearance)
            || Object.keys(serverAppearance).length === 0) {
            commit('markSynced', false);
            commit('setSyncState', 'unsynced');
            return false;
        }
        commit('replaceAppearance', serverAppearance);
        commit('markSynced', true);
        commit('setSyncState', 'ok');
        return true;
    },

    resetToDefault({ commit }) {
        commit('replaceAppearance', defaults());
        commit('markSynced', false);
        commit('setSyncState', 'idle');
    },

    setSyncState({ commit }, value) {
        commit('setSyncState', value);
    },
};
