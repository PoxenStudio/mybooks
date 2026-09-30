<template>
    <AppDialog
        :value="true"
        type="progress"
        :title="titleText"
        :max-width="640"
        hide-footer-button
    >
        <div class="startup-spinner">
            <span
                v-for="i in shades.length"
                :key="i"
                class="startup-cell"
                :style="{ backgroundColor: shades[(i - 1 - offset + shades.length) % shades.length] }"
            ></span>
        </div>
        <div class="startup-task">{{ taskText }}</div>
        <div v-if="stepIndex > 0" class="text-center grey--text mt-2">
            {{ $t('starting.stepProgress', { index: stepIndex, total: steps.length }) }}
        </div>
    </AppDialog>
</template>

<script>
const POLL_INTERVAL = 1500;
const SPIN_INTERVAL = 100;

export default {
    data: () => ({
        shades: ["#E3F2FD", "#BBDEFB", "#90CAF9", "#64B5F6", "#42A5F5", "#2196F3", "#1E88E5", "#1976D2", "#1565C0", "#0D47A1"],
        offset: 0,
        steps: [],
        current: "",
        upgrading: false,
        seenStarting: false,
        finished: false,
        spinTimer: null,
        pollTimer: null,
    }),
    asyncData({ store }) {
        store.commit("navbar", false);
    },
    head() {
        return { title: this.titleText };
    },
    computed: {
        stepIndex() {
            return this.steps.findIndex((s) => s.name === this.current) + 1;
        },
        titleText() {
            return this.upgrading ? this.$t("starting.upgradeTitle") : this.$t("starting.title");
        },
        taskText() {
            if (this.finished) return this.$t("starting.finished");
            if (this.current) return this.$t("starting.steps." + this.current);
            return this.$t("starting.waiting");
        },
    },
    created() {
        this.$store.commit("navbar", false);
    },
    mounted() {
        this.spinTimer = setInterval(() => {
            this.offset = (this.offset + 1) % this.shades.length;
        }, SPIN_INTERVAL);
        this.poll();
    },
    beforeDestroy() {
        clearInterval(this.spinTimer);
        clearTimeout(this.pollTimer);
    },
    methods: {
        poll() {
            fetch(window.location.origin + "/api/startup/status", { credentials: "include", cache: "no-store" })
                .then((rsp) => (rsp.ok ? rsp.json() : null))
                .then((rsp) => {
                    if (rsp && rsp.err === "server_starting") {
                        this.seenStarting = true;
                        this.steps = rsp.steps || [];
                        this.current = rsp.current || "";
                        this.upgrading = !!rsp.upgrading;
                    } else if (rsp && rsp.err === "ok" && !rsp.starting) {
                        this.leave();
                        return;
                    } else {
                        this.seenStarting = true;
                        this.current = "";
                        this.upgrading = false;
                    }
                    this.schedule();
                })
                .catch(() => {
                    this.seenStarting = true;
                    this.current = "";
                    this.upgrading = false;
                    this.schedule();
                });
        },
        schedule() {
            this.pollTimer = setTimeout(this.poll, POLL_INTERVAL);
        },
        leave() {
            this.finished = true;
            const next = this.$route.query.next;
            const target = typeof next === "string" && next.startsWith("/") && !next.startsWith("//") ? next : "/";
            setTimeout(() => {
                this.$store.commit("navbar", true);
                window.location.replace(target);
            }, this.seenStarting ? 800 : 0);
        },
    },
};
</script>

<style scoped>
.startup-spinner {
    display: flex;
    justify-content: center;
    gap: 6px;
    padding: 16px 0 24px;
}
.startup-cell {
    width: 20px;
    height: 20px;
    border-radius: 3px;
    transition: background-color 0.1s linear;
}
.startup-task {
    font-size: 28px;
    line-height: 1.4;
    text-align: center;
}
</style>
