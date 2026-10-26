<template>
    <div>
    <div class="home-sections-container" :class="{ 'home-motion-reduced': !homeMotionEnabled }">
        <div v-if="isSectionEnabled('libraryStats')" class="home-section-slot" :style="{ order: sectionOrder.indexOf('libraryStats') }">
            <v-row class="library-stats-bar">
                <v-col cols="12">
                    <div class="stats-container">
                        <v-btn icon x-small dark class="stats-toggle" :title="showDetail ? $t('index.detailHideDetail') : $t('index.detailShowDetail')" @click="showDetail = !showDetail">
                            <v-icon>{{ showDetail ? 'mdi-chevron-up' : 'mdi-chevron-down' }}</v-icon>
                        </v-btn>
                        <div class="stats-content">
                            <div class="stat-group">
                                <span class="stat-label">{{ $t('index.totalBooks') }}:</span>
                                <span class="stat-value">{{ stats.total_books }}</span>
                            </div>
                            <div class="stat-separator">|</div>
                            <div class="stat-group">
                                <span class="stat-label">{{ $t('index.ebookCount') }}:</span>
                                <span class="stat-value">{{ stats.ebook_count }}</span>
                            </div>
                            <template v-if="allowPhysicalBooks">
                                <div class="stat-separator">|</div>
                                <div class="stat-group">
                                    <span class="stat-label">{{ $t('index.physicalCount') }}:</span>
                                    <span class="stat-value">{{ stats.physical_count }}</span>
                                </div>
                            </template>
                            <div class="stat-separator">|</div>
                            <div class="stat-group">
                                <span class="stat-label">{{ $t('index.monthNewBooks') }}:</span>
                                <span class="stat-value month-new">
                                    {{ $t('index.ebookCount') }} {{ stats.month_ebook_count }}
                                    <template v-if="allowPhysicalBooks">+ {{ $t('index.physicalCount') }} {{ stats.month_physical_count }}</template>
                                </span>
                            </div>
                        </div>
                    </div>
                </v-col>
            </v-row>

            <library-overview v-if="libraryStats && showDetail" :allow-physical-books="allowPhysicalBooks"></library-overview>
        </div>

        <div v-if="isSectionEnabled('readingStats')" class="home-section-slot" :style="{ order: sectionOrder.indexOf('readingStats') }">
            <div v-if="!lazyHome" class="reading-stats-banner-wrapper" :class="{ 'is-pending': readingStatsPending }" v-show="readingStatsHasData || readingStatsPending">
                <reading-stats-banner v-if="!$vuetify.breakpoint.xsOnly" home :show-title="false" @has-stats="onReadingStatsHasData"></reading-stats-banner>
            </div>
            <home-section-card
                v-else-if="isLoggedIn && !$vuetify.breakpoint.xsOnly"
                v-show="readingStatsHasData || readingStatsPending"
                icon="mdi-chart-box-outline"
                :title="$t('index.readingStats.title')"
                storage-key="index.readingStats"
                :default-expanded="false"
                @toggle="onStatsToggle"
            >
                <reading-stats-banner v-show="statsExpanded" home :show-title="false" @has-stats="onReadingStatsHasData"></reading-stats-banner>
            </home-section-card>
        </div>

        <div
            v-if="isSectionEnabled('index.myReading')"
            class="home-section-slot"
            :style="{ order: sectionOrder.indexOf('index.myReading') }"
        >
            <home-section-card
                v-if="readingLoading && isLoggedIn && reading_books.length === 0"
                icon="mdi-book-open-page-variant-outline"
                :title="$t('index.myReading')"
                storage-key="index.myReading"
            >
                <v-row>
                    <v-col cols="4" xs="4" sm="3" md="2" lg="1" v-for="n in 12" :key="'reading-ph'+n" class="book-card">
                        <v-card class="ma-1">
                            <div class="book-img-container">
                                <v-skeleton-loader type="image" class="cover-fill-img"></v-skeleton-loader>
                            </div>
                        </v-card>
                    </v-col>
                </v-row>
            </home-section-card>
            <home-section-card
                v-else-if="reading_books.length > 0"
                icon="mdi-book-open-page-variant-outline"
                :title="$t('index.myReading')"
                storage-key="index.myReading"
            >
                <v-row>
                    <v-col cols="4" xs="4" sm="3" md="2" lg="1" v-for="(book,idx) in get_reading_books" :key="'reading'+idx+book.id" class="book-card">
                        <v-card :to="book.href" class="ma-1">
                            <div class="book-img-container reading-book-cover" :title="book.title">
                                <v-img
                                    :src="book.thumb"
                                    class="cover-fill-img book-img-hover"
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
            v-if="isSectionEnabled('index.socialRecommendation')"
            class="home-section-slot"
            :style="{ order: sectionOrder.indexOf('index.socialRecommendation') }"
        >
            <home-section-card
                v-if="social_recommend_books.length > 0"
                icon="mdi-star-check"
                :title="$t('index.socialRecommendation')"
                storage-key="index.socialRecommendation"
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
            v-if="isSectionEnabled('index.booklistRecommendation')"
            class="home-section-slot"
            :style="{ order: sectionOrder.indexOf('index.booklistRecommendation') }"
        >
            <home-section-card
                v-if="homepage_booklists.length > 0 || (lazyHome && !booklistsLoaded)"
                icon="mdi-format-list-bulleted-square"
                :title="$t('index.booklistRecommendation')"
                storage-key="index.booklistRecommendation"
                :default-expanded="!lazyHome"
                @toggle="onBooklistsToggle"
            >
                <div v-if="homepage_booklists.length === 0" class="text-center pa-4">
                    <v-progress-circular indeterminate size="24"></v-progress-circular>
                </div>
                <v-row v-else>
                    <v-col cols="12" md="6" v-for="b in homepage_booklists" :key="'home-booklist-' + b.id">
                        <BookListCard :booklist="b" :show-recommend-badge="true" @toggle-like="toggleBooklistLike" />
                    </v-col>
                </v-row>
            </home-section-card>
        </div>

        <div
            v-if="isSectionEnabled('index.randomRecommendation')"
            class="home-section-slot"
            :style="{ order: sectionOrder.indexOf('index.randomRecommendation') }"
        >
            <home-section-card
                v-if="random_books.length > 0"
                icon="mdi-apple-keyboard-command"
                :title="$t('index.randomRecommendation')"
                storage-key="index.randomRecommendation"
            >
                <template #header-extra>
                    <v-icon color="primary" class="ml-1 refresh-icon" :class="{ 'refresh-icon--spinning': refreshing.random }" @click="refreshBooks('random')">mdi-refresh</v-icon>
                </template>
                <v-row>
                    <v-col cols="4" xs="4" sm="3" md="2" lg="1" v-for="(book,idx) in get_random_books" :key="'rec'+idx+book.id" class="book-card">
                        <v-card :to="book.href" class="ma-1">
                            <div class="book-img-container" :title="reasonText(book) || book.title">
                                <v-img
                                    :src="book.thumb"
                                    class="cover-fill-img book-img-hover"
                                ></v-img>
                                <!-- 实体书角标 -->
                                <div v-if="book.book_type === 1" class="physical-book-badge">
                                    <v-icon small color="white">mdi-bookshelf</v-icon>
                                </div>
                                <div v-if="reasonText(book)" class="reason-badge">{{ reasonText(book) }}</div>
                            </div>
                        </v-card>
                    </v-col>
                </v-row>
            </home-section-card>
        </div>

        <div
            v-if="isSectionEnabled('index.newRecommendation')"
            class="home-section-slot"
            :style="{ order: sectionOrder.indexOf('index.newRecommendation') }"
        >
            <home-section-card
                v-if="get_recent_books.length > 0"
                icon="mdi-hexagram-outline"
                :title="$t('index.newRecommendation')"
                storage-key="index.newRecommendation"
            >
                <template #header-extra>
                    <v-icon color="primary" class="ml-1 refresh-icon" :class="{ 'refresh-icon--spinning': refreshing.new }" @click="refreshBooks('new')">mdi-refresh</v-icon>
                </template>
                <v-row>
                    <v-col cols="12">
                        <book-cards :books="get_recent_books">
                            <template #introduce="{ book }">
                                <div v-if="reasonText(book)" class="reason-line text-caption primary--text">{{ reasonText(book) }}</div>
                            </template>
                        </book-cards>
                    </v-col>
                </v-row>
            </home-section-card>
        </div>

        <div
            v-for="card in enabledCustomCards"
            :key="'custom-section-' + card.id"
            class="home-section-slot"
            :style="{ order: sectionOrder.indexOf('custom:' + card.id) }"
        >
            <home-custom-card :card="card" @state="onCustomCardState(card.id, $event)"></home-custom-card>
        </div>
    </div>

    <div v-if="showEmptyState" class="home-empty-state text-center pa-8">
        <v-icon size="48" color="grey lighten-1">mdi-view-dashboard-outline</v-icon>
        <p class="mt-3 mb-2">{{ $t("index.homeEmpty") }}</p>
        <v-btn v-if="isAdmin" color="primary" text :to="{ path: '/admin/settings', hash: '#sec-site-site-home-cards' }">
            {{ $t("index.homeConfigure") }}
        </v-btn>
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
import BookListCard from "~/components/BookListCard.vue";
import HomeSectionCard from "~/components/HomeSectionCard.vue";
import HomeCustomCard from "~/components/HomeCustomCard.vue";
import { cardSectionKey, defaultHomepageConfig, normalizeHomepageConfig } from "~/utils/homepage";
export default {
    name: 'IndexPage',
    components: {
        BookCards,
        ReadingStatsBanner: () => import("~/components/ReadingStatsBanner.vue"),
        LibraryOverview: () => import("~/components/LibraryOverview.vue"),
        BookListCard,
        HomeSectionCard,
        HomeCustomCard,
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
        homepageConfigNormalized() {
            if (!this.homepageConfig) {
                // 拿不到配置（旧后端 / 接口失败）时按老站点的默认可见性兜底：
                // 书单卡默认关闭、其余内置卡可见，而不是把首页整页隐藏
                const fallback = defaultHomepageConfig();
                fallback.hidden = ["index.booklistRecommendation"];
                return fallback;
            }
            return normalizeHomepageConfig(this.homepageConfig);
        },
        sectionOrder() {
            return this.homepageConfigNormalized.order;
        },
        hiddenSections() {
            return new Set(this.homepageConfigNormalized.hidden);
        },
        enabledCustomCards() {
            return this.homepageConfigNormalized.custom.filter(
                (card) => card.value && !this.hiddenSections.has(cardSectionKey(card))
            );
        },
        builtinHasContent() {
            if (this.isSectionEnabled('libraryStats')) return true;
            if (this.isSectionEnabled('readingStats') && this.readingStatsHasData) return true;
            if (this.isSectionEnabled('index.myReading') && this.reading_books.length > 0) return true;
            if (this.isSectionEnabled('index.socialRecommendation') && this.social_recommend_books.length > 0) return true;
            if (this.isSectionEnabled('index.booklistRecommendation') && this.homepage_booklists.length > 0) return true;
            if (this.isSectionEnabled('index.randomRecommendation') && this.random_books.length > 0) return true;
            if (this.isSectionEnabled('index.newRecommendation') && this.new_books.length > 0) return true;
            return false;
        },
        customCardsHaveContent() {
            // 配置了并且填了内容的卡片一定会渲染出外壳（0 结果也会显示"暂无书籍"），
            // "有没有书"不再等价于"有没有内容"
            return this.enabledCustomCards.length > 0;
        },
        customCardsLoading() {
            return Object.keys(this.customCardLoading).some((key) => this.customCardLoading[key]);
        },
        customCardsPending() {
            return this.enabledCustomCards.some(
                (card) => !(card.id in this.customCardLoading) && !(card.id in this.customCardBooks)
            );
        },
        homeLoading() {
            if (this.isSectionEnabled('libraryStats') && this.statsLoading) return true;
            if (this.isSectionEnabled('index.myReading') && this.readingLoading) return true;
            if (this.isSectionEnabled('readingStats') && this.readingStatsPending) return true;
            if (this.isSectionEnabled('index.booklistRecommendation') && !this.booklistsLoaded) return true;
            return this.customCardsLoading || this.customCardsPending;
        },
        showEmptyState() {
            if (this.homeLoading) return false;
            return !this.builtinHasContent && !this.customCardsHaveContent;
        },
        indexPage() {
            return this.$store.state.sys && this.$store.state.sys.indexPage;
        },
        isLoggedIn() {
            return !!(this.$store.state.user && this.$store.state.user.is_login);
        },
        isAdmin() {
            return !!(this.$store.state.user && this.$store.state.user.is_admin);
        },
        stats() {
            return this.libraryStats || {
                total_books: '-', ebook_count: '-', physical_count: '-', month_ebook_count: '-', month_physical_count: '-',
            };
        },
        readingStatsPending() {
            return this.isLoggedIn && !this.$vuetify.breakpoint.xsOnly && !this.readingStatsResolved;
        },
        sysReady() {
            return !!(this.$store.state.sys && this.$store.state.sys.version);
        },
        lazyHome() {
            const lite = this.$store.state.sys && this.$store.state.sys.lite;
            return !!(lite && lite.homeCollapse);
        },
        // 首页动效总开关（设置 › 站点与外观 › 首页与列表 › 首页动效，含书单封面自动滚动）。
        // sys 尚未加载时按开启处理，避免首屏误判成关闭；系统「减少动效」偏好在 CSS 层另行兜底
        homeMotionEnabled() {
            const sys = this.$store.state.sys;
            return !sys || sys.home_motion !== false;
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
                this.readingStatsResolved = false;
                if (this.isSectionEnabled('index.myReading')) {
                    this.loadReadingBooks();
                }
            } else {
                this.reading_books = [];
                this.readingStatsHasData = false;
                this.readingStatsResolved = false;
            }
        },
        homepageConfig: {
            deep: true,
            handler() {
                const ids = new Set(this.enabledCustomCards.map((card) => card.id));
                Object.keys(this.customCardBooks).forEach((key) => {
                    if (!ids.has(key)) {
                        this.$delete(this.customCardBooks, key);
                        this.$delete(this.customCardLoading, key);
                    }
                });
            },
        },
    },
    methods: {
        isSectionEnabled(section) {
            return !this.hiddenSections.has(section);
        },
        onCustomCardState(id, state) {
            this.$set(this.customCardBooks, id, !!(state && state.hasBooks));
            this.$set(this.customCardLoading, id, !!(state && state.loading));
        },
        async loadLibraryStats() {
            this.statsLoading = true;
            try {
                const rsp = await this.$backend('/library/stats');
                if (rsp.err === 'ok') {
                    this.libraryStats = rsp.stats;
                }
            } catch (error) {
                console.warn('Failed to load library stats:', error);
            } finally {
                this.statsLoading = false;
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
        reasonText(book) {
            const reason = book.reason;
            if (!reason || !this.$te('index.reason.' + reason.type)) {
                return '';
            }
            return this.$t('index.reason.' + reason.type, { value: reason.value });
        },
        refreshBooks(section) {
            // 请求在途时忽略重复点击，图标以自旋反馈加载状态
            if (this.refreshing[section]) {
                return;
            }
            this.$set(this.refreshing, section, true);
            const shown = this.random_books.concat(this.new_books).map(b => b.id);
            this.$backend('/index?refresh=1&exclude=' + shown.join(',')).then( rsp => {
                if (rsp.err !== 'ok') {
                    return;
                }
                if (section === 'new') {
                    this.new_books = rsp.new_books || [];
                } else {
                    this.random_books = rsp.random_books || [];
                }
            }).catch( error => {
                console.error('Failed to refresh books:', error);
            }).finally( () => {
                this.$set(this.refreshing, section, false);
            });
        },
        async loadReadingBooks() {
            if (!this.isLoggedIn || !this.isSectionEnabled('index.myReading')) {
                this.reading_books = [];
                return;
            }
            this.readingLoading = true;
            try {
                // home=1 标记这是首页发起的请求，后台在 ENABLE_HOMEPAGE_READING_BOOKS=False
                // 时会直接返回空列表（不影响 /reading 在读书籍列表页本身）
                const rsp = await this.$backend('/reading?home=1&size=12');
                if (rsp.err === 'ok') {
                    this.reading_books = rsp.books || [];
                }
            } catch (error) {
                console.warn('Failed to load reading books:', error);
            } finally {
                this.readingLoading = false;
            }
        },
        onReadingStatsHasData(hasData) {
            this.readingStatsHasData = hasData;
            if (this.isLoggedIn) {
                this.readingStatsResolved = true;
            }
        },
        defer(fn, delay) {
            const id = setTimeout(() => {
                if (window.requestIdleCallback) {
                    window.requestIdleCallback(fn, { timeout: 2000 });
                } else {
                    fn();
                }
            }, delay);
            this.deferTimers.push(id);
        },
        onBooklistsToggle(expanded) {
            if (expanded && this.lazyHome && !this.booklistsLoaded) {
                this.loadBooklists();
            }
        },
        onStatsToggle(expanded) {
            if (expanded) {
                this.statsExpanded = true;
            }
        },
        async loadBooklists() {
            if (!this.isSectionEnabled('index.booklistRecommendation')) {
                this.booklistsLoaded = true;
                return;
            }
            try {
                const rsp = await this.$backend('/booklists/homepage');
                if (rsp.err === 'ok') {
                    this.homepage_booklists = rsp.booklists || [];
                }
            } catch (error) {
                console.warn('Failed to load homepage booklists:', error);
            } finally {
                this.booklistsLoaded = true;
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
    },
    mounted() {
        setTimeout(() => this.checkReleaseNotes(), 1500);
        if (this.isSectionEnabled('index.myReading')) {
            this.loadReadingBooks();
        }
        if (this.isSectionEnabled('libraryStats')) {
            if (this.sysReady && this.lazyHome) {
                this.defer(() => this.loadLibraryStats(), 300);
            } else {
                this.loadLibraryStats();
            }
        }
        if (this.isSectionEnabled('index.booklistRecommendation') && !(this.sysReady && this.lazyHome)) {
            this.loadBooklists();
        }
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
        this.deferTimers.forEach((id) => clearTimeout(id));
        if (this.countdownTimer) {
            clearInterval(this.countdownTimer);
        }
    },
    created() {
        this.$store.commit('navbar', true);
        this.readingLoading = this.isLoggedIn;
    },
    async asyncData({ app, res }) {
        if ( res !== undefined ) {
            res.setHeader('Cache-Control', 'no-cache');
        }
        // /api/index 的每个返回分支都带归一化后的 homepage 配置，无需再请求 /homepage。
        // 旧后端没有该字段时 homepageConfig 为 null，computed 里回退到老站点默认可见性；
        // 额外请求 /homepage 在旧后端会 404 并弹出全局错误框，所以不做探测。
        const { homepage, ...indexRsp } = (await app.$backend("/index")) || {};
        return {
            ...indexRsp,
            homepageConfig: homepage || null,
        };
    },
    data: () => ({
        random_books: [],
        new_books: [],
        social_recommend_books: [],
        homepage_booklists: [],
        reading_books: [],
        refreshing: { random: false, new: false },
        readingStatsHasData: false,
        readingStatsResolved: false,
        readingLoading: false,
        statsExpanded: false,
        booklistsLoaded: false,
        deferTimers: [],
        libraryStats: null,
        showDetail: false,
        releaseNotesDialog: false,
        releaseNotesContent: '',
        countdown: 10,
        countdownTimer: null,
        homepageConfig: null,
        statsLoading: true,
        customCardBooks: {},
        customCardLoading: {},
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

.reading-stats-banner-wrapper.is-pending {
    min-height: 198px;
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

.stats-toggle {
    margin-left: 8px;
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
        flex-wrap: nowrap;
        align-items: flex-start;
        gap: 8px;
    }

    .stats-toggle {
        flex: none;
        margin-left: 0;
        margin-top: 2px;
    }

    .stats-content {
        justify-content: flex-start;
        min-width: 0;
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

.home-empty-state {
    background: rgba(245, 255, 248, 0.8);
    border-radius: 10px;
    margin-top: 5px;
}

.theme--dark .home-empty-state {
    background: rgba(0, 0, 0, 0.8);
}

.home-section-slot {
    display: flex;
    flex-direction: column;
}

/* ── #140-1 首屏区块 / 封面进场过渡 ───────────────────────────────
   纯 CSS keyframes：SSR 首帧 HTML 与 hydration 前一致，动画由浏览器在首绘时
   自行启动。区块整体 fade + 轻微上浮；封面在区块内按相邻次序 30ms 递进 stagger
   （.book-list-card 是 BookCards 的横排卡，新书推荐区走它），
   第 12 个之后不再递增——新书区块可达上百本，不能把尾部拖得太久 */
.home-section-slot {
    animation: home-section-in 400ms cubic-bezier(0.22, 0.61, 0.36, 1) backwards;
}

@keyframes home-section-in {
    from {
        opacity: 0;
        transform: translateY(10px);
    }
}

.home-section-slot .book-card,
.home-section-slot .book-list-card {
    animation: home-cover-in 360ms cubic-bezier(0.22, 0.61, 0.36, 1) backwards;
}

@keyframes home-cover-in {
    from {
        opacity: 0;
        transform: translateY(8px);
    }
}

/* 「换一批」返回后数组整体替换、卡片 key 变化重新插入，这里的进场动画会随之
   重放一遍，正好充当换书过渡；书没变的卡（key 未变）不重放、不闪 */
.home-section-slot .book-card:nth-child(n+2),
.home-section-slot .book-list-card:nth-child(n+2) { animation-delay: 30ms; }

.home-section-slot .book-card:nth-child(n+3),
.home-section-slot .book-list-card:nth-child(n+3) { animation-delay: 60ms; }

.home-section-slot .book-card:nth-child(n+4),
.home-section-slot .book-list-card:nth-child(n+4) { animation-delay: 90ms; }

.home-section-slot .book-card:nth-child(n+5),
.home-section-slot .book-list-card:nth-child(n+5) { animation-delay: 120ms; }

.home-section-slot .book-card:nth-child(n+6),
.home-section-slot .book-list-card:nth-child(n+6) { animation-delay: 150ms; }

.home-section-slot .book-card:nth-child(n+7),
.home-section-slot .book-list-card:nth-child(n+7) { animation-delay: 180ms; }

.home-section-slot .book-card:nth-child(n+8),
.home-section-slot .book-list-card:nth-child(n+8) { animation-delay: 210ms; }

.home-section-slot .book-card:nth-child(n+9),
.home-section-slot .book-list-card:nth-child(n+9) { animation-delay: 240ms; }

.home-section-slot .book-card:nth-child(n+10),
.home-section-slot .book-list-card:nth-child(n+10) { animation-delay: 270ms; }

.home-section-slot .book-card:nth-child(n+11),
.home-section-slot .book-list-card:nth-child(n+11) { animation-delay: 300ms; }

.home-section-slot .book-card:nth-child(n+12),
.home-section-slot .book-list-card:nth-child(n+12) { animation-delay: 330ms; }

.refresh-icon {
    cursor: pointer;
    transition: transform 0.28s ease, color 0.28s ease;
}

.refresh-icon:hover {
    transform: rotate(180deg) scale(1.12);
    color: #1976d2 !important;
}

/* #140-2 「换一批」请求在途时的自旋反馈。这是功能性加载指示（与
   v-progress-circular 同类），站长关闭首页动效 / 系统减少动效时也保留 */
@keyframes refresh-icon-spin {
    to {
        transform: rotate(360deg);
    }
}

.refresh-icon--spinning {
    animation: refresh-icon-spin 0.8s linear infinite;
    opacity: 0.75;
}

.book-img-container {
    position: relative;
    display: block;
    width: 100%;
    aspect-ratio: 11 / 15;
    overflow: hidden;
    /* #140-3 封面加载期间的占位底色，弱网下不再是一片空白 */
    background: rgba(0, 0, 0, 0.05);
}

.theme--dark .book-img-container {
    background: rgba(255, 255, 255, 0.08);
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

.reason-badge {
    position: absolute;
    left: 0;
    right: 0;
    bottom: 0;
    padding: 2px 4px;
    font-size: 10px;
    line-height: 14px;
    color: white;
    background: rgba(0, 0, 0, 0.55);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    z-index: 3;
}

.reason-line {
    margin: 2px 4px;
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

/* ── #140-3 封面加载淡入 ─────────────────────────────────────────
   VImg 自带 fade-transition（Vue 2 对组件 vnode 会从 data.attrs 兜底提取
   props，VImg 挂在 attrs 上的 name/mode 实际有效，默认 0.3s 淡入本就生效）。
   这里把首页封面该过渡调长到 450ms，弱网下加载完成的浮现更柔和；
   前缀限定在首页区块内，其他页面维持原生 0.3s。
   Vuetify 对 transition-default() 生成的规则自带 !important，覆盖必须跟随；
   图片自身 loading 期间由 .book-img-container 的占位底色兜住 */
.home-section-slot .v-image__image.fade-transition-enter-active {
    transition: opacity 450ms ease !important;
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

/* ── 首页卡片悬停反馈 ──────────────────────────────────────────────
   整卡轻微上浮 + 阴影，和封面自身的放大叠在一起，让各区块手感一致。
   时长/缓动/位移统一收在下面三个变量里，以后调手感只改这里。 */
.home-sections-container {
    --card-hover-lift: -3px;
    --card-hover-duration: 200ms;
    --card-hover-ease: cubic-bezier(0.22, 0.61, 0.36, 1);
}

/* 前缀 .home-section-slot 不能省：本文件的样式是非 scoped 的全局样式，
   而 .book-card 这个类 history.vue 也在用，不加前缀会波及那些页面 */
.home-section-slot .book-card .v-card {
    transition:
        transform var(--card-hover-duration) var(--card-hover-ease),
        box-shadow var(--card-hover-duration) ease;
}

.library-stats-bar {
    transition: box-shadow var(--card-hover-duration) ease;
}

/* 只在真正有鼠标指针的设备上启用悬停位移，避免触屏上点完一直"粘"着 */
@media (hover: hover) and (pointer: fine) {
    .home-section-slot .book-card .v-card:hover {
        transform: translateY(var(--card-hover-lift));
        box-shadow: 0 8px 20px rgba(0, 0, 0, 0.14);
    }

    .theme--dark .home-section-slot .book-card .v-card:hover {
        box-shadow: 0 8px 20px rgba(0, 0, 0, 0.55);
    }

    /* 在读卡片的封面上盖着 .reading-hover-overlay 圆形按钮，指针落在按钮上而不是图片上，
       所以这里不能用 .book-img-hover:hover，必须跟着容器走。放大倍数也比其它卡小，
       免得和按钮自己的弹出动画抢视线 */
    .reading-book-cover:hover .book-img-hover {
        transform: translateY(-50%) scale(1.08);
    }

    .library-stats-bar:hover {
        box-shadow: 0 10px 18px rgba(0, 0, 0, 0.2);
    }
}

/* 用户要求减少动效时只去掉过渡（瞬间切换终态），不改 transform 本身 ——
   .cover-fill-img 靠 translateY(-50%) 做垂直居中，这里覆写成 none 会让封面错位 */
@media (prefers-reduced-motion: reduce) {
    .home-section-slot .book-card .v-card,
    .book-img-hover,
    .library-stats-bar {
        transition: none;
    }
}

/* ── 首页动效总开关的关闭态（ENABLE_HOME_MOTION=False → .home-motion-reduced）
   与系统 prefers-reduced-motion：停用 #140 新增的进场 / 淡入动画，区块直接呈现
   终态（书单封面自动滚动在 BookListCard 里另行停止）。
   「换一批」在途自旋是功能性加载指示，两种模式下都保留 */
.home-motion-reduced .home-section-slot,
.home-motion-reduced .home-section-slot .book-card,
.home-motion-reduced .home-section-slot .book-list-card {
    animation: none;
}

.home-motion-reduced .home-section-slot .v-image__image.fade-transition-enter-active {
    transition: none !important;
}

@media (prefers-reduced-motion: reduce) {
    .home-section-slot,
    .home-section-slot .book-card,
    .home-section-slot .book-list-card {
        animation: none;
    }

    .home-section-slot .v-image__image.fade-transition-enter-active {
        transition: none !important;
    }
}
</style>

