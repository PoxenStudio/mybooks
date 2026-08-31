<template>
    <div>
    <!-- 书库统计标题栏 -->
    <v-row v-if="libraryStats" class="library-stats-bar">
        <v-col cols="12">
            <div class="stats-container">
                <div class="stats-title"></div>
                <div class="stats-content">
                    <div class="stat-group">
                        <span class="stat-label">{{ $t('index.totalBooks') }}:</span>
                        <span class="stat-value">{{ libraryStats.total_books }}</span>
                    </div>
                    <div class="stat-separator">|</div>
                    <div class="stat-group">
                        <span class="stat-label">{{ $t('index.ebookCount') }}:</span>
                        <span class="stat-value">{{ libraryStats.ebook_count }}</span>
                    </div>
                    <template v-if="allowPhysicalBooks">
                        <div class="stat-separator">|</div>
                        <div class="stat-group">
                            <span class="stat-label">{{ $t('index.physicalCount') }}:</span>
                            <span class="stat-value">{{ libraryStats.physical_count }}</span>
                        </div>
                    </template>
                    <div class="stat-separator">|</div>
                    <div class="stat-group">
                        <span class="stat-label">{{ $t('index.monthNewBooks') }}:</span>
                        <span class="stat-value month-new">
                            {{ $t('index.ebookCount') }} {{ libraryStats.month_ebook_count }}
                            <template v-if="allowPhysicalBooks">+ {{ $t('index.physicalCount') }} {{ libraryStats.month_physical_count }}</template>
                        </span>
                    </div>
                </div>
            </div>
        </v-col>
    </v-row>

    <div class="reading-stats-banner-wrapper" v-show="readingStatsHasData">
        <reading-stats-banner :show-title="false" @has-stats="onReadingStatsHasData"></reading-stats-banner>
    </div>

    <div class="home-sections-container">
        <div
            class="home-section-slot"
            :style="{ order: sectionOrder.indexOf('index.myReading') }"
            @dragover.prevent="onSectionDragOver('index.myReading')"
            @dragleave="onSectionDragLeave('index.myReading')"
            @drop.prevent="onSectionDrop('index.myReading')"
        >
            <home-section-card
                v-if="reading_books.length > 0"
                icon="mdi-book-open-page-variant-outline"
                :title="$t('index.myReading')"
                storage-key="index.myReading"
                :drag-over="dragOverKey === 'index.myReading'"
                @drag-start="onSectionDragStart('index.myReading', $event)"
                @drag-end="onSectionDragEnd"
            >
                <v-row>
                    <v-col cols="4" xs="4" sm="3" md="2" lg="1" v-for="(book,idx) in get_reading_books" :key="'reading'+idx+book.id" class="book-card">
                        <v-card :to="book.href" class="ma-1">
                            <div class="book-img-container reading-book-cover" :title="book.title">
                                <v-img
                                    :src="book.thumb"
                                    class="cover-fill-img"
                                ></v-img>
                                <a
                                    class="reading-hover-overlay"
                                    :href="book.readHref"
                                    target="_blank"
                                    :title="$t('index.continueReading')"
                                    @click.stop
                                >
                                    <v-icon class="reading-hover-icon">mdi-book-open-page-variant-outline</v-icon>
                                </a>
                            </div>
                        </v-card>
                    </v-col>
                </v-row>
            </home-section-card>
        </div>

        <div
            class="home-section-slot"
            :style="{ order: sectionOrder.indexOf('index.socialRecommendation') }"
            @dragover.prevent="onSectionDragOver('index.socialRecommendation')"
            @dragleave="onSectionDragLeave('index.socialRecommendation')"
            @drop.prevent="onSectionDrop('index.socialRecommendation')"
        >
            <home-section-card
                v-if="social_recommend_books.length > 0"
                icon="mdi-star-check"
                :title="$t('index.socialRecommendation')"
                storage-key="index.socialRecommendation"
                :drag-over="dragOverKey === 'index.socialRecommendation'"
                @drag-start="onSectionDragStart('index.socialRecommendation', $event)"
                @drag-end="onSectionDragEnd"
            >
                <v-row>
                    <v-col cols="4" xs="4" sm="3" md="2" lg="1" v-for="(book,idx) in get_social_recommend_books" :key="'social-rec'+idx+book.id" class="book-card">
                        <v-card :to="book.href" class="ma-1">
                            <div class="book-img-container" :title="book.title">
                                <v-img
                                    :src="book.thumb"
                                    class="cover-fill-img book-img-hover"
                                ></v-img>
                                <div v-if="book.book_type === 1" class="physical-book-badge">
                                    <v-icon small color="white">mdi-bookshelf</v-icon>
                                </div>
                                <div
                                    v-if="book.recommender && book.recommender.avatar"
                                    class="recommender-badge"
                                    :title="book.recommender.nickname"
                                >
                                    <v-avatar size="22">
                                        <v-img :src="book.recommender.avatar"></v-img>
                                    </v-avatar>
                                </div>
                            </div>
                        </v-card>
                    </v-col>
                </v-row>
            </home-section-card>
        </div>

        <div
            class="home-section-slot"
            :style="{ order: sectionOrder.indexOf('index.booklistRecommendation') }"
            @dragover.prevent="onSectionDragOver('index.booklistRecommendation')"
            @dragleave="onSectionDragLeave('index.booklistRecommendation')"
            @drop.prevent="onSectionDrop('index.booklistRecommendation')"
        >
            <home-section-card
                v-if="homepage_booklists.length > 0"
                icon="mdi-format-list-bulleted-square"
                :title="$t('index.booklistRecommendation')"
                storage-key="index.booklistRecommendation"
                :drag-over="dragOverKey === 'index.booklistRecommendation'"
                @drag-start="onSectionDragStart('index.booklistRecommendation', $event)"
                @drag-end="onSectionDragEnd"
            >
                <v-row>
                    <v-col cols="12" md="6" v-for="b in homepage_booklists" :key="'home-booklist-' + b.id">
                        <BookListCard :booklist="b" :show-recommend-badge="true" @toggle-like="toggleBooklistLike" />
                    </v-col>
                </v-row>
            </home-section-card>
        </div>

        <div
            class="home-section-slot"
            :style="{ order: sectionOrder.indexOf('index.randomRecommendation') }"
            @dragover.prevent="onSectionDragOver('index.randomRecommendation')"
            @dragleave="onSectionDragLeave('index.randomRecommendation')"
            @drop.prevent="onSectionDrop('index.randomRecommendation')"
        >
            <home-section-card
                v-if="random_books.length > 0"
                icon="mdi-apple-keyboard-command"
                :title="$t('index.randomRecommendation')"
                storage-key="index.randomRecommendation"
                :drag-over="dragOverKey === 'index.randomRecommendation'"
                @drag-start="onSectionDragStart('index.randomRecommendation', $event)"
                @drag-end="onSectionDragEnd"
            >
                <template #header-extra>
                    <v-icon color="primary" class="ml-1 refresh-icon" @click="refreshBooks('all')">mdi-refresh</v-icon>
                </template>
                <v-row>
                    <v-col cols="4" xs="4" sm="3" md="2" lg="1" v-for="(book,idx) in get_random_books" :key="'rec'+idx+book.id" class="book-card">
                        <v-card :to="book.href" class="ma-1">
                            <div class="book-img-container" :title="book.title">
                                <v-img
                                    :src="book.thumb"
                                    class="cover-fill-img book-img-hover"
                                ></v-img>
                                <!-- 实体书角标 -->
                                <div v-if="book.book_type === 1" class="physical-book-badge">
                                    <v-icon small color="white">mdi-bookshelf</v-icon>
                                </div>
                            </div>
                        </v-card>
                    </v-col>
                </v-row>
            </home-section-card>
        </div>

        <div
            class="home-section-slot"
            :style="{ order: sectionOrder.indexOf('index.newRecommendation') }"
            @dragover.prevent="onSectionDragOver('index.newRecommendation')"
            @dragleave="onSectionDragLeave('index.newRecommendation')"
            @drop.prevent="onSectionDrop('index.newRecommendation')"
        >
            <home-section-card
                icon="mdi-hexagram-outline"
                :title="$t('index.newRecommendation')"
                storage-key="index.newRecommendation"
                :drag-over="dragOverKey === 'index.newRecommendation'"
                @drag-start="onSectionDragStart('index.newRecommendation', $event)"
                @drag-end="onSectionDragEnd"
            >
                <v-row>
                    <v-col cols="12">
                        <book-cards :books="get_recent_books"></book-cards>
                    </v-col>
                </v-row>
            </home-section-card>
        </div>
    </div>

    <!-- Release Notes Dialog -->
    <v-dialog v-model="releaseNotesDialog" max-width="480" persistent transition="dialog-bottom-transition">
        <v-card class="release-notes-card">
            <v-card-title class="headline text-center">
                {{ $t('index.versionChanges') }}
                <v-spacer></v-spacer>
                <span class="text-body-2 grey--text">{{ countdown }}s</span>
            </v-card-title>
            <v-card-text class="release-notes-card">
                <!-- Render HTML content for release notes -->
                <div v-html="releaseNotesContent" style="max-height: 440px; overflow-y: auto;"></div>
            </v-card-text>
            <v-card-actions class="justify-center">
                <v-btn rounded large color="primary" dark elevation="2" @click="closeReleaseNotesDialog">
                    {{ $t('common.close') }}
                </v-btn>
            </v-card-actions>
        </v-card>
    </v-dialog>
    </div>
