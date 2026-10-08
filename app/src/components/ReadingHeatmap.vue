<template>
    <div
        class="heatmap-inner"
        :class="{ 'is-dark': $vuetify.theme.dark }"
        :style="{
            gridTemplateColumns: `repeat(${weeksGrid.length}, 1fr)`,
            gridTemplateRows: `${monthRowSize}px repeat(7, 1fr)`,
        }"
    >
        <span
            v-for="marker in monthMarkers"
            :key="'m' + marker.col"
            class="heatmap-month-label"
            :style="{ gridColumnStart: marker.col + 1, fontSize: labelFontSize }"
        >{{ marker.label }}</span>

        <template v-for="(week, wi) in weeksGrid">
            <v-tooltip v-for="(day, di) in week" :key="`${wi}-${di}`" top :disabled="!day">
                <template #activator="{ on, attrs }">
                    <div
                        class="heatmap-cell"
                        :style="{
                            background: day ? levelColor(levelForSeconds(day.reading_seconds)) : emptyColor,
                            gridColumnStart: wi + 1,
                            gridRowStart: di + 2,
                        }"
                        v-bind="attrs"
                        v-on="day ? on : {}"
                    ></div>
                </template>
                <span v-if="day">{{ day.date }} · {{ formatDuration(day.reading_seconds) }}</span>
            </v-tooltip>
        </template>
    </div>
</template>

<script>
// 时长分级与配色已提取到 utils/heatmapLevels.js（与阅读记录页的月历视图共用）
import { EMPTY_COLOR_DARK, EMPTY_COLOR_LIGHT, levelForSeconds, levelColor } from '~/utils/heatmapLevels';
import { intlLocale } from '~/utils/intlLocale';

export default {
    name: 'ReadingHeatmap',
    props: {
        // 逐日数据，[{date: 'YYYY-MM-DD', reading_seconds: number}, ...]，从最早到今天，
        // 由调用方直接从 /user/reading_stats 的 heatmap.days 传入。
        days: { type: Array, default: () => [] },
        compact: { type: Boolean, default: false },
    },
    computed: {
        monthRowSize() {
            return this.compact ? 10 : 14;
        },
        labelFontSize() {
            return this.compact ? '9px' : '11px';
        },
        emptyColor() {
            return this.$vuetify.theme.dark ? EMPTY_COLOR_DARK : EMPTY_COLOR_LIGHT;
        },
        // 按周一起点，把逐日数据切成每 7 天一列；最后一周（本周）不足 7 天时用 null 补齐末尾格子。
        weeksGrid() {
            const weeks = [];
            for (let i = 0; i < this.days.length; i += 7) {
                const week = this.days.slice(i, i + 7);
                while (week.length < 7) week.push(null);
                weeks.push(week);
            }
            return weeks;
        },
        // 每当某一周的第一个有效日期进入新的月份，就在该列标注月份缩写。
        monthMarkers() {
            const markers = [];
            let lastMonth = null;
            this.weeksGrid.forEach((week, col) => {
                const firstDay = week.find((d) => d);
                if (!firstDay) return;
                const month = firstDay.date.slice(0, 7);
                if (month !== lastMonth) {
                    markers.push({ col, label: this.monthLabel(firstDay.date) });
                    lastMonth = month;
                }
            });
            return markers;
        },
    },
    methods: {
        levelForSeconds,
        levelColor(level) {
            return levelColor(level, this.$vuetify.theme.dark);
        },
        monthLabel(dateStr) {
            const date = new Date(`${dateStr}T00:00:00`);
            return new Intl.DateTimeFormat(intlLocale(this.$i18n.locale), { month: 'short' }).format(date);
        },
        // 与书籍详情页阅读时长的展示格式保持一致
        formatDuration(totalSeconds) {
            const seconds = totalSeconds || 0;
            const hours = Math.floor(seconds / 3600);
            const minutes = Math.floor((seconds % 3600) / 60);
            if (hours <= 0) {
                return this.$t('book.readingStats.durationMinutes', { minutes });
            }
            return this.$t('book.readingStats.durationHoursMinutes', { hours, minutes });
        },
    },
};
</script>

<style scoped>
.heatmap-inner {
    display: grid;
    grid-auto-flow: column;
    gap: 3px;
    width: 100%;
    height: 100%;
}

.heatmap-cell {
    width: 100%;
    height: 100%;
    border-radius: 2px;
}

.heatmap-month-label {
    grid-row: 1;
    color: rgba(0, 0, 0, 0.6);
    white-space: nowrap;
    line-height: 1;
}

.heatmap-inner.is-dark .heatmap-month-label {
    color: rgba(255, 255, 255, 0.7);
}
</style>
