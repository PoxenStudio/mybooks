<template>
    <v-card
        class="booklist-card"
        :style="{ borderLeftColor: borderColor }"
        :to="clickable ? `/booklist/${booklist.id}` : undefined"
    >
        <v-chip v-if="showRecommendBadge && booklist.is_sticky" x-small color="orange darken-4" text-color="white" class="booklist-recommend-badge">
            {{ $t('booklist.recommendedBadge') }}
        </v-chip>

        <v-card-text class="pb-2">
            <div class="d-flex align-start">
                <div class="flex-grow-1" style="min-width: 0">
                    <div class="d-flex align-center flex-wrap">
                        <span class="booklist-name text-truncate">{{ booklist.name }}</span>
                        <v-icon v-if="!booklist.is_public" small class="ml-1" color="grey">mdi-lock-outline</v-icon>
                        <v-chip v-if="showGuestReadBadge" x-small color="teal" text-color="white" class="ml-2">
                            <v-icon x-small left>mdi-lock-open-variant-outline</v-icon>{{ $t('booklist.guestReadBadge') }}
                        </v-chip>
                    </div>
                    <div class="booklist-description text-truncate">{{ booklist.description || $t('booklist.noDescription') }}</div>
                </div>

                <div class="booklist-owner d-flex align-center ml-2" @click.stop.prevent>
                    <v-avatar size="28" class="mr-1">
                        <v-img v-if="booklist.owner && booklist.owner.avatar" :src="booklist.owner.avatar"></v-img>
                        <v-icon v-else>mdi-account-circle</v-icon>
                    </v-avatar>
                    <span class="grey--text text-caption text-truncate" style="max-width: 90px">{{ booklist.owner && booklist.owner.username }}</span>
                </div>
            </div>

            <div class="d-flex align-center mt-2 booklist-stats">
                <span class="mr-4"><v-icon x-small class="mr-1">mdi-bookmark-outline</v-icon>{{ booklist.book_count }}</span>
                <span class="mr-4"><v-icon x-small class="mr-1">mdi-eye-outline</v-icon>{{ booklist.view_count }}</span>
                <span class="mr-4 booklist-like" :class="{ 'booklist-like--active': booklist.liked_by_me }" @click.stop.prevent="$emit('toggle-like', booklist)">
                    <v-icon x-small class="mr-1" :color="booklist.liked_by_me ? 'red' : undefined">{{ booklist.liked_by_me ? 'mdi-heart' : 'mdi-heart-outline' }}</v-icon>{{ booklist.like_count }}
                </span>

                <v-spacer></v-spacer>

                <v-btn v-if="isAdmin" x-small text :color="booklist.is_sticky ? 'orange darken-4' : undefined" @click.stop.prevent="$emit('toggle-sticky', booklist)">
                    <v-icon x-small left>mdi-pin</v-icon>{{ booklist.is_sticky ? $t('booklist.unpin') : $t('booklist.pin') }}
                </v-btn>

                <v-menu v-if="showManage" offset-y @click.stop.prevent>
                    <template v-slot:activator="{ on, attrs }">
                        <v-btn icon x-small v-bind="attrs" v-on="on" @click.stop.prevent>
                            <v-icon small>mdi-dots-vertical</v-icon>
                        </v-btn>
                    </template>
                    <v-list dense>
                        <v-list-item @click="$emit('edit', booklist)">
                            <v-list-item-icon><v-icon small>mdi-pencil</v-icon></v-list-item-icon>
                            <v-list-item-title>{{ $t('common.edit') }}</v-list-item-title>
                        </v-list-item>
                        <v-list-item @click="$emit('toggle-visibility', booklist)">
                            <v-list-item-icon><v-icon small>{{ booklist.is_public ? 'mdi-lock-outline' : 'mdi-earth' }}</v-icon></v-list-item-icon>
                            <v-list-item-title>{{ booklist.is_public ? $t('booklist.makePrivate') : $t('booklist.makePublic') }}</v-list-item-title>
                        </v-list-item>
                        <v-menu offset-x open-on-hover>
                            <template v-slot:activator="{ on, attrs }">
                                <v-list-item v-bind="attrs" v-on="on">
                                    <v-list-item-icon><v-icon small>mdi-palette-outline</v-icon></v-list-item-icon>
                                    <v-list-item-title>{{ $t('booklist.changeColor') }}</v-list-item-title>
                                </v-list-item>
                            </template>
                            <v-list dense class="d-flex flex-wrap booklist-color-menu">
                                <v-btn
                                    v-for="c in colors"
                                    :key="c.key"
                                    icon
                                    small
                                    class="ma-1"
                                    :style="{ backgroundColor: dark ? c.dark : c.light }"
                                    @click="$emit('change-color', { booklist, color: c.key })"
                                >
                                    <v-icon v-if="booklist.color === c.key" small color="white">mdi-check</v-icon>
                                </v-btn>
                            </v-list>
                        </v-menu>
                        <v-divider></v-divider>
                        <v-list-item @click="$emit('delete', booklist)">
                            <v-list-item-icon><v-icon small color="red">mdi-delete-outline</v-icon></v-list-item-icon>
                            <v-list-item-title class="red--text">{{ $t('common.delete') }}</v-list-item-title>
                        </v-list-item>
                    </v-list>
                </v-menu>
            </div>
        </v-card-text>

        <v-divider></v-divider>

        <div
            ref="coversViewport"
            class="booklist-covers"
            :class="{
                'booklist-covers--marquee': marqueeActive,
                'booklist-covers--offscreen': marqueeActive && !inView,
                'booklist-covers--masked': coversOverflow,
            }"
        >
            <template v-if="covers.length">
                <div class="booklist-covers-track" :style="marqueeActive ? { animationDuration: marqueeDuration } : null">
                    <v-img
                        v-for="(c, i) in renderedCovers"
                        :key="'cover-' + i + '-' + c.book_id"
                        :src="c.thumb || c.img"
                        eager
                        :aria-hidden="i >= covers.length ? 'true' : null"
                        class="booklist-cover-item"
                        :aspect-ratio="11 / 15"
                    ></v-img>
                </div>
            </template>
            <div v-else class="booklist-covers-empty grey--text text-caption">{{ $t('booklist.noBooks') }}</div>
        </div>
    </v-card>
