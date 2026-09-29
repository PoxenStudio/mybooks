<template>
    <AppDialog
        :value="true"
        type="progress"
        :title="$t('upgrading.title')"
        :max-width="640"
        hide-footer-button
    >
        <div class="upgrade-spinner">
            <span
                v-for="i in shades.length"
                :key="i"
                class="upgrade-cell"
                :style="{ backgroundColor: shades[(i - 1 + offset) % shades.length] }"
            ></span>
        </div>
        <div class="upgrade-task">{{ taskText }}</div>
        <div v-if="stepIndex > 0" class="text-center grey--text mt-2">
            {{ $t('upgrading.stepProgress', { index: stepIndex, total: steps.length }) }}
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
        seenUpgrade: false,
        finished: false,
        spinTimer: null,
        pollTimer: null,
    }),
    asyncData({ store }) {
        store.commit("navbar", false);
    },
    head() {
        return { title: this.$t("upgrading.title") };
    },
    computed: {
        stepIndex() {
            return this.steps.findIndex((s) => s.name === this.current) + 1;
        },
        taskText() {
            if (this.finished) return this.$t("upgrading.finished");
            if (this.current) return this.$t("upgrading.steps." + this.current);
            return this.$t("upgrading.waiting");
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
            fetch(window.location.origin + "/api/upgrade/status", { credentials: "include", cache: "no-store" })
                .then((rsp) => (rsp.ok ? rsp.json() : null))
                .then((rsp) => {
                    if (rsp && rsp.err === "db_upgrading") {
                        this.seenUpgrade = true;
                        this.steps = rsp.steps || [];
                        this.current = rsp.current || "";
                    } else if (rsp && rsp.err === "ok" && !rsp.upgrading) {
                        this.leave();
                        return;
                    } else {
                        this.current = "";
                    }
                    this.schedule();
                })
                .catch(() => {
                    this.current = "";
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
            }, this.seenUpgrade ? 800 : 0);
        },
    },
};
</script>

<style scoped>
.upgrade-spinner {
    display: flex;
    justify-content: center;
    gap: 6px;
    padding: 16px 0 24px;
}
.upgrade-cell {
    width: 20px;
    height: 20px;
    border-radius: 3px;
    transition: background-color 0.1s linear;
}
.upgrade-task {
    font-size: 28px;
    line-height: 1.4;
    text-align: center;
}
</style>