</template>

<script>
import BookCards from "~/components/BookCards.vue";
import ReadingStatsBanner from "~/components/ReadingStatsBanner.vue";
import BookListCard from "~/components/BookListCard.vue";
import HomeSectionCard from "~/components/HomeSectionCard.vue";
export default {
    name: 'IndexPage',
    components: {
        BookCards,
        ReadingStatsBanner,
        BookListCard,
        HomeSectionCard,
    },
    computed: {
        get_random_books: function() {
            return this.random_books.map( b => {
                b['href'] = "/book/" + b.id;
                return b;
            });
        },
        get_reading_books: function() {
            return this.reading_books.slice(0, 12).map( b => {
                b['href'] = "/book/" + b.id;
                b['readHref'] = "/read/" + b.id;
                return b;
            });
        },
        get_recent_books: function() {
            return this.new_books.map( b => {
                b['href'] = "/book/" + b.id;
                return b;
            });
        },
        get_social_recommend_books: function() {
            return this.social_recommend_books.map( b => {
                b['href'] = "/book/" + b.id;
                return b;
            });
        },
        indexPage() {
            return this.$store.state.sys && this.$store.state.sys.indexPage;
        },
        isLoggedIn() {
            return !!(this.$store.state.user && this.$store.state.user.is_login);
        },
        allowPhysicalBooks() {
            return !!(this.$store.state.sys && this.$store.state.sys.allow && this.$store.state.sys.allow.physical_books);
        },
    },
    watch: {
        indexPage: {
            handler: function(val) {
                this.checkRedirect(val);
            },
            immediate: true
        },
        isLoggedIn(loggedIn) {
            if (loggedIn) {
                this.loadReadingBooks();
            } else {
                this.reading_books = [];
            }
        },
    },
    methods: {
        async loadLibraryStats() {
            try {
                const rsp = await this.$backend('/library/stats');
                if (rsp.err === 'ok') {
                    this.libraryStats = rsp.stats;
                }
            } catch (error) {
                console.warn('Failed to load library stats:', error);
            }
        },
        async checkReleaseNotes() {
            try {
                const rsp = await this.$backend('/admin/release/notes?rand='+Math.random());
                if (rsp.err === 'ok' && rsp.msg) {
                    this.releaseNotesContent = rsp.msg;
                    this.releaseNotesDialog = true;
                    this.startCountdown();
                }
            } catch (error) {
                console.error('Failed to check release notes:', error);
            }
        },
        startCountdown() {
            this.countdown = 30;
            this.countdownTimer = setInterval(() => {
                this.countdown--;
                if (this.countdown <= 0) {
                    this.closeReleaseNotesDialog();
                }
            }, 1000);
        },
        closeReleaseNotesDialog() {
            this.releaseNotesDialog = false;
            if (this.countdownTimer) {
                clearInterval(this.countdownTimer);
                this.countdownTimer = null;
            }
        },
        checkRedirect(type) {
            if (type === 'all') {
                this.$router.replace('/all');
            } else if (type === 'categories') {
                this.$router.replace('/categories');
            }
        },
        refreshBooks() {
            this.$backend('/index').then( rsp => {
                if (rsp.err === 'ok') {
                    this.random_books = rsp.random_books || [];
                    this.new_books = rsp.new_books || [];
                    this.social_recommend_books = rsp.social_recommend_books || [];
                }
            }).catch( error => {
                console.error('Failed to refresh books:', error);
            });
        },
        async loadReadingBooks() {
            if (!this.isLoggedIn) {
                this.reading_books = [];
                return;
            }
            try {
                // home=1 标记这是首页发起的请求，后台在 ENABLE_HOMEPAGE_READING_BOOKS=False
                // 时会直接返回空列表（不影响 /reading 在读书籍列表页本身）
                const rsp = await this.$backend('/reading?home=1&size=12');
                if (rsp.err === 'ok') {
                    this.reading_books = rsp.books || [];
                }
            } catch (error) {
                console.warn('Failed to load reading books:', error);
            }
        },
        onReadingStatsHasData(hasData) {
            this.readingStatsHasData = hasData;
        },
        async loadBooklists() {
            try {
                const rsp = await this.$backend('/booklists/homepage');
                if (rsp.err === 'ok') {
                    this.homepage_booklists = rsp.booklists || [];
                }
            } catch (error) {
                console.warn('Failed to load homepage booklists:', error);
            }
        },
        async toggleBooklistLike(b) {
            try {
                const rsp = await this.$backend(`/booklist/${b.id}/like`, { method: 'POST' });
                if (rsp.err === 'ok') {
                    b.liked_by_me = rsp.liked;
                    b.like_count += rsp.liked ? 1 : -1;
                } else if (rsp.err === 'user.need_login') {
                    this.$router.push('/login');
                }
            } catch (e) {
                // ignore
            }
        },
        loadSectionOrder() {
            try {
                const raw = window.localStorage.getItem('home-section-order');
                const saved = raw ? JSON.parse(raw) : null;
                if (Array.isArray(saved)) {
                    const known = saved.filter(k => this.sectionKeys.includes(k));
                    const missing = this.sectionKeys.filter(k => !known.includes(k));
                    return [...known, ...missing];
                }
            } catch (e) {
                // ignore
            }
            return [...this.sectionKeys];
        },
        saveSectionOrder() {
            try {
                window.localStorage.setItem('home-section-order', JSON.stringify(this.sectionOrder));
            } catch (e) {
                // ignore (privacy mode / storage disabled)
            }
        },
        onSectionDragStart(key, event) {
            this.dragKey = key;
            if (event && event.dataTransfer) {
                event.dataTransfer.effectAllowed = 'move';
                event.dataTransfer.setData('text/plain', key);
            }
        },
        onSectionDragOver(key) {
            if (this.dragKey && this.dragKey !== key) {
                this.dragOverKey = key;
            }
        },
        onSectionDragLeave(key) {
            if (this.dragOverKey === key) {
                this.dragOverKey = null;
            }
        },
        onSectionDrop(key) {
            const from = this.sectionOrder.indexOf(this.dragKey);
            const to = this.sectionOrder.indexOf(key);
            if (from === -1 || to === -1 || from === to) {
                this.onSectionDragEnd();
                return;
            }
            const order = this.sectionOrder.slice();
            order.splice(from, 1);
            order.splice(to, 0, this.dragKey);
            this.sectionOrder = order;
            this.saveSectionOrder();
            this.onSectionDragEnd();
        },
        onSectionDragEnd() {
            this.dragKey = null;
            this.dragOverKey = null;
        },
    },
    mounted() {
        this.loadLibraryStats();
        this.checkReleaseNotes();
        this.loadReadingBooks();
        this.loadBooklists();
        // 强制重新渲染图片，修复从其他页面返回时的布局问题
        this.$nextTick(() => {
            window.dispatchEvent(new Event('resize'));
        });
    },
    activated() {
        // 当使用 keep-alive 缓存时，激活页面时强制重新计算布局
        this.$nextTick(() => {
            window.dispatchEvent(new Event('resize'));
        });
    },
    beforeDestroy() {
        if (this.countdownTimer) {
            clearInterval(this.countdownTimer);
        }
    },
    created() {
        this.$store.commit('navbar', true);
        this.sectionOrder = this.loadSectionOrder();
    },
    async asyncData({ app, res }) {
        if ( res !== undefined ) {
            res.setHeader('Cache-Control', 'no-cache');
        }
        return app.$backend("/index");
    },
    data: () => ({
        random_books: [],
        new_books: [],
        social_recommend_books: [],
        homepage_booklists: [],
        reading_books: [],
        readingStatsHasData: false,
        libraryStats: null,
        releaseNotesDialog: false,
        releaseNotesContent: '',
        countdown: 10,
        countdownTimer: null,
        // 首页各模块的默认顺序，拖动排序后持久化到 localStorage
        sectionKeys: [
            'index.myReading',
            'index.socialRecommendation',
            'index.booklistRecommendation',
            'index.randomRecommendation',
            'index.newRecommendation',
        ],
        sectionOrder: [],
        dragKey: null,
        dragOverKey: null,
    }),
    head: () => ({
        titleTemplate: "%s",
    })
}
</script>

