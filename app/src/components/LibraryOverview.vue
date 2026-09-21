<template>
    <div class="lib-overview" :class="{ 'is-dark': isDark }">
        <!-- 空间占用 -->
        <div class="ov-size">
            <v-icon small class="mr-1">mdi-database-outline</v-icon>
            <span class="ov-label">{{ $t('index.detailLibSize') }}:</span>
            <v-progress-circular v-if="size.loading" indeterminate size="14" width="2" class="ml-2" />
            <span v-else class="ov-size-value">{{ sizeText }}</span>
        </div>

        <div class="ov-cards">
            <!-- 每月入库 -->
            <div class="ov-card ov-monthly">
                <div class="ov-card-title">{{ $t('index.detailMonthlyTitle') }}</div>
                <div class="ov-card-body">
                    <div v-if="monthly.loading" class="ov-center"><v-progress-circular indeterminate size="24" width="2" /></div>
                    <div v-else-if="!monthly.data.length" class="ov-center ov-empty">{{ $t('index.detailNoData') }}</div>
                    <line-chart v-else :chart-data="monthlyData" :chart-options="lineOptions" :styles="canvasStyle" />
                </div>
            </div>

            <!-- 分类饼图 -->
            <div class="ov-card ov-category">
                <div class="ov-card-title">{{ $t('index.detailCategoryDist') }}</div>
                <div class="ov-card-body">
                    <div v-if="category.loading" class="ov-center"><v-progress-circular indeterminate size="24" width="2" /></div>
                    <div v-else-if="!categoryData.labels.length" class="ov-center ov-empty">{{ $t('index.detailNoData') }}</div>
                    <pie-chart v-else :chart-data="categoryData" :chart-options="pieOptions" :styles="canvasStyle" />
                </div>
            </div>

            <!-- 标签 Top 50 -->
            <div class="ov-card ov-tags">
                <div class="ov-card-title">{{ $t('index.detailTagsTop') }}</div>
                <div class="ov-card-body">
                    <div v-if="tags.loading" class="ov-center"><v-progress-circular indeterminate size="24" width="2" /></div>
                    <div v-else-if="!tags.data.length" class="ov-center ov-empty">{{ $t('index.detailNoData') }}</div>
                    <div v-else class="ov-tags-scroll">
                        <div :style="{ minWidth: Math.max(tags.data.length * 22, 300) + 'px', height: '100%' }">
                            <bar-chart :chart-data="tagsData" :chart-options="barOptions" :styles="canvasStyle" />
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
</template>

<script>
import BarChart from '~/components/charts/BarChart.vue';
import LineChart from '~/components/charts/LineChart.vue';
import PieChart from '~/components/charts/PieChart.vue';

const PALETTE = [
    '#2196f3', '#4caf50', '#ff9800', '#e91e63', '#9c27b0', '#00bcd4', '#795548', '#607d8b',
    '#cddc39', '#f44336', '#3f51b5', '#009688',
];