</template>

<script>
import { BOOKLIST_COLORS } from '~/utils/booklistColors';

// 封面之间的间距（用 margin-right 而不是 gap：这样 track 总宽 = 2 × 单份内容宽，
// 循环动画平移到 -50% 时正好接上第二份开头，不会出现半格跳动）
const COVER_GAP = 4;
// 滚动线速度，px/s。封面越多滚得越久，而不是滚得越快
const MARQUEE_SPEED = 26;

export default {
    name: 'BookListCard',
    props: {
        booklist: { type: Object, required: true },
        isAdmin: { type: Boolean, default: false },
        showManage: { type: Boolean, default: false },
        showRecommendBadge: { type: Boolean, default: false },
        clickable: { type: Boolean, default: true },
    },
    data() {
        return {
            colors: BOOKLIST_COLORS,
            // 下面四个只在客户端 mounted 后才会被改写，SSR 与首次渲染都保持初始值，
            // 避免 hydration 前后 DOM 不一致
            marqueeActive: false,
            inView: true,
            reducedMotion: false,
            // 封面条内容是否横向溢出（两端淡出遮罩的开关），同样只在客户端实测后改写
            coversOverflow: false,
            // 一份封面内容的实测宽度（px），只在 updateMarquee 里量到真实几何后改写，
            // 0 表示尚未测量，marqueeDuration 会退回按 CSS 固定宽度估算
            measuredCopyWidth: 0,
        };
    },
    computed: {
        dark() {
            return this.$vuetify.theme.dark;
        },
        borderColor() {
            const c = this.colors.find(item => item.key === this.booklist.color) || this.colors[0];
            return this.dark ? c.dark : c.light;
        },
        showGuestReadBadge() {
            return !!this.booklist.guest_read && !this.$store.state.sys.allow.read;
        },
        covers() {
            return (this.booklist.cover_books || []).slice(0, 15);
        },
        // 首页动效总开关（设置 › 站点与外观 › 首页与列表 › 首页动效，2026-10 起含原
        // 「书单封面自动滚动」）。sys 尚未加载时是空对象，此时按开启处理，避免首屏误判成关闭
        coverScrollEnabled() {
            const sys = this.$store && this.$store.state && this.$store.state.sys;
            return !sys || sys.home_motion !== false;
        },
        // 需要滚动时把封面复制一份接在后面，形成无缝循环
        renderedCovers() {
            return this.marqueeActive ? this.covers.concat(this.covers) : this.covers;
        },
        marqueeDuration() {
            const count = this.covers.length;
            if (!count) {
                return '30s';
            }
            // 优先用 updateMarquee 实测到的一份内容宽度，未测量时退回「CSS 固定宽 60 + 间距」估算，
            // 保证首帧（mounted 前 / SSR）也有合理时长
            const oneCopyWidth = this.measuredCopyWidth > 0
                ? this.measuredCopyWidth
                : count * (60 + COVER_GAP);
            // 纯按「一份内容的宽度 ÷ 线速度」算，不留 14s 之类的最小值：
            // 一旦夹了下限，短封面的书单就会滚得比设定的 26px/s 慢
            const seconds = oneCopyWidth / MARQUEE_SPEED;
            return Math.max(seconds, 1).toFixed(1) + 's';
        },
    },
    watch: {
        covers() {
            // 书单封面数量变化后重新判断要不要滚（el 尺寸没变，ResizeObserver 不会触发）
            this.$nextTick(this.updateMarquee);
        },
        coverScrollEnabled(enabled) {
            // 站长在设置里关掉后，已挂载的卡片立即停下（不必刷新页面）
            if (!enabled) {
                this.marqueeActive = false;
            } else {
                this.$nextTick(this.updateMarquee);
            }
        },
    },
    mounted() {
        this.reducedMotion = this.detectReducedMotion();
        this.bindReducedMotion();
        this.bindObservers();
        this.updateMarquee();
    },
    beforeDestroy() {
        if (this.resizeObserver) {
            this.resizeObserver.disconnect();
            this.resizeObserver = null;
        }
        if (this.intersectionObserver) {
            this.intersectionObserver.disconnect();
            this.intersectionObserver = null;
        }
        if (this.resizeFallbackHandler) {
            window.removeEventListener('resize', this.resizeFallbackHandler);
            this.resizeFallbackHandler = null;
        }
        if (this.reducedMotionQuery && this.onReducedMotionChange) {
            if (this.reducedMotionQuery.removeEventListener) {
                this.reducedMotionQuery.removeEventListener('change', this.onReducedMotionChange);
            } else if (this.reducedMotionQuery.removeListener) {
                // 老版 Safari
                this.reducedMotionQuery.removeListener(this.onReducedMotionChange);
            }
        }
        this.reducedMotionQuery = null;
        this.onReducedMotionChange = null;
    },
    methods: {
        detectReducedMotion() {
            return typeof window !== 'undefined'
                && typeof window.matchMedia === 'function'
                && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        },
        bindReducedMotion() {
            if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
                return;
            }
            // 已绑定过就直接返回，避免 addEventListener 路径重复注册同一个 handler
            if (this.reducedMotionQuery) {
                return;
            }
            this.reducedMotionQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
            this.onReducedMotionChange = () => {
                this.reducedMotion = this.detectReducedMotion();
                this.$nextTick(this.updateMarquee);
            };
            if (this.reducedMotionQuery.addEventListener) {
                this.reducedMotionQuery.addEventListener('change', this.onReducedMotionChange);
            } else if (this.reducedMotionQuery.addListener) {
                this.reducedMotionQuery.addListener(this.onReducedMotionChange);
            }
        },
        bindObservers() {
            if (typeof window === 'undefined') {
                return;
            }
            // 卡片宽度会随列数/窗口变化（首页两列、收藏页单列），宽度变了要重新判断
            if (typeof ResizeObserver !== 'undefined') {
                this.resizeObserver = new ResizeObserver(() => this.updateMarquee());
                this.resizeObserver.observe(this.$el);
            } else {
                this.resizeFallbackHandler = () => this.updateMarquee();
                window.addEventListener('resize', this.resizeFallbackHandler);
            }
            // 书单列表页可能同时挂几十张卡片，不在视口里的先暂停，别让它们一起跑动画
            if (typeof IntersectionObserver !== 'undefined') {
                this.intersectionObserver = new IntersectionObserver((entries) => {
                    entries.forEach((entry) => {
                        this.inView = entry.isIntersecting;
                    });
                }, { rootMargin: '120px' });
                this.intersectionObserver.observe(this.$el);
            }
        },
        updateMarquee() {
            const viewport = this.$refs.coversViewport;
            if (!viewport) {
                return;
            }
            // 卡片被折叠（display:none）时量不到宽度，保留上一次判断，等 ResizeObserver 再算
            if (!viewport.clientWidth) {
                return;
            }
            const style = window.getComputedStyle(viewport);
            const available = viewport.clientWidth
                - parseFloat(style.paddingLeft)
                - parseFloat(style.paddingRight);
            const item = viewport.querySelector('.booklist-cover-item');
            if (!item) {
                this.marqueeActive = false;
                this.coversOverflow = false;
                return;
            }
            const itemWidth = item.getBoundingClientRect().width + COVER_GAP;
            const contentWidth = itemWidth * this.covers.length;
            // 记住一份内容的实测宽度，marqueeDuration 用它换算时长（itemWidth 已含间距）
            this.measuredCopyWidth = contentWidth;
            // #140-5 两端淡出遮罩：内容超出一行就启用（轮播与静止手动横滑模式都生效，
            // 遮罩是静态视觉处理，不受动效开关影响）；内容不满一行时不启用，
            // 避免把完整可见的封面边缘也「裁」淡。阈值取 > available（marquee 判定的
            // 超集），保证「轮播开着 ⇒ 遮罩一定开着」
            this.coversOverflow = contentWidth > available;
            // 站长关掉了动效，或用户要求减少动效，或没有封面：保持原生横向滚动，不动
            if (this.reducedMotion || !this.coverScrollEnabled || !this.covers.length) {
                this.marqueeActive = false;
                return;
            }
            // 必须"一份封面就铺满可视区"才滚：动画会把封面复制一份并把 track 平移一份宽，
            // 若一份比视口窄，平移到终点后视口右边界会越过第二份的末尾，露出空白条。
            // 铺不满（书单只有几本）时保持静止，靠手动横滑查看。恰好铺满（相等）时接缝
            // 不露空白，也应滚动，故用 >=；+2 是浮点取整的安全余量。
            this.marqueeActive = contentWidth >= available + 2;
        },
    },
};
</script>