<style>
@media (max-width: 640px) {
    .reading-stats-banner-wrapper {
        display: none;
    }
}

/* 书库统计标题栏样式 */
.library-stats-bar {
    background: #55655f;
    color: white;
    padding: 2px;
    margin: 0;
    border-radius: 5px;
    box-shadow: 0 8px 12px rgba(0,0,0,0.15);
}

.stats-container {
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 16px;
}

.stats-title {
    font-size: 18px;
    font-weight: bold;
    color: #ffffff;
    min-width: 100px;
}

.stats-content {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 12px;
    flex: 1;
    justify-content: flex-end;
}

.stat-group {
    display: flex;
    align-items: center;
    gap: 6px;
}

.stat-label {
    font-size: 14px;
    color: #e3f2fd;
    white-space: nowrap;
}

.stat-value {
    background: rgba(0,0,0,0.3);
    color: #ffffff;
    padding: 4px 12px;
    border-radius: 16px;
    font-weight: bold;
    font-size: 14px;
    min-width: 40px;
    text-align: center;
    box-shadow: inset 0 2px 4px rgba(0,0,0,0.2);
}

.stat-value.month-new {
    background: rgba(76, 175, 80, 0.3);
    border: 1px solid rgba(76, 175, 80, 0.5);
}

.stat-separator {
    color: rgba(255,255,255,0.6);
    font-size: 16px;
    margin: 0 4px;
}

