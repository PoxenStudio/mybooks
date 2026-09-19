<template>
    <v-menu v-model="menu" :close-on-content-click="false" offset-y bottom left min-width="336" max-width="336">
        <template v-slot:activator="{ on, attrs }">
            <v-btn icon v-bind="attrs" v-on="on" :title="$t('appearance.title')">
                <v-icon>mdi-palette-outline</v-icon>
            </v-btn>
        </template>
        <v-card class="appearance-menu-card">
            <v-card-title class="subtitle-2 font-weight-bold pb-2 pt-4">{{ $t('appearance.title') }}</v-card-title>
            <v-card-text class="appearance-menu-body">
                <!-- Theme Mode -->
                <div class="mb-4">
                    <div class="caption text--secondary mb-2">{{ $t('appearance.theme') }}</div>
                    <v-btn-toggle v-model="darkMode" mandatory dense class="w-100 d-flex">
                        <v-btn :value="false" class="flex-grow-1" small>
                            <v-icon left small>mdi-white-balance-sunny</v-icon> {{ $t('appearance.light') }}
                        </v-btn>
                        <v-btn :value="true" class="flex-grow-1" small>
                            <v-icon left small>mdi-weather-night</v-icon> {{ $t('appearance.dark') }}
                        </v-btn>
                    </v-btn-toggle>
                </div>

                <!-- Accent Colors -->
                <div class="mb-4">
                    <div class="caption text--secondary mb-2">{{ $t('appearance.accent') }}</div>
                    <div class="d-flex flex-wrap" style="gap: 8px;">
                        <div
                            v-for="color in accentColors"
                            :key="color.value"
                            class="color-swatch"
                            role="button"
                            tabindex="0"
                            :aria-label="color.value"
                            :aria-pressed="isSameColor(settings.accent, color.value) ? 'true' : 'false'"
                            :style="{ backgroundColor: color.value }"
                            :class="{ 'selected-swatch': isSameColor(settings.accent, color.value) }"
                            @click="update({ accent: color.value })"
                            @keydown.enter.prevent="update({ accent: color.value })"
                            @keydown.space.prevent="update({ accent: color.value })"
                        >
                            <v-icon v-if="isSameColor(settings.accent, color.value)" small color="white" style="text-shadow: 0 1px 2px rgba(0,0,0,0.5);">mdi-check</v-icon>
                        </div>
                    </div>
                </div>

                <!-- Top bar / brand color -->
                <div class="mb-4">
                    <div class="caption text--secondary mb-2">{{ $t('appearance.brandColor') }}</div>
                    <div class="d-flex flex-wrap" style="gap: 8px;">
                        <div
                            v-for="color in brandColors"
                            :key="color.value"
                            class="color-swatch"
                            role="button"
                            tabindex="0"
                            :aria-label="color.label ? $t(color.label) : color.value"
                            :aria-pressed="isBrandColorSelected(color.value) ? 'true' : 'false'"
                            :style="{ backgroundColor: color.value }"
                            :class="{ 'selected-swatch': isBrandColorSelected(color.value) }"
                            :title="color.label ? $t(color.label) : color.value"
                            @click="update({ brandColor: color.value })"
                            @keydown.enter.prevent="update({ brandColor: color.value })"
                            @keydown.space.prevent="update({ brandColor: color.value })"
                        >
                            <v-icon v-if="isBrandColorSelected(color.value)" small color="white" style="text-shadow: 0 1px 2px rgba(0,0,0,0.5);">mdi-check</v-icon>
                        </div>
                    </div>
                    <div class="d-flex align-center mt-2" style="gap: 10px;">
                        <label class="custom-color-field text--secondary">
                            <input type="color" :value="currentBrandColor" @input="update({ brandColor: $event.target.value })" />
                            <span>{{ $t('appearance.custom') }}</span>
                        </label>
                        <v-btn x-small text @click="update({ brandColor: null })">{{ $t('appearance.restore') }}</v-btn>
                    </div>
                    <div v-if="brandIsLight" class="caption text--secondary mt-1">{{ $t('appearance.contrastHint') }}</div>
                </div>

                <!-- Sidebar icon color -->
                <div class="mb-4">
                    <div class="caption text--secondary mb-2">{{ $t('appearance.sidebarIcon') }}</div>
                    <v-btn-toggle v-model="iconMode" mandatory dense class="w-100 d-flex">
                        <v-btn v-for="mode in iconModes" :key="mode.value" :value="mode.value" class="flex-grow-1" small>
                            {{ $t(mode.label) }}
                        </v-btn>
                    </v-btn-toggle>
                    <div v-if="iconMode !== 'multi'" class="d-flex align-center mt-2" style="gap: 10px;">
                        <label class="custom-color-field text--secondary">
                            <input type="color" :value="currentIconColor" @input="update({ sidebarIconMode: 'custom', sidebarIconColor: $event.target.value })" />
                            <span>{{ $t('appearance.iconColor') }}</span>
                        </label>
                    </div>
                </div>

                <!-- Radius -->
                <div class="mb-4">
                    <div class="caption text--secondary mb-2">{{ $t('appearance.radius') }}</div>
                    <v-btn-toggle v-model="radius" mandatory dense class="w-100 d-flex">
                        <v-btn v-for="r in radiusOptions" :key="r.value" :value="r.value" class="flex-grow-1" small>
                            {{ r.label }}
                        </v-btn>
                    </v-btn-toggle>
                </div>

                <!-- Background Pattern -->
                <div class="mb-2">
                    <div class="caption text--secondary mb-2">{{ $t('appearance.background') }}</div>
                    <div class="bg-name-grid">
                        <v-btn
                            v-for="bg in bgOptions"
                            :key="bg.value"
                            x-small
                            depressed
                            :color="settings.background === bg.value ? 'primary' : ''"
                            :class="settings.background === bg.value ? 'white--text' : 'bg-name-btn'"
                            @click="update({ background: bg.value })"
                        >{{ bg.label }}</v-btn>
                    </div>
                </div>

                <!-- Sync actions -->
                <div class="sync-block mt-3 pt-3">
                    <div class="d-flex align-center justify-end" style="gap: 4px;">
                        <v-btn v-if="canUpload" x-small text color="primary" @click="pushToServer">{{ $t('appearance.sync.upload') }}</v-btn>
                        <v-btn x-small text @click="resetAll">{{ $t('appearance.reset') }}</v-btn>
                    </div>
                </div>
            </v-card-text>
        </v-card>
    </v-menu>
