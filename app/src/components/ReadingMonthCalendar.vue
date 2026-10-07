<template>
    <div class="month-calendar" :class="{ 'is-dark': $vuetify.theme.dark }">
        <div class="month-weekdays">
            <span v-for="label in weekdayLabels" :key="'wd-' + label" class="month-weekday">{{ label }}</span>
        </div>
        <div class="month-grid">
            <span v-for="n in leadingBlanks" :key="'blank-' + n" class="month-cell is-blank"></span>
            <v-tooltip v-for="day in days" :key="day.date" top>
                <template #activator="{ on, attrs }">
                    <div
                        class="month-cell"
                        :style="{ background: cellColor(day) }"
                        v-bind="attrs"
                        v-on="day.reading_seconds ? on : {}"
                    >{{ dayNumber(day) }}</div>
                </template>
                <span>{{ day.date }} · {{ formatDuration(day.reading_seconds) }}</span>
            </v-tooltip>
        </div>
    </div>
</template>

<script>
// 阅读记录仪表盘「月」视图：单月日历格，颜色分级与热力图共用一套 util。
// days 由父组件传入 [本月1号 ... 本月末(或今天)] 的逐日数据；月末尚未到来的日子不渲染。
import { levelForSeconds, levelColor } from '~/utils/heatmapLevels';
import { intlLocale } from '~/utils/intlLocale';

export default {
    name: 'ReadingMonthCalendar',
    props: {
        // [{date: 'YYYY-MM-DD', reading_seconds: number}, ...]，从当月 1 号开始
        days: { type: Array, default: () => [] },
    },
    computed: {
        isDark() {
            return this.$vuetify.theme.dark;
        },
        weekdayLabels() {
            const fmt = new Intl.DateTimeFormat(intlLocale(this.$i18n.locale), { weekday: 'short' });
            // 2023-10-02 是周一，取 7 天的短星期名，保证一~日的顺序
            return Array.from({ length: 7 }, (_v, i) => fmt.format(new Date(2023, 9, 2 + i)));
        },
        leadingBlanks() {
            if (!this.days.length) return 0;
            const first = new Date(`${this.days[0].date}T00:00:00`);
            return (first.getDay() + 6) % 7; // getDay(): 周日=0 → 周一=0 的偏移
        },
    },
    methods: {
        dayNumber(day) {
            return parseInt(day.date.slice(8), 10);
        },
        cellColor(day) {
            return levelColor(levelForSeconds(day.reading_seconds), this.isDark);
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
    },
};
</script>

<style scoped>
.month-calendar {
    width: 100%;
    max-width: 420px;
    margin: 0 auto;
}

.month-weekdays {
    display: grid;
    grid-template-columns: repeat(7, 1fr);
    gap: 4px;
    margin-bottom: 4px;
}

.month-weekday {
    text-align: center;
    font-size: 11px;
    color: rgba(0, 0, 0, 0.55);
}

.month-calendar.is-dark .month-weekday {
    color: rgba(255, 255, 255, 0.65);
}

.month-grid {
    display: grid;
    grid-template-columns: repeat(7, 1fr);
    gap: 4px;
}

.month-cell {
    aspect-ratio: 1 / 1;
    border-radius: 4px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 11px;
    color: rgba(0, 0, 0, 0.65);
    min-height: 28px;
}

.month-calendar.is-dark .month-cell {
    color: rgba(255, 255, 255, 0.75);
}

.month-cell.is-blank {
    background: transparent;
}
</style>
