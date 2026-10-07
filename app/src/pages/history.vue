<template>
    <div>
        <!-- ═══════════ 阅读统计仪表盘 ═══════════ -->
        <template v-if="dashboard && dashboard.enabled">
            <div class="dash-header" :class="{ 'is-dark': isDark }">
                <div class="dash-header-main">
                    <div>
                        <div class="dash-total">{{ totalDurationText }}</div>
                        <div class="dash-since" v-if="firstReadingDate">
                            {{ firstReadingDate }} {{ $t('history.dashboard.since') }}
                        </div>
                    </div>
                    <v-btn icon small class="dash-edit-btn" :color="editMode ? 'primary' : ''" @click="editMode = !editMode">
                        <v-icon>mdi-pencil</v-icon>
                    </v-btn>
                </div>
            </div>

            <div class="dash-cards" :class="{ 'is-dark': isDark }">
                <client-only>
                    <draggable
                        v-model="visibleCards"
                        class="dash-cards-grid"
                        v-bind="dragOptions"
                        @change="saveCardConfig"
                    >
                        <div
                            v-for="cardId in visibleCards"
                            :key="cardId"
                            class="dash-card"
                            :class="[{ wide: isWideCard(cardId) }, 'dash-card-' + cardId]"
                        >
                            <v-btn
                                v-if="editMode"
                                icon
                                x-small
                                class="card-remove"
                                @click.stop="removeCard(cardId)"
                            ><v-icon small>mdi-close-circle</v-icon></v-btn>

                            <!-- 阅读天数 -->
                            <template v-if="cardId === 'totalDays'">
                                <div class="card-label">
                                    <v-icon small class="mr-1">mdi-calendar-month-outline</v-icon>{{ $t('history.dashboard.card_totalDays') }}
                                </div>
                                <div class="card-number">{{ dashboard.total_days }}</div>
                            </template>

                            <!-- 阅读书籍 -->
                            <template v-else-if="cardId === 'totalBooks'">
                                <div class="card-label">
                                    <v-icon small class="mr-1">mdi-book-multiple-outline</v-icon>{{ $t('history.dashboard.card_totalBooks') }}
                                </div>
                                <div class="card-number">{{ dashboard.total_books }}</div>
                            </template>

                            <!-- 本周时长（环比上周） -->
                            <template v-else-if="cardId === 'weekDuration'">
                                <div class="card-label">
                                    <v-icon small class="mr-1">mdi-clock-outline</v-icon>{{ $t('history.dashboard.card_weekDuration') }}
                                </div>
                                <div class="card-number card-number-sm">{{ formatDuration(dashboard.period.last7_seconds) }}</div>
                                <div class="ratio-bar">
                                    <div class="ratio-bar-fill" :style="{ background: primaryColor, width: weekRatioPercent + '%' }"></div>
                                </div>
                                <div class="card-sub">{{ weekVsText }}</div>
                            </template>

                            <!-- 连续阅读 -->
                            <template v-else-if="cardId === 'streak'">
                                <div class="card-label">
                                    <v-icon small class="mr-1 streak-flame">mdi-fire</v-icon>{{ $t('history.dashboard.card_streak') }}
                                </div>
                                <div class="card-number" v-if="dashboard.streak.current > 0">
                                    {{ $t('history.dashboard.streakNow', { n: dashboard.streak.current }) }}
                                </div>
                                <div class="card-sub" v-if="dashboard.streak.current > 0">
                                    {{ $t('history.dashboard.bestStreak', { n: dashboard.streak.best }) }}
                                </div>
                                <div class="card-sub streak-motivation" v-else>
                                    {{ $t('history.dashboard.streakMotivation') }}
                                </div>
                            </template>

                            <!-- 在读的书 -->
                            <template v-else-if="cardId === 'currentBook'">
                                <div class="card-label">
                                    <v-icon small class="mr-1">mdi-book-open-page-variant-outline</v-icon>{{ $t('history.dashboard.card_currentBook') }}
                                </div>
                                <div class="current-book-row" v-if="currentBooks.length">
                                    <nuxt-link
                                        v-for="b in currentBooks"
                                        :key="b.id"
                                        class="current-book-item"
                                        :to="'/book/' + b.id"
                                    >
                                        <v-img :src="b.thumb || b.img" class="current-book-cover" />
                                        <div class="current-book-meta">
                                            <div class="current-book-title">{{ b.title }}</div>
                                            <div class="current-book-author">{{ b.author }}</div>
                                        </div>
                                    </nuxt-link>
                                </div>
                                <div class="card-sub" v-else>{{ $t('history.dashboard.noCurrentBook') }}</div>
                            </template>

                            <!-- 即将读完 -->
                            <template v-else-if="cardId === 'nearFinish'">
                                <div class="card-label">
                                    <v-icon small class="mr-1">mdi-progress-check</v-icon>{{ $t('history.dashboard.card_nearFinish') }}
                                </div>
                                <div class="near-finish-body" v-if="nearFinishBooks.length">
                                    <div class="ring" :style="{ background: ringGradient }">
                                        <div class="ring-inner">
                                            <span class="ring-number">{{ Math.round(nearFinishAvg) }}<small>%</small></span>
                                            <span class="ring-label">{{ $t('history.dashboard.avgProgress') }}</span>
                                        </div>
                                    </div>
                                    <div class="near-finish-list">
                                        <div v-for="b in nearFinishBooks.slice(0, 3)" :key="b.book_id" class="near-finish-item">
                                            <span class="near-finish-title">{{ b.title }}</span>
                                            <span class="near-finish-percent" :style="{ color: primaryColor }">{{ b.progress_percent }}%</span>
                                        </div>
                                    </div>
                                </div>
                                <div class="card-sub" v-else>{{ $t('history.dashboard.noNearFinish') }}</div>
                            </template>

                            <!-- 近 7 天 / 近 30 天 -->
                            <template v-else-if="cardId === 'last7' || cardId === 'last30'">
                                <div class="card-label">
                                    <v-icon small class="mr-1">{{ cardId === 'last7' ? 'mdi-calendar-week-begin' : 'mdi-calendar-range' }}</v-icon>
                                    {{ $t(cardId === 'last7' ? 'history.dashboard.card_last7' : 'history.dashboard.card_last30') }}
                                </div>
                                <div class="card-number card-number-sm">{{ formatDuration(periodSeconds(cardId)) }}</div>
                                <div class="ghost-number" :style="{ color: ghostColor }">{{ cardId === 'last7' ? '7' : '30' }}</div>
                            </template>
                        </div>
                    </draggable>
                </client-only>

                <!-- 编辑模式：重新添加被移除的卡片 -->
                <div v-if="editMode" class="dash-add-row" :class="{ 'is-dark': isDark }">
                    <template v-if="hiddenCardDefs.length">
                        <span class="dash-add-label">{{ $t('history.dashboard.addCards') }}</span>
                        <v-chip
                            v-for="def in hiddenCardDefs"
                            :key="def.id"
                            small
                            outlined
                            color="primary"
                            class="ma-1"
                            @click="addCard(def.id)"
                        >
                            <v-icon small left>{{ def.icon }}</v-icon>{{ $t('history.dashboard.card_' + def.id) }}
                        </v-chip>
                    </template>
                    <span v-else class="dash-add-label">{{ $t('history.dashboard.allCardsShown') }}</span>
                </div>

                <!-- 长时间没有阅读的空状态卡 -->
                <div v-if="showEmptyState" class="dash-card wide empty-card">
                    <div class="empty-kaomoji">(:˘＿˘:)</div>
                    <div class="empty-title">{{ $t('history.dashboard.emptyTitle') }}</div>
                    <div class="empty-sub">{{ $t('history.dashboard.emptySub') }}</div>
                </div>
            </div>

            <!-- 周 / 月 / 年 / 总 -->
            <div class="dash-range" :class="{ 'is-dark': isDark }">
                <div class="range-head">
                    <v-btn-toggle v-model="rangeView" mandatory dense rounded class="range-toggle">
                        <v-btn small value="week">{{ $t('history.dashboard.viewWeek') }}</v-btn>
                        <v-btn small value="month">{{ $t('history.dashboard.viewMonth') }}</v-btn>
                        <v-btn small value="year">{{ $t('history.dashboard.viewYear') }}</v-btn>
                        <v-btn small value="all">{{ $t('history.dashboard.viewAll') }}</v-btn>
                    </v-btn-toggle>
                    <div class="range-nav">
                        <template v-if="rangeView !== 'all'">
                            <v-btn icon small @click="navRange(-1)"><v-icon>mdi-chevron-left</v-icon></v-btn>
                            <span class="range-title">{{ rangeTitle }}</span>
                            <v-btn icon small :disabled="!canGoNext" @click="navRange(1)"><v-icon>mdi-chevron-right</v-icon></v-btn>
                        </template>
                        <span v-else class="range-title range-title-single">{{ $t('history.dashboard.allTime') }}</span>
                    </div>
                </div>
                <div class="range-body">
                    <div class="chart-box" :class="{ 'chart-box-auto': rangeView === 'month' }">
                        <bar-chart v-if="rangeView === 'week'" :chart-data="weekChartData" :chart-options="weekChartOptions" />
                        <reading-month-calendar v-else-if="rangeView === 'month'" :days="rangeDays" :month-start="rangeView === 'month' ? anchor : ''" />
                        <div v-else class="heatmap-scroll">
                            <div class="heatmap-scroll-inner" :style="{ minWidth: heatmapMinWidth }">
                                <reading-heatmap :days="rangeDays" />
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </template>

        <!-- ═══════════ 阅读书目（默认折叠） ═══════════ -->
        <div class="walls-section">
            <div class="walls-toggle" @click="wallsOpen = !wallsOpen">
                <v-icon small>{{ wallsOpen ? 'mdi-chevron-up' : 'mdi-chevron-down' }}</v-icon>
                <legend class="ma-0 ml-1">{{ $t('history.dashboard.bookSection') }}</legend>
                <v-chip x-small class="ml-2">{{ wallTotalCount }}</v-chip>
            </div>
            <v-expand-transition>
                <div v-show="wallsOpen">
                    <!-- 阅读统计卡片 -->
                    <v-row v-if="readingStats">
                        <v-col cols=12>
                            <legend>{{ $t('history.readingStats') }}</legend>
                            <v-divider class="mb-4"></v-divider>
                        </v-col>
                        <v-col cols=6 sm=3>
                            <v-card class="pa-3 text-center stats-card gradient-bg-primary">
                                <v-card-title class="justify-center pa-2">
                                    <div class="stat-number-badge">{{ readingStats.total_reading }}</div>
                                </v-card-title>
                                <v-card-subtitle class="stat-label-text">{{ $t('history.totalReading') }}</v-card-subtitle>
                            </v-card>
                        </v-col>
                        <v-col cols=6 sm=3>
                            <v-card class="pa-3 text-center stats-card gradient-bg-success">
                                <v-card-title class="justify-center pa-2">
                                    <div class="stat-number-badge">{{ readingStats.total_read_done }}</div>
                                </v-card-title>
                                <v-card-subtitle class="stat-label-text">{{ $t('history.totalReadDone') }}</v-card-subtitle>
                            </v-card>
                        </v-col>
                        <v-col cols=6 sm=3>
                            <v-card class="pa-3 text-center stats-card gradient-bg-info">
                                <v-card-title class="justify-center pa-2">
                                    <div class="stat-number-badge">{{ readingStats.month_reading }}</div>
                                </v-card-title>
                                <v-card-subtitle class="stat-label-text">{{ $t('history.monthReading') }}</v-card-subtitle>
                            </v-card>
                        </v-col>
                        <v-col cols=6 sm=3>
                            <v-card class="pa-3 text-center stats-card gradient-bg-orange">
                                <v-card-title class="justify-center pa-2">
                                    <div class="stat-number-badge">{{ readingStats.month_read_done }}</div>
                                </v-card-title>
                                <v-card-subtitle class="stat-label-text">{{ $t('history.monthReadDone') }}</v-card-subtitle>
                            </v-card>
                        </v-col>
                    </v-row>

                    <!-- 当前在读书籍 -->
                    <v-row v-if="currentReadingBooks && currentReadingBooks.length > 0">
                        <v-col cols=12>
                            <legend>{{ $t('history.currentReadingBooks') }}</legend>
                            <v-divider></v-divider>
                        </v-col>
                        <v-col cols=4 sm=2 v-for="book in currentReadingBooks" :key="'reading-' + book.id">
                            <v-card :to="'/book/' + book.id" class="ma-1 book-card">
                                <v-img :src="book.thumb || book.img" :aspect-ratio="11/15">
                                    <v-chip small color="primary" class="ma-1 reading-chip">{{ $t('readingState.reading') }}</v-chip>
                                </v-img>
                            </v-card>
                        </v-col>
                    </v-row>

                    <!-- 本月读完书籍 -->
                    <v-row v-if="monthReadDoneBooks && monthReadDoneBooks.length > 0">
                        <v-col cols=12>
                            <legend>{{ $t('history.monthReadDoneBooks') }}</legend>
                            <v-divider></v-divider>
                        </v-col>
                        <v-col cols=4 sm=2 v-for="book in monthReadDoneBooks" :key="'done-' + book.id">
                            <v-card :to="'/book/' + book.id" class="ma-1 book-card">
                                <v-img :src="book.thumb || book.img" :aspect-ratio="11/15">
                                    <v-chip small color="success" class="ma-1 done-chip">{{ $t('readingState.done') }}</v-chip>
                                </v-img>
                            </v-card>
                        </v-col>
                    </v-row>

                    <!-- 在线阅读历史 -->
                    <v-row align=start v-if="history.length == 0">
                        <v-col cols=12>
                            <p class="title"> {{ $t('history.noRecords') }} </p>
                        </v-col>
                    </v-row>
                    <v-row v-else v-for="item in history" :key="item.name">
                        <v-col cols=12>
                            <div class="d-flex align-center">
                                <legend>{{ $t(`history.${item.name}`) }}</legend>
                                <v-btn
                                    v-if="item.name === 'onlineReading' && canClearHistory"
                                    small
                                    text
                                    color="error"
                                    class="ml-2"
                                    :loading="clearingHistory"
                                    @click="clearHistory(item)"
                                >{{ $t('history.clearHistory') }}</v-btn>
                            </div>
                            <v-divider></v-divider>
                        </v-col>
                        <v-col cols=12 v-if="item.books.length==0" >
                            <p class="pb-6">{{ $t('history.noBooks') }}</p>
                        </v-col>
                        <v-col cols=4 sm=2 v-else v-for="book in item.books" :key="item.name + book.id">
                            <v-card :to="book.href" class="ma-1 book-card">
                                <v-img :src="book.thumb || book.img" :aspect-ratio="11/15" > </v-img>
                            </v-card>
                        </v-col>
                    </v-row>
                </div>
            </v-expand-transition>
        </div>
    </div>
