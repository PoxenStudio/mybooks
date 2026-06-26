<template>
    <div>
    <!-- 书库统计标题栏 -->
    <v-row v-if="libraryStats" class="library-stats-bar">
        <v-col cols=12>
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
                    <div class="stat-separator">|</div>
                    <div class="stat-group">
                        <span class="stat-label">{{ $t('index.physicalCount') }}:</span>
                        <span class="stat-value">{{ libraryStats.physical_count }}</span>
                    </div>
                    <div class="stat-separator">|</div>
                    <div class="stat-group">
                        <span class="stat-label">{{ $t('index.monthNewBooks') }}:</span>
                        <span class="stat-value month-new">
                            {{ $t('index.ebookCount') }} {{ libraryStats.month_ebook_count }}
                            + {{ $t('index.physicalCount') }} {{ libraryStats.month_physical_count }}
                        </span>
                    </div>
                </div>
            </div>
        </v-col>
    </v-row>

    <v-row v-if="random_books.length > 0">
        <v-col cols=12>
            <div class="d-flex align-center">
                <p class="ma-0 title">{{ $t('index.randomRecommendation') }}</p>
                <v-icon color="primary" class="ml-1 refresh-icon" @click="refreshBooks('all')">mdi-refresh</v-icon>
            </div>
        </v-col>
        <v-col cols=4 xs=4 sm=3 md=2 lg=1 v-for="(book,idx) in get_random_books" :key="'rec'+idx+book.id" class="book-card">
            <v-card :to="book.href" class="ma-1" outlined>
                <div class="book-img-container" :title="book.title">
                    <v-img
                        :src="book.thumb"
                        :aspect-ratio="11/15"
                        style="border-radius: 12px;"
                        class="book-img-hover"
                        contain
                    ></v-img>
                    <!-- 实体书角标 -->
                    <div v-if="book.book_type === 1" class="physical-book-badge">
                        <v-icon small color="white">mdi-bookshelf</v-icon>
                    </div>
                </div>
            </v-card>
        </v-col>
    </v-row>
    <v-row>
        <v-col cols=12 v-if="random_books.length > 0">
            <v-divider class="new-legend"></v-divider>
            <p class="ma-0 title">{{ $t('index.newRecommendation') }}</p>
        </v-col>
        <v-col cols=12>
            <book-cards :books="get_recent_books"></book-cards>
        </v-col>
    </v-row>

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
export default {
    name: 'IndexPage',
    components: {
        BookCards,
    },
    computed: {
        get_random_books: function() {
            return this.random_books.map( b => {
                b['href'] = "/book/" + b.id;
                return b;
            });
        },
        get_recent_books: function() {
            return this.new_books.map( b => {
                b['href'] = "/book/" + b.id;
                return b;
            });
        },
        indexPage() {
            return this.$store.state.sys && this.$store.state.sys.indexPage;
        },
    },
    watch: {
        indexPage: {
            handler: function(val) {
                this.checkRedirect(val);
            },
            immediate: true
        }
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
                }
            }).catch( error => {
                console.error('Failed to refresh books:', error);
            });
        }
    },
    mounted() {
        this.loadLibraryStats();
        this.checkReleaseNotes();
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
        const sys = this.$store.state.sys || {};
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
        libraryStats: null,
        releaseNotesDialog: false,
        releaseNotesContent: '',
        countdown: 10,
        countdownTimer: null,
    }),
    head: () => ({
        titleTemplate: "%s",
    })
}
</script>

<style>
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

.book-img-hover {
    transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    will-change: transform;
}

.book-img-hover:hover {
    transform: scale(1.06);
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