export default {
    name: 'LibraryOverview',
    components: { BarChart, LineChart, PieChart },
    props: {
        allowPhysicalBooks: { type: Boolean, default: false },
    },
    data: () => ({
        size: { loading: true, data: 0 },
        monthly: { loading: true, data: [] },
        tags: { loading: true, data: [] },
        category: { loading: true, data: { items: [], uncategorized: 0 } },
    }),
    computed: {
        isDark() {
            return this.$vuetify.theme.dark;
        },
        tickColor() {
            return this.isDark ? '#eee' : '#333';
        },
        gridColor() {
            return this.isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.1)';
        },
        canvasStyle() {
            return { position: 'relative', width: '100%', height: '100%' };
        },
        sizeText() {
            const mb = this.size.data / 1024 / 1024;
            return mb >= 1024 ? `${(mb / 1024).toFixed(2)} GB` : `${mb.toFixed(1)} MB`;
        },
        monthlyData() {
            const rows = this.monthly.data.slice(0, 24).reverse();
            const datasets = [{
                label: this.$t('index.ebookCount'),
                data: rows.map((r) => r.ebook),
                borderColor: 'rgba(33,150,243,0.9)',
                backgroundColor: 'rgba(33,150,243,0.2)',
                tension: 0.3,
                fill: true,
                pointRadius: 2,
            }];
            if (this.allowPhysicalBooks) {
                datasets.push({
                    label: this.$t('index.physicalCount'),
                    data: rows.map((r) => r.physical),
                    borderColor: 'rgba(255,152,0,0.9)',
                    backgroundColor: 'rgba(255,152,0,0.2)',
                    tension: 0.3,
                    fill: true,
                    pointRadius: 2,
                });
            }
            return { labels: rows.map((r) => r.month), datasets };
        },
        lineOptions() {
            return {
                maintainAspectRatio: false,
                responsive: true,
                plugins: { legend: { display: this.allowPhysicalBooks, position: 'top', labels: { color: this.tickColor, boxWidth: 10, font: { size: 10 } } } },
                scales: {
                    x: { ticks: { color: this.tickColor, font: { size: 10 }, maxRotation: 60, autoSkip: true }, grid: { display: false } },
                    y: { beginAtZero: true, ticks: { color: this.tickColor, font: { size: 10 }, precision: 0 }, grid: { color: this.gridColor } },
                },
            };
        },
        tagsData() {
            return {
                labels: this.tags.data.map((t) => t.name),
                datasets: [{ data: this.tags.data.map((t) => t.count), backgroundColor: 'rgba(33,150,243,0.75)', borderRadius: 3 }],
            };
        },
        categoryData() {
            const items = this.category.data.items.map((i) => ({ name: i.name, count: i.count }));
            if (this.category.data.uncategorized > 0) {
                items.push({ name: this.$t('index.detailUncategorized'), count: this.category.data.uncategorized });
            }
            return {
                labels: items.map((i) => `${i.name} (${i.count})`),
                datasets: [{
                    data: items.map((i) => i.count),
                    backgroundColor: items.map((_i, idx) => (idx === items.length - 1 && this.category.data.uncategorized > 0 ? '#9e9e9e' : PALETTE[idx % PALETTE.length])),
                    borderWidth: 1,
                }],
            };
        },
        barOptions() {
            return {
                maintainAspectRatio: false,
                responsive: true,
                plugins: { legend: { display: false } },
                scales: {
                    x: { ticks: { color: this.tickColor, font: { size: 10 }, autoSkip: false, maxRotation: 90, minRotation: 60 }, grid: { display: false } },
                    y: { beginAtZero: true, ticks: { color: this.tickColor, font: { size: 10 }, precision: 0 }, grid: { color: this.gridColor } },
                },
            };
        },
        pieOptions() {
            return {
                maintainAspectRatio: false,
                responsive: true,
                plugins: { legend: { display: true, position: 'right', labels: { color: this.tickColor, boxWidth: 10, font: { size: 10 } } } },
            };
        },
    },
    mounted() {
        this.load('size', this.size);
        this.load('monthly', this.monthly);
        this.load('tags', this.tags);
        this.load('categories', this.category);
    },
    methods: {
        async load(kind, target) {
            try {
                const rsp = await this.$backend(`/library/stats/${kind}`);
                if (rsp.err === 'ok') {
                    target.data = rsp.data;
                }
            } catch (error) {
                console.warn(`Failed to load library stats ${kind}:`, error);
            } finally {
                target.loading = false;
            }
        },
    },
};
</script>

<style scoped>
.lib-overview {
    margin: 8px 0 12px;
}

.ov-size {
    display: flex;
    align-items: center;
    font-size: 13px;
    margin-bottom: 8px;
    color: rgba(0, 0, 0, 0.65);
}

.lib-overview.is-dark .ov-size {
    color: rgba(255, 255, 255, 0.75);
}

.ov-size-value {
    margin-left: 8px;
    font-weight: bold;
    padding: 2px 10px;
    border-radius: 12px;
    background: rgba(85, 101, 95, 0.15);
}

.ov-cards {
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
}

.ov-card {
    flex: 1 1 240px;
    min-width: 0;
    height: 230px;
    background: rgba(255, 255, 255, 0.9);
    border: 1px solid rgba(0, 0, 0, 0.08);
    border-radius: 16px;
    padding: 8px 12px;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
    display: flex;
    flex-direction: column;
    overflow: hidden;
}

.lib-overview.is-dark .ov-card {
    background: rgba(0, 0, 0, 0.82);
    border-color: transparent;
}

.ov-tags {
    flex: 3 1 100%;
}

.ov-monthly {
    flex: 2 1 300px;
}

.ov-category {
    flex: 2 1 300px;
}

.ov-card-title {
    font-size: 12px;
    color: rgba(0, 0, 0, 0.65);
    margin-bottom: 4px;
}

.lib-overview.is-dark .ov-card-title {
    color: rgba(255, 255, 255, 0.7);
}

.ov-card-body {
    flex: 1;
    min-height: 0;
    position: relative;
}

.ov-center {
    height: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
}

.ov-empty {
    font-size: 12px;
    opacity: 0.6;
}

.ov-tags-scroll {
    height: 100%;
    overflow-x: auto;
    overflow-y: hidden;
}
</style>
