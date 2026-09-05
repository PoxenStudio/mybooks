<template>
    <AppDialog
        v-model="visible"
        type="action"
        :title="$t('book.readingTimeBackfill')"
        icon="mdi-timer-plus-outline"
        color="primary"
        :confirm-text="$t('common.save')"
        :confirm-loading="saving"
        :confirm-disabled="loadingEntry"
        @confirm="onSave"
    >
        <v-menu v-model="dateMenu" :close-on-content-click="false" offset-y min-width="auto">
            <template v-slot:activator="{ on, attrs }">
                <v-text-field
                    :value="date"
                    :label="$t('book.readingTimeDate')"
                    prepend-icon="mdi-calendar"
                    readonly
                    v-bind="attrs"
                    v-on="on"
                ></v-text-field>
            </template>
            <v-date-picker v-model="date" :max="today" @input="onDatePicked"></v-date-picker>
        </v-menu>

        <div class="grey--text text-body-2 mb-2">
            {{ $t('book.readingTimeDateRecorded', { minutes: dateRecordedMinutes }) }}
            &nbsp;·&nbsp;
            {{ $t('book.readingTimeBookRecorded', { minutes: bookTotalMinutes }) }}
        </div>

        <v-row>
            <v-col cols="6">
                <AppTimePicker v-model="startTime" :label="$t('book.readingTimeStart')" @change="onTimeChange"></AppTimePicker>
            </v-col>
            <v-col cols="6">
                <AppTimePicker v-model="endTime" :label="$t('book.readingTimeEnd')" @change="onTimeChange"></AppTimePicker>
            </v-col>
        </v-row>

        <v-text-field
            v-model.number="durationMinutes"
            type="number"
            min="0"
            :max="MAX_MINUTES"
            :label="$t('book.readingTimeDurationMinutes')"
            @change="onDurationChange"
        ></v-text-field>
    </AppDialog>
</template>

<script>
const MAX_MINUTES = 18 * 60;

function toMinutes(hhmm) {
    const [h, m] = (hhmm || "00:00").split(":").map(Number);
    return h * 60 + m;
}

function toHHMM(mins) {
    mins = Math.max(0, Math.min(1439, Math.round(mins)));
    const h = Math.floor(mins / 60);
    const m = mins % 60;
    return String(h).padStart(2, "0") + ":" + String(m).padStart(2, "0");
}

export default {
    name: "ReadingTimeBackfillDialog",
    data() {
        return {
            MAX_MINUTES,
            visible: false,
            bookId: null,
            dateMenu: false,
            date: "",
            startTime: "08:00",
            endTime: "08:30",
            durationMinutes: 30,
            existingEntry: null,
            dateRecordedSeconds: 0,
            bookTotalSeconds: 0,
            loadingEntry: false,
            saving: false,
        };
    },
    computed: {
        today() {
            return new Date().toISOString().slice(0, 10);
        },
        dateRecordedMinutes() {
            return Math.round(this.dateRecordedSeconds / 60);
        },
        bookTotalMinutes() {
            return Math.round(this.bookTotalSeconds / 60);
        },
    },
    methods: {
        open(bookId) {
            this.bookId = bookId;
            this.date = this.today;
            this.visible = true;
            this.fetchEntry();
        },
        close() {
            this.visible = false;
        },
        onDatePicked() {
            this.dateMenu = false;
            this.fetchEntry();
        },
        resetToDefaults() {
            this.existingEntry = null;
            this.startTime = "08:00";
            this.endTime = "08:30";
            this.durationMinutes = 30;
        },
        fetchEntry() {
            this.loadingEntry = true;
            this.$backend(`/book/${this.bookId}/reading_time?date=${this.date}`)
                .then((rsp) => {
                    if (rsp.err !== "ok") return;
                    this.dateRecordedSeconds = rsp.date_recorded_seconds || 0;
                    this.bookTotalSeconds = rsp.book_total_seconds || 0;
                    if (rsp.entry) {
                        this.existingEntry = rsp.entry;
                        this.durationMinutes = Math.round(rsp.entry.duration_seconds / 60);
                        this.startTime = rsp.entry.start_time || "08:00";
                        this.endTime = rsp.entry.end_time || toHHMM(toMinutes(this.startTime) + this.durationMinutes);
                    } else {
                        this.resetToDefaults();
                    }
                })
                .finally(() => {
                    this.loadingEntry = false;
                });
        },
        onTimeChange() {
            let diff = toMinutes(this.endTime) - toMinutes(this.startTime);
            if (diff < 0) diff = 0;
            if (diff > MAX_MINUTES) {
                diff = MAX_MINUTES;
                this.endTime = toHHMM(toMinutes(this.startTime) + MAX_MINUTES);
            }
            this.durationMinutes = diff;
        },
        onDurationChange() {
            const duration = Math.max(0, Math.min(MAX_MINUTES, Math.round(this.durationMinutes) || 0));
            this.durationMinutes = duration;
            let endMin = toMinutes(this.startTime) + duration;
            if (endMin > 1439) {
                const overflow = endMin - 1439;
                this.startTime = toHHMM(toMinutes(this.startTime) - overflow);
                endMin = 1439;
            }
            this.endTime = toHHMM(endMin);
        },
        onSave() {
            if (this.date > this.today) {
                this.$alert("error", this.$t("book.readingTimeFuture"));
                return;
            }
            this.saving = true;
            const request = this.durationMinutes > 0
                ? this.$backend(`/book/${this.bookId}/reading_time`, {
                    method: "POST",
                    body: JSON.stringify({
                        date: this.date,
                        duration_seconds: this.durationMinutes * 60,
                        start_time: this.startTime,
                        end_time: this.endTime,
                    }),
                })
                : this.$backend(`/book/${this.bookId}/reading_time?date=${this.date}`, { method: "DELETE" });

            request
                .then((rsp) => {
                    if (rsp.err === "ok") {
                        this.$alert("success", this.durationMinutes > 0 ? this.$t("book.readingTimeSaved") : this.$t("book.readingTimeDeleted"));
                        this.visible = false;
                        this.$emit("saved");
                    } else {
                        this.$alert("error", rsp.msg);
                    }
                })
                .finally(() => {
                    this.saving = false;
                });
        },
    },
};
</script>