/* 响应式设计 */
@media (max-width: 768px) {
    .stats-container {
        flex-direction: column;
        align-items: flex-start;
    }

    .stats-content {
        justify-content: flex-start;
        width: 100%;
    }

    .stat-separator {
        display: none;
    }
}

.new-legend {
    margin-top: 30px;
    margin-bottom: 20px;
}

.home-sections-container {
    display: flex;
    flex-direction: column;
}

.home-section-slot {
    display: flex;
    flex-direction: column;
}

.refresh-icon {
    cursor: pointer;
    transition: transform 0.28s ease, color 0.28s ease;
}

.refresh-icon:hover {
    transform: rotate(180deg) scale(1.12);
    color: #1976d2 !important;
}

.book-img-container {
    position: relative;
    display: block;
    width: 100%;
    aspect-ratio: 11 / 15;
    overflow: hidden;
}

/* 确保图片容器保持正确的宽高比 */
.book-img-container .v-image {
    width: 100% !important;
    height: auto !important;
}

/* 确保响应式内容填充整个容器 */
.book-img-container .v-responsive__content {
    width: 100% !important;
    height: 100% !important;
}

.physical-book-badge {
    position: absolute;
    top: 6px;
    left: 6px;
    background-color: #2196F3;
    border-radius: 50%;
    width: 24px;
    height: 24px;
    display: flex;
    align-items: center;
    justify-content: center;
    box-shadow: 0 2px 8px rgba(33, 150, 243, 0.4);
    z-index: 3;
}