</template>

<script>
import {
    BRAND_COLOR_PRESETS,
    DEFAULT_ACCENT,
    SIDEBAR_ICON_MODES,
    isLightBackground,
    resolveBrandColor,
    unifiedIconColor,
} from '~/utils/appearance';

/** 改一下色块就发一次请求太费——合并 600ms 内的连续改动 */
const SAVE_DEBOUNCE_MS = 600;

const ICON_MODE_LABELS = {
    multi: 'appearance.iconMulti',
    theme: 'appearance.iconTheme',
    custom: 'appearance.iconCustom',
};

export default {
    name: 'AppearanceMenu',
    data() {
        return {
            menu: false,
            syncTimer: null,
            // 用来丢弃过期响应：只有最后一次请求的结果才算数
            syncSeq: 0,
            brandColors: BRAND_COLOR_PRESETS,
            iconModes: SIDEBAR_ICON_MODES.map((value) => ({ value, label: ICON_MODE_LABELS[value] })),
            accentColors: [
                { value: '#1976D2', name: 'Blue' },
                { value: '#E91E63', name: 'Pink' },
                { value: '#9C27B0', name: 'Purple' },
                { value: '#4CAF50', name: 'Green' },
                { value: '#FF9800', name: 'Orange' },
                { value: '#607D8B', name: 'Blue Grey' },
                { value: '#009688', name: 'Teal' },
                { value: '#F44336', name: 'Red' },
            ],
            radiusOptions: [
                { label: '0', value: '0px' },
                { label: '0.25', value: '4px' },
                { label: '0.5', value: '8px' },
                { label: '1.0', value: '16px' },
            ],
        };
    },
    computed: {
        // 面板不再自己持有外观数据：唯一真值在 store，任何改动都经 update() 落进去
        settings() {
            return this.$store.state.appearance;
        },
        darkMode: {
            get() {
                return this.settings.darkMode;
            },
            set(value) {
                // 切换深浅色时联动背景图案：浅色 → 浅色图2，深色 → 深色图2，
                // 避免深色主题下还残留一张浅色底图（反之亦然）。
                this.update({ darkMode: value, background: value ? 'repeat-image-4' : 'repeat-image-2' });
            },
        },
        iconMode: {
            get() {
                return this.settings.sidebarIconMode;
            },
            set(value) {
                if (value === 'custom') {
                    // 切到自定义时给个可用的初始色，避免出现「选了自定义但没有颜色」
                    const initial = unifiedIconColor({ sidebarIconMode: 'theme', accent: this.settings.accent });
                    this.update({ sidebarIconMode: value, sidebarIconColor: initial });
                } else {
                    this.update({ sidebarIconMode: value });
                }
            },
        },
        radius: {
            get() {
                return this.settings.radius;
            },
            set(value) {
                this.update({ radius: value });
            },
        },
        currentBrandColor() {
            return resolveBrandColor(this.settings.brandColor);
        },
        brandIsLight() {
            return isLightBackground(this.currentBrandColor);
        },
        currentIconColor() {
            return unifiedIconColor(this.settings) || this.settings.accent || DEFAULT_ACCENT;
        },
        isLogin() {
            return Boolean(this.$store.state.user && this.$store.state.user.is_login);
        },
        syncState() {
            return this.settings.syncState;
        },
        /** 归一化后的同步状态：只要「已同步 / 同步中」之外的情况都允许手动上传 */
        effectiveSyncState() {
            if (this.syncState === 'saving') return 'saving';
            if (!this.isLogin) return 'local';
            if (this.syncState === 'failed') return 'failed';
            if (this.syncState === 'ok') return 'ok';
            return 'unsynced';
        },
        canUpload() {
            return this.isLogin && this.effectiveSyncState !== 'ok' && this.effectiveSyncState !== 'saving';
        },
        bgOptions() {
            return [
                // Fundamental
                { label: this.$t('appearance.bg.default'),       value: 'default' },
                { label: this.$t('appearance.bg.cross'),         value: 'cross' },
                { label: this.$t('appearance.bg.left-diagonal'), value: 'left-diagonal' },
                { label: this.$t('appearance.bg.right-diagonal'),value: 'right-diagonal' },
                // Gradient / Ambient
                { label: this.$t('appearance.bg.aurora'),        value: 'aurora' },
                { label: this.$t('appearance.bg.horizon'),       value: 'horizon' },
                { label: this.$t('appearance.bg.glow'),          value: 'glow' },
                { label: this.$t('appearance.bg.mesh'),          value: 'mesh' },
                // Repeat Images
                { label: this.$t('appearance.bg.repeatImage1'), value: 'repeat-image-1' },
                { label: this.$t('appearance.bg.repeatImage2'), value: 'repeat-image-2' },
                { label: this.$t('appearance.bg.repeatImage3'), value: 'repeat-image-3' },
                { label: this.$t('appearance.bg.repeatImage4'), value: 'repeat-image-4' },
            ];
        },
    },
    beforeDestroy() {
        // 防抖窗口内被销毁（例如刚改完就跳到 /login、/logout、/welcome：这些页面用的是别的
        // layout，AppHeader 会被卸载）时，直接丢掉定时器会让最后一次改动永远不上传，
        // 而且 syncState 会永远停在 'saving' —— canUpload 恒为 false，「保存到账号」按钮
        // 从此不会再出现。所以这里改为立即补发一次，而不是清掉了事。
        if (this.syncTimer) {
            clearTimeout(this.syncTimer);
            this.syncTimer = null;
            this.pushToServer();
        }
    },
    methods: {
        /** 颜色比较统一按小写：sanitize 会把落库的颜色转小写，预设色板里是大写 */
        isSameColor(a, b) {
            return String(a || '').toLowerCase() === String(b || '').toLowerCase();
        },
        isBrandColorSelected(value) {
            return this.isSameColor(this.currentBrandColor, value);
        },
        /** 所有改动的唯一入口：先落 store（立即生效），再排队同步 */
        update(patch) {
            this.$store.commit('appearance/setAppearance', patch);
            this.queueSync();
        },
        queueSync() {
            if (this.syncTimer) clearTimeout(this.syncTimer);
            if (!this.isLogin) {
                this.$store.commit('appearance/setSyncState', 'local');
                return;
            }
            this.$store.commit('appearance/setSyncState', 'saving');
            this.syncTimer = setTimeout(this.pushToServer, SAVE_DEBOUNCE_MS);
        },
        /**
         * 所有外观请求的统一出口：乐观置为「同步中」，并丢弃过期响应（只有最后一次请求算数）。
         * 成功分支交给调用方，失败/未登录的分支在这里统一收口。
         */
        send(request, onSuccess) {
            if (this.syncTimer) {
                clearTimeout(this.syncTimer);
                this.syncTimer = null;
            }
            const seq = ++this.syncSeq;
            this.$store.commit('appearance/setSyncState', 'saving');
            return request().then((rsp) => {
                if (seq !== this.syncSeq) return;
                if (rsp && rsp.err === 'ok') {
                    onSuccess(rsp);
                } else if (rsp && rsp.err === 'user.need_login') {
                    // $backend 已经跳转登录页了，这里只把状态退回「仅本机」
                    this.$store.commit('appearance/markSynced', false);
                    this.$store.commit('appearance/setSyncState', 'local');
                } else {
                    this.$store.commit('appearance/markSynced', false);
                    this.$store.commit('appearance/setSyncState', 'failed');
                    // $backend 只对 not_installed / not_invited / user.need_login / exception
                    // 这几种 err 做提示，外观自己的错误码（appearance.version.unsupported、
                    // appearance.too_large、params.invalid…）会静默变成一个"失败"状态，
                    // 这里显式抛给用户，否则服务端写的提示语等于白写。
                    if (rsp && rsp.msg) this.$alert('error', rsp.msg);
                }
            }).catch(() => {
                if (seq !== this.syncSeq) return;
                this.$store.commit('appearance/markSynced', false);
                this.$store.commit('appearance/setSyncState', 'failed');
            });
        },
        /** 把当前完整设置写到账号（POST /api/user/appearance，见 webserver/handlers/user.py） */
        pushToServer() {
            return this.send(
                () => this.$backend('/user/appearance', {
                    method: 'POST',
                    body: JSON.stringify(this.$store.getters['appearance/settings']),
                }),
                (rsp) => {
                    // 服务端会把归一化后的完整设置回传（它可能丢掉了某些键）。以它为准，
                    // 客户端与服务端就不会长期停在两份不同的值上（白名单漂移时尤其明显）。
                    if (rsp.appearance && typeof rsp.appearance === 'object' && !Array.isArray(rsp.appearance)) {
                        this.$store.commit('appearance/replaceAppearance', rsp.appearance);
                    }
                    this.$store.commit('appearance/markSynced', true);
                    this.$store.commit('appearance/setSyncState', 'ok');
                },
            );
        },
        /** 删掉账号里的外观设置（DELETE /api/user/appearance），让站点默认重新生效 */
        clearOnServer() {
            return this.send(
                () => this.$backend('/user/appearance', { method: 'DELETE' }),
                () => {
                    // 账号里已经没有外观设置了 —— 状态回到「尚未上传」，
                    // 面板会重新显示「保存到账号」，用户可以再决定要不要存一套。
                    this.$store.commit('appearance/markSynced', false);
                    this.$store.commit('appearance/setSyncState', 'unsynced');
                },
            );
        },
        /**
         * 「重置为默认」= 回到「从未保存过外观」：本机清缓存 + 账号侧删掉设置。
         *
         * 刻意**不是**「提交一份内置默认值」：那样会把站点默认（sys.theme，管理员全站设置）
         * 永久顶掉 —— 站点默认只在本机没有外观缓存时生效，而提交会把缓存和账号都填满。
         * 副作用是浅色站点上点一下重置就整站翻成深色，且再也跟不动管理员后来的调整。
         */
        resetAll() {
            this.$store.dispatch('appearance/resetToDefault');
            if (this.isLogin) {
                this.clearOnServer();
            } else {
                this.$store.commit('appearance/setSyncState', 'local');
            }
        },
    },
};
</script>

<style scoped>
.appearance-menu-body {
    max-height: 72vh;
    overflow-y: auto;
}

.color-swatch {
    width: 24px;
    height: 24px;
    border-radius: 50%;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: transform 0.1s ease;
}
.color-swatch:hover {
    transform: scale(1.1);
}
/* 色块是 role=button 的 div（与既有 accent 色块一致），键盘聚焦时需要有可见的焦点环 */
.color-swatch:focus-visible {
    outline: 2px solid var(--primary-color, #1976D2);
    outline-offset: 2px;
}
.selected-swatch {
    box-shadow: 0 0 0 2px var(--v-background-base, #fff), 0 0 0 4px currentColor;
}

.custom-color-field {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    margin: 0;
    font-size: 12px;
    cursor: pointer;
}
.custom-color-field input[type="color"] {
    width: 24px;
    height: 24px;
    padding: 0;
    border: 1px solid rgba(128, 128, 128, 0.4);
    border-radius: 50%;
    background: none;
    cursor: pointer;
}

.bg-name-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 6px;
}
.bg-name-grid .v-btn {
    min-width: 0;
    padding: 0 2px !important;
    font-size: 10px;
}

.sync-block {
    border-top: 1px solid rgba(128, 128, 128, 0.25);
}
</style>
