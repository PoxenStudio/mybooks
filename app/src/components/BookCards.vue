<template>
    <v-row>
        <v-col cols=12 xs=12 sm=6 md=4 lg=3 xl=2 v-for="(book,idx) in render_books" :key="idx+'-books-'+book.id" class="book-list-card d-flex">
            <v-card :to="selectable ? undefined : book.href" class="flex-grow-1"
                    @click="selectable ? $emit('toggle-select', book.id) : undefined">
                <v-row>
                    <v-col cols=4 xs=4 sm=4 md=4 lg=4 class='col-book-img'>
                        <div class="book-img-container">
                            <v-img :src="book.thumb || book.img" :alt="book.title" class="book-img-hover"></v-img>
                            <!-- 角标只保留一个，按「有声书 > 实体书 > 分享」取最高优先级。
                                 原来是三个角标分别压在封面左右两个角上，其中「多选」单选框与
                                 「有声书」角标同坐标且 z-index 更高，音频页开多选时有声书标记直接被吃掉。 -->
                            <div v-if="coverBadge(book)" class="cover-badge" :style="{ backgroundColor: coverBadge(book).color }">
                                <v-icon small color="white">{{ coverBadge(book).icon }}</v-icon>
                            </div>
                            <!-- 多选单选框跟封面同坐标系（右上角）。原来它绝对定位在整张卡片上，
                                 纵坐标恰好压在标题第一行尾部，长书名末几个字被盖住。 -->
                            <div v-if="selectable" class="book-select-badge"
                                 role="checkbox"
                                 :aria-checked="isSelected(book.id) ? 'true' : 'false'"
                                 :aria-label="book.title"
                                 @click.stop.prevent="$emit('toggle-select', book.id)">
                                <v-icon :color="isSelected(book.id) ? 'primary' : 'grey lighten-1'">
                                    {{ isSelected(book.id) ? 'mdi-radiobox-marked' : 'mdi-radiobox-blank' }}
                                </v-icon>
                            </div>
                        </div>
                    </v-col>
                    <v-col cols=8 xs=8 sm=8 md=8 lg=8 class='col-book-info'>
                        <v-card-text class="pb-0 d-flex flex-column" align-left>
                            <div class="book-title">{{book.title}}</div>
                            <!-- 一行元信息取代最多 5 个饱和 chip（分类/位置/3 个格式）：
                                 书名之外真正用来区分书的信息只有这一行。 -->
                            <div v-if="metaLine(book)" class="book-meta">{{ metaLine(book) }}</div>
                            <slot name="introduce" :book="book"></slot>
                            <div class="book-comments flex-grow-1">
                                <p v-if="book.comments && shouldShowCommentTooltip(book.comments)"
                                    v-html="book.comments"
                                    class="comment-tooltip-activator"
                                    tabindex="0"
                                    @mouseenter="showTooltip($event, book.comments)"
                                    @mouseleave="hideTooltip"
                                    @focus="showTooltip($event, book.comments)"
                                    @blur="hideTooltip"
                                ></p>
                                <p v-else-if="book.comments" v-html="book.comments"></p>
                                <p v-else>{{ $t('bookCards.browseDetails') }}</p>
                            </div>
                        </v-card-text>
                    </v-col>
                </v-row>
                <slot name="actions" :book="book"></slot>
            </v-card>
        </v-col>
    </v-row>
</template>

