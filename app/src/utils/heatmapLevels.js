// 阅读时长 → 热力格子颜色分级。ReadingHeatmap（周/年/总视图）与 ReadingMonthCalendar
// （月视图）共用，保证同一时长在不同视图里颜色一致。
//
// 时长大多集中在 1 小时以内，所以 1 小时以内切了 4 档，保证低时长也能看出差异。
// 参照 GitHub 热力图的绿色调，但方向反过来——阅读时长越长，颜色越亮越鲜艳。
// 0 档（没有阅读）颜色随主题切换，见 emptyColor()。
const EMPTY_COLOR_LIGHT = '#F5F5F5';
const EMPTY_COLOR_DARK = '#151B23';

// 深色样式：最短档是深色卡片背景上仍能辨认的最不起眼的深绿，8 小时以上用最明亮的绿色，最扎眼。
// 两端锚点：最深 rgb(3,58,22)、最亮 rgb(86,211,100)，中间 6 档做线性插值。
const LEVEL_COLORS_DARK = [
    null, // 0：没有阅读，颜色随主题切换，见 emptyColor()
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
    null, // 0：没有阅读，颜色随主题切换，见 emptyColor()
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

function levelColor(level, isDark) {
    if (level === 0) return isDark ? EMPTY_COLOR_DARK : EMPTY_COLOR_LIGHT;
    const colors = isDark ? LEVEL_COLORS_DARK : LEVEL_COLORS_LIGHT;
    return colors[level];
}

export { EMPTY_COLOR_LIGHT, EMPTY_COLOR_DARK, LEVEL_COLORS_DARK, LEVEL_COLORS_LIGHT, levelForSeconds, levelColor };
