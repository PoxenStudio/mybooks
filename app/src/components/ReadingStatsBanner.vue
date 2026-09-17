<template>
    <v-row v-if="stats" class="reading-stats-banner">
        <v-col cols=12>
            <div class="d-flex align-center mb-2" v-if="showTitle">
                <p class="ma-0 title">{{ $t('index.readingStats.title') }}</p>
            </div>
            <div class="reading-stats-cards">
                <!-- 总阅读时长 -->
                <div class="stats-card total-hours-card">
                    <div class="stats-card-label">{{ $t('index.readingStats.totalReadingHours') }}</div>
                    <div class="stats-card-body total-hours-body">
                        <div class="total-hours-circle">
                            <span class="total-hours-number">
                                <span class="total-hours-int">{{ totalHours.intPart }}</span><span class="total-hours-frac">.{{ totalHours.fracPart }}</span>
                            </span>
                            <span class="total-hours-unit">{{ $t('index.readingStats.hoursUnit') }}</span>
                        </div>
                    </div>
                </div>

                <!-- 下载 / 推送汇总 -->
                <div class="stats-card">
                    <div class="stats-card-label">{{ $t('index.readingStats.downloadAndPush') }}</div>
                    <div class="stats-card-body chart-body">
                        <bar-chart :chart-data="totalsBarData" :chart-options="barOptions" :styles="chartCanvasStyle" />
                    </div>
                </div>

                <!-- 阅读热力图（近13周） -->
                <div class="stats-card wide">
                    <div class="stats-card-label">{{ $t('index.readingStats.readingHeatmap') }}</div>
                    <div class="stats-card-body">
                        <reading-heatmap :days="heatmapDays" compact />
                    </div>
                </div>

                <!-- 近8周下载与推送 -->
                <div class="stats-card wide">
                    <div class="stats-card-label">{{ $t('index.readingStats.weeklyDownloadAndPush') }}</div>
                    <div class="stats-card-body chart-body">
                        <line-chart :chart-data="weeklyEventsData" :chart-options="lineOptions" :styles="chartCanvasStyle" />
                    </div>
                </div>

                <!-- 书籍状态分布 -->
                <div class="stats-card">
                    <div class="stats-card-label">{{ $t('index.readingStats.bookStatus') }}</div>
                    <div class="stats-card-body chart-body">
                        <doughnut-chart :chart-data="bookStatusData" :chart-options="bookStatusOptions" :styles="chartCanvasStyle" />
                    </div>
                </div>
            </div>
        </v-col>
    </v-row>
</template>

<script>
import BarChart from '~/components/charts/BarChart.vue';
import LineChart from '~/components/charts/LineChart.vue';
import DoughnutChart from '~/components/charts/DoughnutChart.vue';
import ReadingHeatmap from '~/components/ReadingHeatmap.vue';

