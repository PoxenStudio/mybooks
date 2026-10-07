<template>
    <div class="month-calendar" :class="{ 'is-dark': $vuetify.theme.dark }">
        <div class="month-weekdays">
            <span v-for="label in weekdayLabels" :key="'wd-' + label" class="month-weekday">{{ label }}</span>
        </div>
        <div class="month-grid">
            <span v-for="n in leadingBlanks" :key="'blank-' + n" class="month-cell is-blank"></span>
            <v-tooltip v-for="day in fullDays" :key="day.date" top>
                <template #activator="{ on, attrs }">
                    <div
                        class="month-cell"
                        :class="{ 'is-today': isToday(day) }"
                        :style="cellStyle(day)"
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
// days 由父组件传入当月已有的逐日数据（到今天为止）；monthStart 为该月 1 号，
// 未到的日期没有数据，也按空格子渲染，保证网格是完整的一个月。
import { levelForSeconds, levelColor } from '~/utils/heatmapLevels';
import { intlLocale } from '~/utils/intlLocale';

export default {
    name: 'ReadingMonthCalendar',
    props: {
        // [{date: 'YYYY-MM-DD', reading_seconds: number}, ...]，从当月 1 号开始
        days: { type: Array, default: () => [] },
        // 该月 1 号（YYYY-MM-01）；为空时按 days 实际长度渲染
        monthStart: { type: String, default: '' },
    },
    computed: {
        isDark() {
            return this.$vuetify.theme.dark;
        },
        monthStartSafe() {
            if (this.monthStart) return this.monthStart;
            return this.days.length ? this.days[0].date.slice(0, 8) + '01' : '';
        },
        daysInMonth() {
            if (!this.monthStartSafe) return this.days.length;
            const [y, m] = this.monthStartSafe.split('-').map(Number);
            return new Date(y, m, 0).getDate();
        },
        // 完整月份的逐日格子：未来日期没有数据，按 0 秒空格子补齐
        fullDays() {
            if (!this.monthStartSafe) return this.days;
            const byDate = {};
            this.days.forEach((d) => {
                byDate[d.date] = d;
            });
            const [y, m] = this.monthStartSafe.split('-').map(Number);
            const result = [];
            for (let day = 1; day <= this.daysInMonth; day++) {
                const date = `${y}-${String(m).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
                result.push(byDate[date] || { date, reading_seconds: 0 });
            }
            return result;
        },
        weekdayLabels() {
            const fmt = new Intl.DateTimeFormat(intlLocale(this.$i18n.locale), { weekday: 'short' });
            // 2023-10-02 是周一，取 7 天的短星期名，保证一~日的顺序
            return Array.from({ length: 7 }, (_v, i) => fmt.format(new Date(2023, 9, 2 + i)));
        },
        leadingBlanks() {
            if (!this.monthStartSafe) return 0;
            const first = new Date(`${this.monthStartSafe}T00:00:00`);
            return (first.getDay() + 6) % 7; // getDay(): 周日=0 → 周一=0 的偏移
        },
        // 本地时区的今天；阅读桶按 UTC 日期存，深夜/清晨与桶日期可能差一天，标记仅作视觉参考
        todayStr() {
            const d = new Date();
            const m = String(d.getMonth() + 1).padStart(2, '0');
            const day = String(d.getDate()).padStart(2, '0');
            return `${d.getFullYear()}-${m}-${day}`;
        },
        primaryColor() {
            const theme = (this.$vuetify && this.$vuetify.theme && this.$vuetify.theme.currentTheme) || {};
            return theme.primary || '#1976d2';
        },
    },
    methods: {
        dayNumber(day) {
            return parseInt(day.date.slice(8), 10);
        },
        isToday(day) {
            return day.date === this.todayStr;
        },
        cellStyle(day) {
            const style = { background: this.cellColor(day) };
            if (this.isToday(day)) {
                style.boxShadow = `inset 0 0 0 2px ${this.primaryColor}`;
            }
            return style;
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

/* 今天：主色描边 + 数字加粗（描边颜色走模板内联样式跟站点主色） */
.month-cell.is-today {
    font-weight: bold;
}
</style>