.recommender-badge {
    position: absolute;
    bottom: 6px;
    right: 6px;
    border-radius: 50%;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.4);
    z-index: 3;
    border: 2px solid white;
}

.book-img-hover {
    transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    will-change: transform;
}

.reading-book-cover {
    container-type: size;
    cursor: pointer;
}

.cover-fill-img.v-image {
    position: absolute;
    top: 50%;
    left: 0;
    width: 100%;
    transform: translateY(-50%);
}

.cover-fill-img .v-image__image {
    background-size: 100% 100% !important;
}

.reading-hover-overlay {
    position: absolute;
    top: 50%;
    left: 50%;
    width: min(46cqw, 46cqh);
    height: min(46cqw, 46cqh);
    transform: translate(-50%, -50%) scale(0.85);
    border-radius: 50%;
    background: rgba(0, 87, 179, 0.75);
    box-sizing: border-box;
    padding: 1px;
    display: flex;
    align-items: center;
    justify-content: center;
    opacity: 0;
    cursor: pointer;
    pointer-events: none;
    z-index: 2;
}

.reading-book-cover:hover .reading-hover-overlay {
    opacity: 1;
    transform: translate(-50%, -50%) scale(1);
    pointer-events: auto;
}

.reading-hover-overlay:hover {
    background: rgba(0, 87, 179, 0.95);
}