<style scoped>
.booklist-card {
    position: relative;
    border-left-width: 4px;
    border-left-style: solid;
    margin-right: 2px;
}
.booklist-recommend-badge {
    position: absolute;
    top: 8px;
    left: 8px;
    z-index: 1;
}
.booklist-name {
    font-size: 20px;
    font-weight: 700;
    max-width: 100%;
}
.booklist-description {
    font-size: 13px;
    color: var(--v-secondary-base, #757575);
    margin-top: 2px;
}
.text-truncate-2 {
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
}
.booklist-stats {
    font-size: 13px;
}
.booklist-like {
    cursor: pointer;
}
.booklist-like--active {
    color: red;
}
.booklist-color-menu {
    max-width: 160px;
}
.booklist-covers {
    padding: 8px;
    overflow-x: auto;
    overflow-y: hidden;
}
.booklist-covers-track {
    display: flex;
    width: max-content;
}
/* 封面复制一份接在后面循环平移。-50% 正好是一份内容的宽度（间距用 margin-right 保证精确无缝） */
.booklist-covers--marquee {
    overflow-x: hidden;
}
/* #140-5 封面条两端淡出遮罩：封面滚动/轮播时从边缘渐隐渐现，而不是被硬切。
   mask 固定作用在滚动容器自身（不随内容滚），标准属性给 Firefox，
   -webkit- 前缀给 Safari / 旧 Chromium */
.booklist-covers--masked {
    -webkit-mask-image: linear-gradient(to right, transparent 0, #000 28px, #000 calc(100% - 28px), transparent 100%);
    mask-image: linear-gradient(to right, transparent 0, #000 28px, #000 calc(100% - 28px), transparent 100%);
}
.booklist-covers--marquee .booklist-covers-track {
    animation-name: booklist-covers-scroll;
    animation-duration: 30s;
    animation-timing-function: linear;
    animation-iteration-count: infinite;
    will-change: transform;
}
/* 鼠标停在卡片上、键盘聚焦、或卡片滚出视口时暂停 */
.booklist-card:hover .booklist-covers-track,
.booklist-card:focus-within .booklist-covers-track,
.booklist-covers--offscreen .booklist-covers-track {
    animation-play-state: paused;
}
@keyframes booklist-covers-scroll {
    from {
        transform: translate3d(0, 0, 0);
    }
    to {
        transform: translate3d(-50%, 0, 0);
    }
}
.booklist-cover-item {
    flex: 0 0 auto;
    width: 60px;
    margin-right: 4px;
    border-radius: 4px;
    position: relative;
    z-index: 1;
    transition: transform 200ms cubic-bezier(0.22, 0.61, 0.36, 1), box-shadow 200ms ease;
}
/* 悬停单张封面时只放大这一张。上限约 1.15 —— 封面高 82px，放大后上下各溢出约 6px，
   仍在容器 8px 的 padding 内，不会被 overflow:hidden 切边 */
@media (hover: hover) and (pointer: fine) {
    .booklist-cover-item:hover {
        transform: scale(1.15);
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
        z-index: 4;
    }
}
@media (prefers-reduced-motion: reduce) {
    .booklist-cover-item {
        transition: none;
    }
    .booklist-cover-item:hover {
        transform: none;
    }
    /* 纯 CSS 兜底：脚本失效或 mounted 前也尊重用户的减少动效偏好，
       直接停掉 track 的轮播动画（JS 侧 marqueeActive=false 时本就退回 overflow-x:auto，二者不冲突） */
    .booklist-covers--marquee .booklist-covers-track {
        animation: none;
    }
}
.booklist-covers-empty {
    padding: 12px;
    width: 100%;
    text-align: center;
}
</style>