</template>

<script>
import draggable from 'vuedraggable';
import BarChart from '~/components/charts/BarChart.vue';
import ReadingHeatmap from '~/components/ReadingHeatmap.vue';
import ReadingMonthCalendar from '~/components/ReadingMonthCalendar.vue';
import { intlLocale } from '~/utils/intlLocale';

// 卡片目录：默认全部展示；用户移除的卡片保存在 localStorage，可随时重新添加
const CARD_DEFS = [
    { id: 'totalDays', wide: false },
    { id: 'totalBooks', wide: false },
    { id: 'weekDuration', wide: true },
    { id: 'streak', wide: false },
    { id: 'currentBook', wide: true },
    { id: 'nearFinish', wide: false },
    { id: 'last7', wide: false },
    { id: 'last30', wide: false },
];
const CARDS_KEY = 'mybooks_reading_dash_cards';

// Vuetify 2 的主题色存在 JS 里（ AppearanceMenu 的自定义主色也写回 currentTheme），
// 转 rgba 方便做透明度变体；非法值原样返回兜底
function hexToRgba(hex, alpha) {
    const raw = (hex || '#1976d2').trim();
    let h = raw.replace('#', '');
    if (h.length === 3) h = h.split('').map((c) => c + c).join('');
    const num = parseInt(h, 16);
    if (Number.isNaN(num) || (num >>> 0) > 0xffffff) return raw;
    const r = (num >> 16) & 255;
    const g = (num >> 8) & 255;
    const b = num & 255;
    return `rgba(${r},${g},${b},${alpha})`;
}

