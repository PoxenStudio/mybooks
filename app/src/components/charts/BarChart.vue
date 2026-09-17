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
        chartData: {
            deep: true,
            handler() {
                this.renderChart(this.chartData, this.chartOptions);
            },
        },
        chartOptions: {
            deep: true,
            handler() {
                this.renderChart(this.chartData, this.chartOptions);
            },
        },
    },
    mounted() {
        this.renderChart(this.chartData, this.chartOptions);
    },
};
</script>