<script>
export default {
    props: {
        books: Array,
        isAudioPage: {
            type: Boolean,
            default: false
        },
        selectable: {
            type: Boolean,
            default: false
        },
        selectedIds: {
            type: Array,
            default: () => []
        }
    },
    components: {
    },
    computed: {
        render_books: function() {
            return (this.books || []).map( b => {
                // 确保b是一个对象
                if (!b) return {};

                if ( b['href'] == undefined ) {
                    if (this.isAudioPage) {
                        b['href'] = "/audio/" + (b.id || '');
                    } else {
                        b['href'] = "/book/" + (b.id || '');
                    }
                }
                return b;
            }).filter(Boolean); // 过滤掉空对象
        },
    },
    methods: {
        /**
         * 封面上只留一个角标：有声书 > 实体书 > 分享。
         * 三个角标同时出现时（音频页 + 实体书 + 有分享链接）叠在同一个角上，看起来像渲染错误；
         * 而这三个标记的信息量并不对等 —— 有没有音频最影响「能不能听」，分享链接只有管理员关心。
         */
        coverBadge(book) {
            if (!book) return null;
            if (this.isAudioPage || book.has_audio) return { icon: 'mdi-headphones', color: '#9C27B0' };
            if (book.book_type === 1) return { icon: 'mdi-bookshelf', color: '#2196F3' };
            if (book.shared) return { icon: 'mdi-cloud-outline', color: '#009688' };
            return null;
        },
        /** 一行元信息：作者 · 分类 · 位置 · 格式。缺哪个就跳过哪个，不留空分隔符。 */
        metaLine(book) {
            if (!book) return '';
            const parts = [];
            if (book.author) parts.push(book.author);
            if (book.category) parts.push(book.category);
            if (book.location) parts.push(book.location);
            const formats = (book.files || [])
                .slice(0, 3)
                .map((file) => (file && file.format ? String(file.format).toUpperCase() : ''))
                .filter(Boolean);
            if (formats.length) parts.push(formats.join(' / '));
            return parts.join(' · ');
        },
        isSelected(bookId) {
            return (this.selectedIds || []).includes(bookId);
        },
        shouldShowCommentTooltip(html) {
            return this.isLongComment(html) && !this.isSmallScreen();
        },
        isSmallScreen() {
            return Boolean(this.$vuetify?.breakpoint?.smAndDown);
        },
        buildCommentPreview(html) {
            if (!html) return '';
            let text = String(html)
                .replace(/<br\s*\/?\s*>/gi, ' ')
                .replace(/<\/p>/gi, ' ')
                .replace(/<[^>]+>/g, '')
                .replace(/&nbsp;/gi, ' ')
                .replace(/&amp;/gi, '&')
                .replace(/&lt;/gi, '<')
                .replace(/&gt;/gi, '>')
                .replace(/\s+/g, ' ')
                .trim();

            if (text.length > 200) {
                text = text.slice(0, 200) + '...';
            }
            return text;
        },
        isLongComment(html) {
            if (!html) return false;
            let text = String(html).replace(/<[^>]+>/g, '').replace(/&nbsp;/gi, ' ').trim();
            return text.length > 80;
        },
        getOrCreateTooltipEl() {
            let el = document.getElementById('bc-global-tooltip');
            if (!el) {
                el = document.createElement('div');
                el.id = 'bc-global-tooltip';
                el.style.cssText = [
                    'position:fixed',
                    'z-index:9999',
                    'background:#003153',
                    'color:#fff',
                    'border-radius:4px',
                    'padding:6px 10px',
                    'font-size:12px',
                    'line-height:1.5',
                    'max-width:360px',
                    'white-space:normal',
                    'word-break:break-word',
                    'pointer-events:none',
                    'box-shadow:0 2px 12px rgba(0,0,0,0.3)',
                    'display:none',
                ].join(';');
                document.body.appendChild(el);
            }
            return el;
        },
        showTooltip(event, html) {
            const text = this.buildCommentPreview(html);
            const el = this.getOrCreateTooltipEl();
            el.textContent = text;
            el.style.transform = '';
            el.style.display = 'block';
            const rect = event.currentTarget.getBoundingClientRect();
            const gap = 8;
            const vpW = window.innerWidth;
            const ttW = el.offsetWidth;
            let left = rect.left + rect.width / 2 - ttW / 2;
            left = Math.max(8, Math.min(left, vpW - ttW - 8));
            el.style.left = left + 'px';
            const ttH = el.offsetHeight;
            if (rect.top - ttH - gap < 8) {
                el.style.top = (rect.bottom + gap) + 'px';
            } else {
                el.style.top = (rect.top - ttH - gap) + 'px';
            }
        },
        hideTooltip() {
            const el = document.getElementById('bc-global-tooltip');
            if (el) el.style.display = 'none';
        },
    },
    beforeDestroy() {
        this.hideTooltip();
    },
    // vue3 compatible alias
    beforeUnmount() {
        this.hideTooltip();
    },
    // hide on scroll
    mounted() {
        this._scrollHide = () => this.hideTooltip();
        window.addEventListener('scroll', this._scrollHide, true);
    },
    destroyed() {
        window.removeEventListener('scroll', this._scrollHide, true);
    },
    unmounted() {
        window.removeEventListener('scroll', this._scrollHide, true);
    },
    data: () => {
        return {
        }
    },
}
</script>

