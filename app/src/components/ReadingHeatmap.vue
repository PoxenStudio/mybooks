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
// 时长分级：阅读时长大多集中在 1 小时以内，所以 1 小时以内切了 4 档，保证低时长也能看出差异。
// 参照 GitHub 热力图的绿色调，但方向按需求反过来——阅读时长越长，颜色越亮越鲜艳。0 档（没有阅读）
// 颜色随主题切换，见 emptyColor。
const EMPTY_COLOR_LIGHT = '#F5F5F5';
const EMPTY_COLOR_DARK = '#151B23';

// 深色样式：最短档是深色卡片背景上仍能辨认的最不起眼的深绿，8 小时以上用最明亮的绿色，最扎眼。
// 两端锚点：最深 rgb(3,58,22)、最亮 rgb(86,211,100)，中间 6 档做线性插值。
const LEVEL_COLORS_DARK = [
    null, // 0：没有阅读，颜色随主题切换，见 emptyColor computed
    '#033a16', // 0~15 分钟
    '#0f5021', // 15~30 分钟
    '#1b662c', // 30~45 分钟
    '#277c37', // 45~60 分钟
    '#329143', // 1~2 小时
    '#3ea74e', // 2~4 小时
    '#4abd59', // 4~8 小时（更鲜艳的绿色）
    '#56d364', // 8 小时以上（最明亮的绿色）
];

// 浅色样式：在白色卡片背景上，深色系反而看不清，所以从浅绿色渐变到明亮的绿色。
// 两端锚点：最浅 rgb(200,245,208)、最亮 rgb(15,138,55)，中间 6 档做线性插值。
const LEVEL_COLORS_LIGHT = [
    null, // 0：没有阅读，颜色随主题切换，见 emptyColor computed
    '#c8f5d0', // 0~15 分钟
    '#a8ebb8', // 15~30 分钟
    '#87dfa0', // 30~45 分钟
    '#66d089', // 45~60 分钟
    '#48bf72', // 1~2 小时
    '#2fac5e', // 2~4 小时
    '#1c9a4c', // 4~8 小时
    '#0f8a37', // 8 小时以上（最明亮的绿色）
];

function levelForSeconds(seconds) {
    if (!seconds) return 0;
    const minutes = seconds / 60;
    if (minutes < 15) return 1;
    if (minutes < 30) return 2;
    if (minutes < 45) return 3;
    if (minutes < 60) return 4;
    const hours = seconds / 3600;
    if (hours < 2) return 5;
    if (hours < 4) return 6;
    if (hours < 8) return 7;
    return 8;
}

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
            if (level === 0) return this.emptyColor;
            const colors = this.$vuetify.theme.dark ? LEVEL_COLORS_DARK : LEVEL_COLORS_LIGHT;
            return colors[level];
        },
        monthLabel(dateStr) {
            const date = new Date(`${dateStr}T00:00:00`);
            return new Intl.DateTimeFormat(this.$i18n.locale || 'zh', { month: 'short' }).format(date);
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
