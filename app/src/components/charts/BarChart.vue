<script>
// vue-chartjs@3.x (Vue2 + Chart.js 3) requires extending the base component
// and calling renderChart() manually — the declarative chart-data/chart-options
// props only exist in vue-chartjs@4 (Vue3). Keep this wrapper thin and reusable.
import { Bar } from 'vue-chartjs';

export default {
    extends: Bar,
    props: {
        chartData: { type: Object, required: true },
        chartOptions: { type: Object, default: () => ({}) },
    },
    watch: {
        // 不能 deep：Chart.js 渲染时会改写传入的 data/options（这里已被 Vue 观测），
        // deep watch 会被自己的渲染反复触发，形成更新死循环。父组件每次都传新对象，监听引用即可。
        chartData() {
            this.renderChart(this.chartData, this.chartOptions);
        },
        chartOptions() {
            this.renderChart(this.chartData, this.chartOptions);
        },
    },
    mounted() {
        this.renderChart(this.chartData, this.chartOptions);
    },
};
</script>