function toDate(dateStr) {
    return new Date(`${dateStr}T00:00:00`);
}

function toDayStr(d) {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${y}-${m}-${day}`;
}

function mondayOf(d) {
    const copy = new Date(d);
    copy.setHours(0, 0, 0, 0);
    copy.setDate(copy.getDate() - ((copy.getDay() + 6) % 7));
    return copy;
}

// ISO 周号（周一为一周起点，含第一个星期四的那周是第 1 周）
function isoWeekNumber(d) {
    const t = new Date(d);
    t.setHours(0, 0, 0, 0);
    t.setDate(t.getDate() + 3 - ((t.getDay() + 6) % 7));
    const week1 = new Date(t.getFullYear(), 0, 4);
    return 1 + Math.round(((t - week1) / 86400000 - 3 + ((week1.getDay() + 6) % 7)) / 7);
}

export default {
    components: {
        draggable,
        BarChart,
        ReadingHeatmap,
        ReadingMonthCalendar,
    },
    computed: {
        history: function() {
            return [
                { name: 'onlineReading', books: this.onlineReadingBooks },
            ]
        },
        canClearHistory: function() {
            return !!(this.user.allow_user_disable_statistic || this.user.is_admin);
        },
        isDark() {
            return this.$vuetify.theme.dark;
        },
        // ---------- 仪表盘头部 ----------
        totalDurationText() {
            const seconds = (this.dashboard && this.dashboard.totals.total_reading_seconds) || 0;
            if (seconds < 60) {
                return this.$t('history.dashboard.durationSeconds', { seconds });
            }
            const hours = Math.floor(seconds / 3600);
            const minutes = Math.floor((seconds % 3600) / 60);
            if (hours <= 0) {
                return this.$t('book.readingStats.durationMinutes', { minutes });
            }
            return this.$t('book.readingStats.durationHoursMinutes', { hours, minutes });
        },
        firstReadingDate() {
            return (this.dashboard && this.dashboard.first_reading_date) || null;
        },
        primaryColor() {
            const theme = (this.$vuetify && this.$vuetify.theme && this.$vuetify.theme.currentTheme) || {};
            return theme.primary || '#1976d2';
        },
        ghostColor() {
            return hexToRgba(this.primaryColor, this.isDark ? 0.28 : 0.1);
        },
        // ---------- 卡片 ----------
        visibleCards: {
            get() {
                return this.cardOrder;
            },
            set(value) {
                this.cardOrder = value;
            },
        },
        hiddenCardDefs() {
            return CARD_DEFS.filter((d) => !this.cardOrder.includes(d.id));
        },
        dragOptions() {
            return {
                animation: 180,
                delay: 250,
                delayOnTouchOnly: true,
                filter: 'a, button, input, .no-drag',
                preventOnFilter: false,
            };
        },
        // ---------- 卡片内容 ----------
        currentBooks() {
            return (this.currentReadingBooks || []).slice(0, 3);
        },
        nearFinishBooks() {
            return (this.dashboard && this.dashboard.near_finish_books) || [];
        },
        nearFinishAvg() {
            return (this.dashboard && this.dashboard.near_finish_avg_percent) || 0;
        },
        ringGradient() {
            const percent = Math.max(0, Math.min(100, this.nearFinishAvg));
            const track = this.isDark ? 'rgba(255,255,255,0.10)' : 'rgba(0,0,0,0.08)';
            return `conic-gradient(${this.primaryColor} ${percent}%, ${track} 0)`;
        },
        weekRatioPercent() {
            const last7 = (this.dashboard && this.dashboard.period.last7_seconds) || 0;
            const prev7 = (this.dashboard && this.dashboard.period.prev7_seconds) || 0;
            if (prev7 <= 0) return last7 > 0 ? 100 : 0;
            return Math.min(100, Math.round((last7 / prev7) * 100));
        },
        weekVsText() {
            const last7 = (this.dashboard && this.dashboard.period.last7_seconds) || 0;
            const prev7 = (this.dashboard && this.dashboard.period.prev7_seconds) || 0;
            if (prev7 <= 0) {
                return last7 > 0 ? this.$t('history.dashboard.noLastWeek') : this.$t('history.dashboard.vsLastWeekFlat');
            }
            const percent = Math.round(((last7 - prev7) / prev7) * 100);
            if (percent === 0) return this.$t('history.dashboard.vsLastWeekFlat');
            if (percent > 0) {
                return this.$t('history.dashboard.vsLastWeekUp', { p: Math.min(percent, 999) });
            }
            return this.$t('history.dashboard.vsLastWeekDown', { p: Math.min(-percent, 999) });
        },
        showEmptyState() {
            return !!this.dashboard && (this.dashboard.period.last30_seconds || 0) === 0;
        },
        // ---------- 周/月/年/总 ----------
        // anchor 的含义随视图变化：周 = 该周周一；月 = 该月 1 号；年 = 该年 1 月 1 号；总 = 不用
        rangeBounds() {
            const today = new Date();
            today.setHours(0, 0, 0, 0);
            if (this.rangeView === 'all') {
                if (!this.firstReadingDate) return null;
                return { start: mondayOf(toDate(this.firstReadingDate)), end: today };
            }
            if (!this.anchor) return null;
            const anchor = toDate(this.anchor);
            if (this.rangeView === 'week') {
                return { start: anchor, end: new Date(anchor.getFullYear(), anchor.getMonth(), anchor.getDate() + 6) };
            }
            if (this.rangeView === 'month') {
                return {
                    start: anchor,
                    end: new Date(anchor.getFullYear(), anchor.getMonth() + 1, 0),
                };
            }
            return { start: anchor, end: new Date(anchor.getFullYear(), 11, 31) };
        },
        canGoNext() {
            if (!this.anchor) return false;
            const next = this.shiftAnchor(1);
            if (!next) return false;
            const today = new Date();
            today.setHours(0, 0, 0, 0);
            // 月/年锚点都是 1 号，周锚点是周一：不晚于今天即可继续右翻
            return next <= today;
        },
        rangeTitle() {
            if (!this.anchor) return '';
            const anchor = toDate(this.anchor);
            if (this.rangeView === 'week') {
                return `${anchor.getFullYear()} · ${this.$t('history.dashboard.weekTitle', { w: isoWeekNumber(anchor) })}`;
            }
            if (this.rangeView === 'month') {
                return this.$t('history.dashboard.monthTitle', { y: anchor.getFullYear(), m: anchor.getMonth() + 1 });
            }
            return this.$t('history.dashboard.yearTitle', { y: anchor.getFullYear() });
        },
        weekChartData() {
            // 本周还没过的日子后端不返回，补 0 凑满 7 天
            const values = [0, 0, 0, 0, 0, 0, 0];
            this.rangeDays.forEach((d, i) => {
                if (i < 7) values[i] = d.reading_seconds;
            });
            return {
                labels: this.weekdayLabels,
                datasets: [{
                    label: this.$t('history.dashboard.duration'),
                    data: values,
                    backgroundColor: hexToRgba(this.primaryColor, 0.75),
                    borderRadius: 6,
                }],
            };
        },
        chartTickColor() {
            return this.isDark ? '#eee' : '#333';
        },
        chartGridColor() {
            return this.isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.1)';
        },
        weekChartOptions() {
            const self = this;
            return {
                maintainAspectRatio: false,
                responsive: true,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: (ctx) => self.formatDuration(ctx.parsed.y),
                        },
                    },
                },
                scales: {
                    x: { ticks: { color: this.chartTickColor, font: { size: 11 } }, grid: { display: false } },
                    y: { beginAtZero: true, ticks: { color: this.chartTickColor, font: { size: 10 } }, grid: { color: this.chartGridColor } },
                },
            };
        },
        weekdayLabels() {
            const fmt = new Intl.DateTimeFormat(intlLocale(this.$i18n.locale), { weekday: 'short' });
            // 2023-10-02 是周一，取 7 天的短星期名，保证一~日的顺序
            return Array.from({ length: 7 }, (_v, i) => fmt.format(new Date(2023, 9, 2 + i)));
        },
        heatmapMinWidth() {
            const weeks = Math.ceil(this.rangeDays.length / 7) || 1;
            return `${Math.max(weeks * 16, 200)}px`;
        },
        // ---------- 折叠的阅读书目 ----------
        wallTotalCount() {
            return (this.currentReadingBooks ? this.currentReadingBooks.length : 0)
                + (this.monthReadDoneBooks ? this.monthReadDoneBooks.length : 0)
                + (this.onlineReadingBooks ? this.onlineReadingBooks.length : 0);
        },
    },
    data: () => ({
        user: {},
        readingStats: null,
        currentReadingBooks: [],
        monthReadDoneBooks: [],
        onlineReadingBooks: [],
        clearingHistory: false,
        dashboard: null,
        cardOrder: CARD_DEFS.map((d) => d.id),
        editMode: false,
        wallsOpen: false,
        rangeView: 'week',
        anchor: null,
        rangeDays: [],
    }),
    head() {
        return { title: this.$t('appHeader.reading_history') };
    },
    created() {
        this.init(this.$route);
    },
    beforeRouteUpdate(to, from, next) {
        this.init(to, next);
    },
    methods: {
        init(route, next) {
            this.$store.commit('navbar', true);

            // 获取用户信息
            this.$backend("/user/info?detail=1")
            .then( rsp => {
                this.user = rsp.user;
                this.loadCardConfig();
            });

            // 获取在线阅读历史（从 Reading 表读取）
            this.$backend("/user/history")
            .then( rsp => {
                if (rsp.err === 'ok') {
                    this.onlineReadingBooks = rsp.books || [];
                }
            })
            .catch(error => {
                console.warn('Failed to load reading history:', error);
            });

            // 获取阅读统计信息（在读/已读计数 + 封面墙）
            this.$backend("/reading/stats")
            .then( rsp => {
                if (rsp.err === 'ok') {
                    this.readingStats = rsp.stats;
                    this.currentReadingBooks = rsp.current_reading_books || [];
                    this.monthReadDoneBooks = rsp.month_read_done_books || [];
                }
            })
            .catch(error => {
                console.warn('Failed to load reading stats:', error);
            });

            // 阅读仪表盘（总时长/天数/连击/即将读完）
            this.loadDashboard();

            if ( next ) next();
        },
        loadDashboard() {
            this.$backend("/user/reading_stats")
            .then( rsp => {
                if (rsp.err === 'ok' && rsp.enabled) {
                    this.dashboard = rsp;
                    this.resetAnchor();
                } else {
                    this.dashboard = null;
                }
            })
            .catch(error => {
                console.warn('Failed to load reading dashboard:', error);
                this.dashboard = null;
            });
        },
        // ---------- 卡片配置 ----------
        cardsStorageKey() {
            // /user/info 不暴露数字 id，用 username 区分多用户
            const uid = (this.user && this.user.username) || 'anon';
            return `${CARDS_KEY}_${uid}`;
        },
        loadCardConfig() {
            let order = null;
            try {
                const raw = window.localStorage.getItem(this.cardsStorageKey());
                order = raw ? JSON.parse(raw) : null;
            } catch (e) {
                order = null;
            }
            if (Array.isArray(order)) {
                const valid = order.filter((id) => CARD_DEFS.some((d) => d.id === id));
                const missing = CARD_DEFS.map((d) => d.id).filter((id) => !valid.includes(id));
                this.cardOrder = valid.concat(missing);
            } else {
                this.cardOrder = CARD_DEFS.map((d) => d.id);
            }
        },
        saveCardConfig() {
            try {
                window.localStorage.setItem(this.cardsStorageKey(), JSON.stringify(this.cardOrder));
            } catch (e) {
                /* localStorage 不可用时静默降级为固定布局 */
            }
        },
        removeCard(cardId) {
            this.cardOrder = this.cardOrder.filter((id) => id !== cardId);
            this.saveCardConfig();
        },
        addCard(cardId) {
            if (!this.cardOrder.includes(cardId)) {
                this.cardOrder = this.cardOrder.concat([cardId]);
                this.saveCardConfig();
            }
        },
        isWideCard(cardId) {
            const def = CARD_DEFS.find((d) => d.id === cardId);
            return def ? def.wide : false;
        },
        periodSeconds(cardId) {
            if (!this.dashboard) return 0;
            return cardId === 'last7' ? this.dashboard.period.last7_seconds : this.dashboard.period.last30_seconds;
        },
        formatDuration(totalSeconds) {
            const seconds = totalSeconds || 0;
            const hours = Math.floor(seconds / 3600);
            const minutes = Math.floor((seconds % 3600) / 60);
            if (hours <= 0) {
                return this.$t('book.readingStats.durationMinutes', { minutes });
            }
            return this.$t('book.readingStats.durationHoursMinutes', { hours, minutes });
        },
        // ---------- 周/月/年/总 ----------
        resetAnchor() {
            const today = new Date();
            today.setHours(0, 0, 0, 0);
            if (this.rangeView === 'week') {
                this.anchor = toDayStr(mondayOf(today));
            } else if (this.rangeView === 'month') {
                this.anchor = toDayStr(new Date(today.getFullYear(), today.getMonth(), 1));
            } else if (this.rangeView === 'year') {
                this.anchor = toDayStr(new Date(today.getFullYear(), 0, 1));
            } else {
                this.anchor = null;
            }
            this.fetchRange();
        },
        shiftAnchor(dir) {
            const anchor = toDate(this.anchor);
            if (this.rangeView === 'week') {
                return new Date(anchor.getFullYear(), anchor.getMonth(), anchor.getDate() + 7 * dir);
            }
            if (this.rangeView === 'month') {
                return new Date(anchor.getFullYear(), anchor.getMonth() + dir, 1);
            }
            return new Date(anchor.getFullYear() + dir, 0, 1);
        },
        navRange(dir) {
            const next = this.shiftAnchor(dir);
            if (!next) return;
            const today = new Date();
            today.setHours(0, 0, 0, 0);
            if (dir > 0 && next > today) return;
            this.anchor = toDayStr(next);
            this.fetchRange();
        },
        async fetchRange() {
            const bounds = this.rangeBounds;
            if (!bounds) {
                this.rangeDays = [];
                return;
            }
            const today = new Date();
            today.setHours(0, 0, 0, 0);
            let end = bounds.end;
            if (end > today) end = today;
            if (bounds.start > end) {
                this.rangeDays = [];
                return;
            }
            try {
                const rsp = await this.$backend(
                    `/user/reading_range?start=${toDayStr(bounds.start)}&end=${toDayStr(end)}`
                );
                if (rsp.err === 'ok' && rsp.enabled) {
                    this.rangeDays = rsp.days || [];
                } else {
                    this.rangeDays = [];
                }
            } catch (error) {
                console.warn('Failed to load reading range:', error);
                this.rangeDays = [];
            }
        },
        clearHistory(_item) {
            this.clearingHistory = true;
            this.$backend('/user/history/clear', { method: 'POST' })
                .then(rsp => {
                    if (rsp.err === 'ok') {
                        this.onlineReadingBooks = [];
                    }
                })
                .finally(() => {
                    this.clearingHistory = false;
                });
        },
    },
    watch: {
        rangeView() {
            this.resetAnchor();
        },
    },
}
</script>

<style scoped>
/* ═══ 仪表盘头部 ═══ */
.dash-header {
    margin: 4px 0 12px;
}

.dash-header-main {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
}

.dash-total {
    font-size: 34px;
    font-weight: bold;
    line-height: 1.2;
    color: rgba(0, 0, 0, 0.87);
}

.dash-header.is-dark .dash-total {
    color: rgba(255, 255, 255, 0.92);
}

.dash-since {
    font-size: 13px;
    color: rgba(0, 0, 0, 0.5);
    margin-top: 2px;
}

.dash-header.is-dark .dash-since {
    color: rgba(255, 255, 255, 0.55);
}

/* ═══ 卡片网格 ═══ */
.dash-cards {
    margin-bottom: 8px;
}

.dash-cards-grid {
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
}

.dash-card {
    position: relative;
    flex: 1 1 calc(25% - 12px);
    min-width: 158px;
    max-width: 100%;
    min-height: 132px;
    background: #ffffff;
    border: 1px solid rgba(0, 0, 0, 0.06);
    border-radius: 16px;
    padding: 14px 16px;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
    overflow: hidden;
    cursor: grab;
}

.dash-card:active {
    cursor: grabbing;
}

.dash-card.wide {
    flex: 2 1 calc(50% - 12px);
}

.dash-cards.is-dark .dash-card {
    background: rgba(0, 0, 0, 0.82);
    border-color: transparent;
}

/* draggable 排序时的占位样式 */
.dash-cards-grid .sortable-ghost {
    opacity: 0.4;
}

.card-remove {
    position: absolute;
    top: 4px;
    right: 4px;
    z-index: 2;
}

.card-label {
    display: flex;
    align-items: center;
    font-size: 12px;
    color: rgba(0, 0, 0, 0.55);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.dash-cards.is-dark .card-label {
    color: rgba(255, 255, 255, 0.65);
}

.card-number {
    font-size: 26px;
    font-weight: bold;
    color: rgba(0, 0, 0, 0.87);
    margin-top: 8px;
    line-height: 1.25;
}

.card-number-sm {
    font-size: 22px;
}

.dash-cards.is-dark .card-number {
    color: rgba(255, 255, 255, 0.92);
}

.card-sub {
    font-size: 12px;
    color: rgba(0, 0, 0, 0.5);
    margin-top: 4px;
}

.dash-cards.is-dark .card-sub {
    color: rgba(255, 255, 255, 0.55);
}

.ratio-bar {
    height: 6px;
    border-radius: 3px;
    background: rgba(0, 0, 0, 0.08);
    margin-top: 8px;
    overflow: hidden;
}

.dash-cards.is-dark .ratio-bar {
    background: rgba(255, 255, 255, 0.12);
}

.ratio-bar-fill {
    height: 100%;
    border-radius: 3px;
    transition: width 0.4s ease;
}

.streak-flame {
    color: #f57c00 !important;
}

.streak-motivation {
    font-size: 13px;
    line-height: 1.5;
}

/* 在读的书（宽卡：最多 3 本，横向排布，整项可点击） */
.current-book-row {
    display: flex;
    flex-wrap: wrap;
    gap: 10px 16px;
    margin-top: 10px;
}

.current-book-item {
    display: flex;
    gap: 10px;
    min-width: 0;
    flex: 1 1 calc(33% - 16px);
    text-decoration: none;
    cursor: pointer;
}

.current-book-cover {
    width: 48px;
    min-width: 48px;
    height: 72px;
    border-radius: 4px;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.22);
    flex: none;
}

.current-book-meta {
    min-width: 0;
    display: flex;
    flex-direction: column;
    justify-content: center;
}

.current-book-title {
    font-size: 13px;
    font-weight: 600;
    color: rgba(0, 0, 0, 0.87);
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    line-height: 1.4;
}

.dash-cards.is-dark .current-book-title {
    color: rgba(255, 255, 255, 0.92);
}

.current-book-author {
    font-size: 11px;
    color: rgba(0, 0, 0, 0.5);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    margin-top: 2px;
}

.dash-cards.is-dark .current-book-author {
    color: rgba(255, 255, 255, 0.55);
}

/* 即将读完 */
.near-finish-body {
    display: flex;
    align-items: center;
    gap: 14px;
    margin-top: 8px;
}

.ring {
    width: 64px;
    height: 64px;
    min-width: 64px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
}

.ring-inner {
    width: 48px;
    height: 48px;
    border-radius: 50%;
    background: #ffffff;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
}

.dash-cards.is-dark .ring-inner {
    background: rgba(0, 0, 0, 0.9);
}

.ring-number {
    font-size: 13px;
    font-weight: bold;
    color: rgba(0, 0, 0, 0.87);
    line-height: 1;
}

.dash-cards.is-dark .ring-number {
    color: rgba(255, 255, 255, 0.92);
}

.ring-label {
    font-size: 8px;
    color: rgba(0, 0, 0, 0.5);
    margin-top: 2px;
}

.dash-cards.is-dark .ring-label {
    color: rgba(255, 255, 255, 0.55);
}

.near-finish-list {
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 4px;
}

.near-finish-item {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 12px;
    line-height: 1.5;
}

.near-finish-title {
    color: rgba(0, 0, 0, 0.75);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    min-width: 0;
}

.dash-cards.is-dark .near-finish-title {
    color: rgba(255, 255, 255, 0.75);
}

.near-finish-percent {
    font-weight: 500;
    flex: none;
}

/* 近 7 天 / 近 30 天的底纹大数字（颜色跟主色，见模板内联样式） */
.ghost-number {
    position: absolute;
    right: 10px;
    bottom: -12px;
    font-size: 68px;
    font-weight: bold;
    line-height: 1;
    pointer-events: none;
}

/* 编辑模式 */
.dash-add-row {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    margin-top: 12px;
    padding: 8px 12px;
    border-radius: 10px;
    background: rgba(0, 0, 0, 0.04);
}

.dash-add-row.is-dark {
    background: rgba(255, 255, 255, 0.08);
}

.dash-add-label {
    font-size: 12px;
    color: rgba(0, 0, 0, 0.55);
    margin-right: 8px;
}

.dash-cards.is-dark .dash-add-label {
    color: rgba(255, 255, 255, 0.55);
}

/* 空状态卡 */
.empty-card {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    text-align: center;
    padding: 20px;
    margin-top: 12px;
    cursor: default;
}

.empty-kaomoji {
    font-size: 30px;
    color: rgba(0, 0, 0, 0.35);
    letter-spacing: 2px;
}

.dash-cards.is-dark .empty-kaomoji {
    color: rgba(255, 255, 255, 0.4);
}

.empty-title {
    font-size: 14px;
    font-weight: 500;
    color: rgba(0, 0, 0, 0.75);
    margin-top: 8px;
}

.dash-cards.is-dark .empty-title {
    color: rgba(255, 255, 255, 0.8);
}

.empty-sub {
    font-size: 12px;
    color: rgba(0, 0, 0, 0.45);
    margin-top: 4px;
}

.dash-cards.is-dark .empty-sub {
    color: rgba(255, 255, 255, 0.5);
}

/* ═══ 周/月/年/总 ═══ */
.dash-range {
    background: #ffffff;
    border: 1px solid rgba(0, 0, 0, 0.06);
    border-radius: 16px;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
    padding: 14px 16px;
    margin-bottom: 16px;
}

.dash-range.is-dark {
    background: rgba(0, 0, 0, 0.82);
    border-color: transparent;
}

.range-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 8px;
    margin-bottom: 12px;
}

.range-toggle {
    background: rgba(0, 0, 0, 0.04);
    border-radius: 20px;
}

.dash-range.is-dark .range-toggle {
    background: rgba(255, 255, 255, 0.08);
}

.range-nav {
    display: flex;
    align-items: center;
    gap: 4px;
}

.range-title {
    font-size: 14px;
    font-weight: 500;
    color: rgba(0, 0, 0, 0.75);
    min-width: 110px;
    text-align: center;
}

.dash-range.is-dark .range-title {
    color: rgba(255, 255, 255, 0.8);
}

.range-title-single {
    margin-right: 72px; /* 与左侧按钮对称 */
}

.chart-box {
    position: relative;
    height: 180px;
}

/* 月历需要按自身内容撑高 */
.chart-box.chart-box-auto {
    height: auto;
}

/* chart.js 量的是 canvas 包裹层的高度：包裹层 auto 时会退化成 400px 撑出容器，
   让它填满 chart-box 即可（非 !important，不影响 chart.js 自身的内联样式元素） */
.chart-box ::v-deep div:first-child {
    width: 100%;
    height: 100%;
}

.heatmap-scroll {
    overflow-x: auto;
    padding-bottom: 4px;
    height: 100%;
}

.heatmap-scroll-inner {
    height: 100%;
}

/* ═══ 折叠的阅读书目 ═══ */
.walls-section {
    margin-top: 8px;
}

.walls-toggle {
    display: flex;
    align-items: center;
    cursor: pointer;
    user-select: none;
    padding: 4px 0;
}

/* ═══ 原 4 张统计卡（保留在折叠区） ═══ */
.stats-card {
    border-radius: 16px;
    border: none;
    min-height: 120px;
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    box-shadow: 0 2px 8px rgba(0,0,0,0.1);
}

.stats-card:hover {
    transform: translateY(-4px);
    box-shadow: 0 8px 24px rgba(0,0,0,0.15);
}

.stat-number-badge {
    background: rgba(0,0,0,0.3);
    color: #ffffff;
    padding: 8px 16px;
    border-radius: 20px;
    font-weight: bold;
    font-size: 18px;
    min-width: 50px;
    text-align: center;
    box-shadow: inset 0 2px 4px rgba(0,0,0,0.2);
    display: inline-block;
}

.stat-label-text {
    color: white !important;
    font-weight: 500;
    font-size: 14px;
    padding-top: 8px;
}

.gradient-bg-primary {
    background: linear-gradient(135deg, #1976d2 0%, #42a5f5 100%);
}

.gradient-bg-success {
    background: linear-gradient(135deg, #388e3c 0%, #66bb6a 100%);
}

.gradient-bg-info {
    background: linear-gradient(135deg, #0288d1 0%, #29b6f6 100%);
}

.gradient-bg-orange {
    background: linear-gradient(135deg, #f57c00 0%, #ffb74d 100%);
}

.book-card {
    transition: transform 0.2s ease-in-out;
}

.book-card:hover {
    transform: scale(1.02);
}

.reading-chip {
    position: absolute;
    top: 8px;
    left: 8px;
    z-index: 1;
    box-shadow: 0 2px 4px rgba(0,0,0,0.3);
}

.done-chip {
    position: absolute;
    top: 8px;
    left: 8px;
    z-index: 1;
    box-shadow: 0 2px 4px rgba(0,0,0,0.3);
}

@media (max-width: 960px) {
    .dash-card,
    .dash-card.wide {
        flex: 1 1 calc(50% - 12px);
    }
}

@media (max-width: 480px) {
    .dash-card.wide {
        flex: 1 1 100%;
    }

    .dash-total {
        font-size: 28px;
    }
}
</style>