.reading-hover-icon.v-icon {
    color: #ffffff !important;
    font-size: min(40cqw, 40cqh) !important;
}

/* hover 时图标做 2s 一轮的抖动动画，提示"点击进入阅读" */
@keyframes reading-icon-shake {
    0%, 100% { transform: rotate(0deg); }
    10% { transform: rotate(-12deg); }
    20% { transform: rotate(10deg); }
    30% { transform: rotate(-9deg); }
    40% { transform: rotate(8deg); }
    50% { transform: rotate(-6deg); }
    60% { transform: rotate(5deg); }
    70% { transform: rotate(-3deg); }
    80% { transform: rotate(2deg); }
    90% { transform: rotate(-1deg); }
}

.reading-book-cover:hover .reading-hover-icon.v-icon {
    animation: reading-icon-shake 2s ease-in-out infinite;
    transform-origin: center;
}

.book-img-hover:hover {
    transform: translateY(-50%) scale(1.1);
    z-index: 2;
    box-shadow: 0 8px 24px rgba(0,0,0,0.18);
}

/* 确保书籍卡片在路由切换时正确渲染 */
.book-card {
    min-height: 0;
}

.book-title {
    text-align: center;
    display: block;
    overflow: hidden;
    display: -webkit-box;
    -webkit-line-clamp: 1;
    line-clamp: 1;
    -webkit-box-orient: vertical;
    text-overflow: clip;
    font-size: small;
}

.book-card .v-card {
    overflow: hidden;
}
/* Release Notes Dialog card font size */
.release-notes-card {
    font-size: 16px;
}
/* Ensure close button text is also 16px */
.release-notes-card .v-btn {
    font-size: 16px !important;
}
</style>