export default {
    name: 'ReadingStatsBanner',
    components: { BarChart, LineChart, DoughnutChart, ReadingHeatmap },
    props: {
        uid: { type: [Number, String], default: null },
        showTitle: { type: Boolean, default: true },
    },
    data: () => ({
        stats: null,
    }),
    computed: {
        chartCanvasStyle() {
            return { position: 'relative', width: '100%', height: '100%' };
        },
        isDark() {
            return this.$vuetify.theme.dark;
        },
        chartTickColor() {
            return this.isDark ? '#eee' : '#333';
        },
        chartGridColor() {
            return this.isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.1)';
        },
        isLoggedIn() {
            return !!(this.$store.state.user && this.$store.state.user.is_login);
        },
        totalHours() {
            const hours = ((this.stats && this.stats.totals.total_reading_seconds) || 0) / 3600;
            const rounded = Math.round(hours * 100) / 100;
            const [intPart, fracPart] = rounded.toFixed(2).split('.');
            return { intPart, fracPart };
        },
        totalsBarData() {
            const totals = (this.stats && this.stats.totals) || { download_count: 0, push_count: 0 };
            return {
                labels: [this.$t('index.readingStats.downloads'), this.$t('index.readingStats.pushes')],
                datasets: [{
                    data: [totals.download_count, totals.push_count],
                    backgroundColor: ['rgba(33,150,243,0.75)', 'rgba(76,175,80,0.75)'],
                    borderRadius: 6,
                }],
            };
        },
        weekly() {
            return (this.stats && this.stats.weekly) || [];
        },
        weekLabels() {
            return this.weekly.map((w) => w.week_start.slice(5));
        },
        heatmapDays() {
            return (this.stats && this.stats.heatmap && this.stats.heatmap.days) || [];
        },
        weeklyEventsData() {
            return {
                labels: this.weekLabels,
                datasets: [
                    {
                        label: this.$t('index.readingStats.downloads'),
                        data: this.weekly.map((w) => w.download_count),
                        borderColor: 'rgba(33,150,243,0.9)',
                        backgroundColor: 'rgba(33,150,243,0.2)',
                        tension: 0.3,
                    },
                    {
                        label: this.$t('index.readingStats.pushes'),
                        data: this.weekly.map((w) => w.push_count),
                        borderColor: 'rgba(76,175,80,0.9)',
                        backgroundColor: 'rgba(76,175,80,0.2)',
                        tension: 0.3,
                    },
                ],
            };
        },
        bookStatus() {
            return (this.stats && this.stats.book_status) || { reading: 0, to_read: 0, finished: 0 };
        },
        bookStatusData() {
            const s = this.bookStatus;
            return {
                labels: [
                    `${this.$t('index.readingStats.reading')} (${s.reading})`,
                    `${this.$t('index.readingStats.toRead')} (${s.to_read})`,
                    `${this.$t('index.readingStats.finished')} (${s.finished})`,
                ],
                datasets: [{
                    data: [s.reading, s.to_read, s.finished],
                    backgroundColor: ['rgba(255,152,0,0.85)', 'rgba(158,158,158,0.85)', 'rgba(76,175,80,0.85)'],
                }],
            };
        },
        barOptions() {
            return {
                maintainAspectRatio: false,
                responsive: true,
                plugins: { legend: { display: false } },
                scales: {
                    x: { ticks: { color: this.chartTickColor, font: { size: 10 } }, grid: { display: false } },
                    y: { beginAtZero: true, ticks: { color: this.chartTickColor, font: { size: 10 }, precision: 0, stepSize: 1 }, grid: { color: this.chartGridColor } },
                },
            };
        },
        lineOptions() {
            return {
                maintainAspectRatio: false,
                responsive: true,
                plugins: { legend: { display: true, position: 'left', labels: { color: this.chartTickColor, boxWidth: 10, font: { size: 10 } } } },
                scales: {
                    x: { ticks: { color: this.chartTickColor, font: { size: 10 } }, grid: { display: false } },
                    y: { beginAtZero: true, ticks: { color: this.chartTickColor, font: { size: 10 }, precision: 0, stepSize: 1 }, grid: { color: this.chartGridColor } },
                },
            };
        },
        bookStatusOptions() {
            return {
                maintainAspectRatio: false,
                responsive: true,
                plugins: { legend: { display: true, position: 'right', labels: { color: this.chartTickColor, boxWidth: 10, font: { size: 10 } } } },
            };
        },
    },
    methods: {
        async loadStats() {
            if (!this.isLoggedIn) {
                this.stats = null;
                this.$emit('has-stats', false);
                return;
            }
            try {
                const url = this.uid ? `/user/reading_stats?uid=${encodeURIComponent(this.uid)}` : '/user/reading_stats';
                const rsp = await this.$backend(url);
                if (rsp.err === 'ok' && rsp.enabled) {
                    this.stats = rsp;
                    this.$emit('has-stats', true);
                } else {
                    this.stats = null;
                    this.$emit('has-stats', false);
                }
            } catch (error) {
                console.warn('Failed to load reading stats:', error);
                this.stats = null;
                this.$emit('has-stats', false);
            }
        },
    },
    watch: {
        isLoggedIn(loggedIn) {
            if (loggedIn) {
                this.loadStats();
            }
        },
    },
    mounted() {
        this.loadStats();
    },
};
</script>

<style scoped>
.reading-stats-banner {
    margin-top: 8px;
    margin-bottom: 16px;
}

.reading-stats-cards {
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
}

.stats-card {
    flex: 1 1 155px;
    min-width: 0;
    height: 150px;
    background: rgba(255, 255, 255, 0.9);
    border: 1px solid rgba(0, 0, 0, 0.08);
    border-radius: 16px;
    padding: 8px 12px;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
    display: flex;
    flex-direction: column;
    overflow: hidden;
}

.theme--dark .stats-card {
    background: rgba(0, 0, 0, 0.82);
    border-color: transparent;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
}

.stats-card.wide {
    flex: 2 1 250px;
}

.total-hours-card {
    flex: 1 1 120px;
    max-width: 140px;
    padding-left: 4px;
    padding-right: 4px;
}

.stats-card-label {
    color: rgba(0, 0, 0, 0.65);
    font-size: 12px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.theme--dark .stats-card-label {
    color: rgba(255, 255, 255, 0.85);
}

.stats-card-body {
    flex: 1;
    min-height: 0;
    position: relative;
}

.chart-body {
    padding-top: 4px;
}

.total-hours-body {
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 3px;
    container-type: size;
}

.total-hours-circle {
    width: min(100cqw, 100cqh);
    height: min(100cqw, 100cqh);
    border-radius: 50%;
    background: rgba(33, 150, 243, 0.18);
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    color: rgba(0, 0, 0, 0.87);
}

.theme--dark .total-hours-circle {
    background: rgba(33, 150, 243, 0.28);
    color: #ffffff;
}

.total-hours-number {
    line-height: 1;
}

.total-hours-int {
    font-size: 20px;
    font-weight: bold;
}

.total-hours-frac {
    font-size: 14px;
    font-weight: bold;
}

.total-hours-unit {
    font-size: 11px;
    margin-top: 2px;
    color: rgba(0, 0, 0, 0.6);
}

.theme--dark .total-hours-unit {
    color: rgba(255, 255, 255, 0.85);
}

@media (max-width: 600px) {
    .stats-card, .stats-card.wide {
        flex: 1 1 100%;
        max-width: 100%;
    }
}
</style>
