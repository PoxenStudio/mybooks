<script>
import { Doughnut } from 'vue-chartjs';

export default {
    extends: Doughnut,
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