<style scoped>
.book-title {
    display: block;
    overflow: hidden;
    display: -webkit-box;
    /* 原来只有 1 行：1920px 六列布局下几乎每个书名都被截断。两行能容纳绝大多数书名 */
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    text-overflow: clip;
    text-align: left;
    font-weight: bold;
    line-height: 1.35;
}

/* 元信息行：替代原来最多 5 个彩色 chip，单行省略，不参与换行计算 */
.book-meta {
    margin-top: 2px;
    font-size: 11px;
    line-height: 1.5;
    text-align: left;
    opacity: 0.62;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.book-list-card .v-card {
    position: relative;
    min-height: 6em;
    display: flex;
    flex-direction: column;
    width: 100%;
    height: 100%;
    overflow: hidden;
    border-radius: var(--app-radius, 4px);
    transition: transform 200ms cubic-bezier(0.22, 0.61, 0.36, 1), box-shadow 200ms ease;
}
.book-select-badge {
    position: absolute;
    top: 4px;
    right: 4px;
    z-index: 4;
    background: rgba(255, 255, 255, 0.9);
    border-radius: 50%;
    width: 24px;
    height: 24px;
    display: flex;
    align-items: center;
    justify-content: center;
    box-shadow: 0 2px 6px rgba(0, 0, 0, 0.25);
    cursor: pointer;
}
/* 与首页其它区块书卡（index.vue 的 .home-section-slot .book-card）保持同一套手感：
   上浮 3px + 阴影，原来只有 1px 且没有过渡，和书单卡切换时会明显不一致 */
@media (hover: hover) and (pointer: fine) {
    .book-list-card .v-card:hover {
        transform: translateY(-3px);
        box-shadow: 0 8px 20px rgba(0, 0, 0, 0.14);
    }

    .theme--dark .book-list-card .v-card:hover {
        box-shadow: 0 8px 20px rgba(0, 0, 0, 0.55);
    }
}

@media (prefers-reduced-motion: reduce) {
    .book-list-card .v-card {
        transition: none;
    }
}
.book-list-card .v-card > .row {
    flex: 1;
    margin: 0;
}
.book-list-card .v-card-text {
    height: 100%;
}
.book-comments {
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    text-overflow: clip;
    margin-top: 3px;
    margin-bottom: 3px;
    text-align: left;
    overflow: hidden;
}
.book-comments p {
    font-size: small;
    margin-bottom: 0px;
}

.comment-tooltip-activator {
    cursor: pointer;
}

.book-list-card .row {
    margin-bottom: 0px;
}
.page-title {
    font-weight: bold;
    text-align: left;
}
.col-book-img {
    padding: 6px 0 0 3px;
    display: flex;
    flex-direction: column;
}
.book-img-container {
    position: relative;
    display: flex;
    width: 100%;
    aspect-ratio: 3/4;
}
.book-img-container .v-image {
    width: 100%;
    height: 100%;
    border-radius: var(--app-radius, 4px);
    overflow: hidden;
}
/* 封面角标：全卡只有这一个，颜色由 coverBadge() 决定（有声书紫 / 实体书蓝 / 分享青） */
.cover-badge {
    position: absolute;
    top: 4px;
    left: 4px;
    border-radius: 50%;
    width: 22px;
    height: 22px;
    display: flex;
    align-items: center;
    justify-content: center;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.28);
    z-index: 3;
}
.col-book-info {
    padding: 0;
    margin-left: -6px;
    margin-top: -6px;
}
.book-img-hover {
    transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}
.book-img-hover:hover {
    overflow-clip-margin: content-box;
    overflow: clip;
    transform: scale(1.06);
    z-index: 2;
    box-shadow: 0 8px 24px rgba(0,0,0,0.18);
}
</style>
