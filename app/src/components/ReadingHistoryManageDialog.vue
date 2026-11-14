<template>
    <div :class="{ 'is-dark': isDark }">
        <AppDialog
            v-model="visible"
            type="action"
            :title="$t('history.manage.title')"
            icon="mdi-history"
            max-width="860"
            :persistent="false"
            hide-footer-button
            scrollable
        >
            <div v-if="loading" class="text-center py-8">
                <v-progress-circular indeterminate color="primary"></v-progress-circular>
            </div>
            <template v-else>
                <div v-if="summary.records === 0 && summary.manual_records === 0" class="empty-state">
                    <v-icon large color="grey">mdi-history</v-icon>
                    <p class="mt-2 mb-0">{{ $t('history.manage.empty') }}</p>
                </div>
                <template v-else>
                    <div class="summary-box">
                        <div class="summary-main">
                            {{ $t('history.manage.summary', { records: summary.records, books: summary.books }) }}
                        </div>
                        <div v-if="summary.records" class="summary-sub">
                            {{ $t('history.manage.range', { start: summary.first_date, end: summary.last_date }) }}
                            · {{ $t('history.manage.totalDuration', { duration: formatDuration(summary.total_seconds) }) }}
                        </div>
                        <div v-if="summary.manual_records" class="summary-sub">
                            {{ $t('history.manage.manualRecords', { records: summary.manual_records }) }}
                        </div>
                    </div>

                    <div class="book-list">
                        <div v-for="book in books" :key="book.book_id" class="book-item">
                            <div class="book-row">
                                <v-img
                                    v-if="book.thumb || book.img"
                                    :src="book.thumb || book.img"
                                    class="book-cover"
                                    width="36"
                                    height="48"
                                ></v-img>
                                <div v-else class="book-cover book-cover-empty">
                                    <v-icon small color="grey">mdi-book-open-page-variant-outline</v-icon>
                                </div>
                                <div class="book-meta">
                                    <div class="book-title">{{ bookTitle(book) }}</div>
                                    <div class="book-sub">
                                        {{ $t('history.manage.bookLine', { records: book.records, duration: formatDuration(book.total_seconds) }) }}
                                        · {{ book.first_date }} ~ {{ book.last_date }}
                                    </div>
                                </div>
                                <v-btn icon small :title="$t('history.manage.expand')" @click="toggleDetail(book)">
                                    <v-icon small>{{ expanded[book.book_id] ? 'mdi-chevron-up' : 'mdi-chevron-down' }}</v-icon>
                                </v-btn>
                                <v-btn icon small color="error" :title="$t('history.manage.deleteBook')" @click="askDeleteBook(book)">
                                    <v-icon small>mdi-delete-outline</v-icon>
                                </v-btn>
                            </div>
                            <div v-if="expanded[book.book_id]" class="detail-box">
                                <div v-if="detailLoading[book.book_id]" class="text-center py-3">
                                    <v-progress-circular indeterminate size="20" color="primary"></v-progress-circular>
                                </div>
                                <div v-else-if="!(detailRows[book.book_id] || []).length" class="detail-empty">
                                    {{ $t('history.manage.detailEmpty') }}
                                </div>
                                <v-simple-table v-else dense>
                                    <thead>
                                        <tr>
                                            <th>{{ $t('history.manage.date') }}</th>
                                            <th>{{ $t('history.manage.duration') }}</th>
                                            <th class="text-right">{{ $t('history.manage.action') }}</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        <tr v-for="row in detailRows[book.book_id]" :key="row.date">
                                            <td>{{ row.date }}</td>
                                            <td>{{ formatDuration(row.duration) }}</td>
                                            <td class="text-right">
                                                <v-btn icon small color="error" :title="$t('history.manage.deleteDay')" @click="askDeleteDay(book, row)">
                                                    <v-icon small>mdi-delete-outline</v-icon>
                                                </v-btn>
                                            </td>
                                        </tr>
                                    </tbody>
                                </v-simple-table>
                            </div>
                        </div>
                    </div>

                    <v-divider class="my-4"></v-divider>
                    <div class="danger-zone">
                        <div class="danger-title">{{ $t('history.manage.dangerTitle') }}</div>
                        <div class="danger-hint">{{ $t('history.manage.dangerHint') }}</div>
                        <v-btn outlined small color="error" @click="askClearAll">
                            <v-icon small left>mdi-delete-outline</v-icon>
                            {{ $t('history.manage.clearAll') }}
                        </v-btn>
                    </div>
                </template>
            </template>
        </AppDialog>

        <AppDialog
            v-model="confirmOpen"
            type="confirm"
            icon="mdi-alert"
            color="error"
            :title="confirmTitle"
            :confirm-text="$t('history.manage.confirmButton')"
            confirm-color="error"
            :confirm-disabled="!confirmChecked"
            :confirm-loading="deleting"
            max-width="460"
            @confirm="executeDelete"
            @dismiss="resetConfirm"
        >
            <p class="mb-3">{{ confirmMessage }}</p>
            <p v-if="pendingAction && pendingAction.type === 'all' && summary.manual_records" class="mb-3">
                {{ $t('history.manage.confirmManual', { records: summary.manual_records }) }}
            </p>
            <v-checkbox v-model="confirmChecked" :label="$t('history.manage.confirmCheckbox')" hide-details></v-checkbox>
        </AppDialog>
    </div>
</template>

<script>
const EMPTY_SUMMARY = {
    records: 0,
    books: 0,
    total_seconds: 0,
    first_date: null,
    last_date: null,
    manual_records: 0,
};

export default {
    name: 'ReadingHistoryManageDialog',
    props: {
        value: { type: Boolean, default: false },
    },
    data: () => ({
        summary: { ...EMPTY_SUMMARY },
        books: [],
        loading: false,
        loadSeq: 0,
        expanded: {},
        detailRows: {},
        detailLoading: {},
        detailSeq: {},
        confirmOpen: false,
        confirmChecked: false,
        deleting: false,
        pendingAction: null,
    }),
    computed: {
        isDark() {
            return this.$vuetify.theme.dark;
        },
        visible: {
            get() {
                return this.value;
            },
            set(value) {
                this.$emit('input', value);
            },
        },
        confirmTitle() {
            if (!this.pendingAction) return '';
            if (this.pendingAction.type === 'all') return this.$t('history.manage.confirmAllTitle');
            if (this.pendingAction.type === 'book') return this.$t('history.manage.confirmBookTitle');
            return this.$t('history.manage.confirmDayTitle');
        },
        confirmMessage() {
            const action = this.pendingAction;
            if (!action) return '';
            if (action.type === 'all') {
                return this.$t('history.manage.confirmAll', {
                    records: this.summary.records,
                    books: this.summary.books,
                    duration: this.formatDuration(this.summary.total_seconds),
                });
            }
            if (action.type === 'book') {
                return this.$t('history.manage.confirmBook', {
                    title: this.bookTitle(action.book),
                    records: action.book.records,
                    duration: this.formatDuration(action.book.total_seconds),
                });
            }
            return this.$t('history.manage.confirmDay', {
                title: this.bookTitle(action.book),
                date: action.row.date,
                duration: this.formatDuration(action.row.duration),
            });
        },
    },
    watch: {
        value(value) {
            if (value) {
                this.open();
            } else {
                this.resetConfirm();
            }
        },
    },
    methods: {
        open() {
            this.expanded = {};
            this.detailRows = {};
            this.detailLoading = {};
            this.resetConfirm();
            this.load();
        },
        load() {
            const seq = ++this.loadSeq;
            this.loading = true;
            Promise.all([
                this.$backend('/user/history/summary'),
                this.$backend('/user/history/books'),
            ])
                .then(([summaryRsp, booksRsp]) => {
                    if (seq !== this.loadSeq) return;
                    if (summaryRsp.err === 'ok') {
                        this.summary = summaryRsp.summary || { ...EMPTY_SUMMARY };
                    } else {
                        this.$alert('error', summaryRsp.msg || this.$t('history.manage.loadFailed'));
                    }
                    if (booksRsp.err === 'ok') {
                        this.books = booksRsp.books || [];
                    } else {
                        this.$alert('error', booksRsp.msg || this.$t('history.manage.loadFailed'));
                    }
                })
                .catch(() => {
                    if (seq !== this.loadSeq) return;
                    this.$alert('error', this.$t('history.manage.loadFailed'));
                })
                .finally(() => {
                    if (seq === this.loadSeq) {
                        this.loading = false;
                    }
                });
        },
        loadDetail(bookId) {
            const seq = (this.detailSeq[bookId] || 0) + 1;
            this.$set(this.detailSeq, bookId, seq);
            this.$set(this.detailLoading, bookId, true);
            this.$backend(`/user/history/books/${bookId}`)
                .then((rsp) => {
                    if (this.detailSeq[bookId] !== seq) return;
                    if (rsp.err === 'ok') {
                        this.$set(this.detailRows, bookId, rsp.records || []);
                    } else {
                        this.$alert('error', rsp.msg || this.$t('history.manage.detailFailed'));
                    }
                })
                .catch(() => {
                    if (this.detailSeq[bookId] !== seq) return;
                    this.$alert('error', this.$t('history.manage.detailFailed'));
                })
                .finally(() => {
                    if (this.detailSeq[bookId] === seq) {
                        this.$set(this.detailLoading, bookId, false);
                    }
                });
        },
        toggleDetail(book) {
            const bookId = book.book_id;
            this.$set(this.expanded, bookId, !this.expanded[bookId]);
            if (this.expanded[bookId] && !this.detailRows[bookId]) {
                this.loadDetail(bookId);
            }
        },
        bookTitle(book) {
            if (book.missing || !book.title) {
                return this.$t('history.manage.missingBook', { id: book.book_id });
            }
            return book.title;
        },
        formatDuration(seconds) {
            seconds = Math.max(0, Math.floor(Number(seconds) || 0));
            if (seconds < 60) {
                return this.$t('history.dashboard.durationSeconds', { seconds });
            }
            const hours = Math.floor(seconds / 3600);
            const minutes = Math.floor((seconds % 3600) / 60);
            if (hours <= 0) {
                return this.$t('book.readingStats.durationMinutes', { minutes });
            }
            return this.$t('book.readingStats.durationHoursMinutes', { hours, minutes });
        },
        askDeleteBook(book) {
            this.pendingAction = { type: 'book', book };
            this.confirmChecked = false;
            this.confirmOpen = true;
        },
        askDeleteDay(book, row) {
            this.pendingAction = { type: 'day', book, row };
            this.confirmChecked = false;
            this.confirmOpen = true;
        },
        askClearAll() {
            this.pendingAction = { type: 'all' };
            this.confirmChecked = false;
            this.confirmOpen = true;
        },
        resetConfirm() {
            this.confirmOpen = false;
            this.pendingAction = null;
            this.confirmChecked = false;
        },
        executeDelete() {
            const action = this.pendingAction;
            if (!action || !this.confirmChecked) return;
            let request;
            if (action.type === 'all') {
                request = this.$backend('/user/history/clear', { method: 'POST' });
            } else if (action.type === 'book') {
                request = this.$backend(`/user/history/books/${action.book.book_id}`, { method: 'DELETE' });
            } else {
                request = this.$backend(
                    `/user/history/books/${action.book.book_id}?date=${action.row.date}`,
                    { method: 'DELETE' }
                );
            }
            this.deleting = true;
            request
                .then((rsp) => {
                    if (rsp.err !== 'ok') {
                        this.$alert('error', rsp.msg || this.$t('history.manage.deleteFailed'));
                        return;
                    }
                    const deleted = rsp.deleted || {};
                    this.$alert('success', this.$t('history.manage.deleted', { records: deleted.records || 0 }));
                    this.resetConfirm();
                    if (action.type === 'all') {
                        this.load();
                    } else {
                        this.refreshAfterDelete(action.book.book_id);
                    }
                    this.$emit('changed');
                })
                .catch(() => {
                    this.$alert('error', this.$t('history.manage.deleteFailed'));
                })
                .finally(() => {
                    this.deleting = false;
                });
        },
        refreshAfterDelete(bookId) {
            // Invalidate any in-flight detail request for this book before reloading.
            this.$set(this.detailSeq, bookId, (this.detailSeq[bookId] || 0) + 1);
            this.$delete(this.detailRows, bookId);
            this.load();
            if (this.expanded[bookId]) {
                this.loadDetail(bookId);
            }
        },
    },
};
</script>

<style scoped>
.summary-box {
    background: rgba(0, 0, 0, 0.04);
    border-radius: 8px;
    padding: 12px 16px;
    margin-bottom: 12px;
}
.summary-main {
    font-size: 15px;
    font-weight: 600;
}
.summary-sub {
    font-size: 12px;
    color: rgba(0, 0, 0, 0.6);
    margin-top: 4px;
}
.book-list {
    max-height: 52vh;
    overflow-y: auto;
    padding-right: 4px;
}
.book-item {
    border-bottom: 1px solid rgba(0, 0, 0, 0.08);
}
.book-row {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px 0;
}
.book-cover {
    flex: 0 0 auto;
    border-radius: 3px;
    object-fit: cover;
}
.book-cover-empty {
    display: flex;
    align-items: center;
    justify-content: center;
    background: rgba(0, 0, 0, 0.05);
}
.book-meta {
    flex: 1 1 auto;
    min-width: 0;
}
.book-title {
    font-size: 14px;
    font-weight: 500;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}
.book-sub {
    font-size: 12px;
    color: rgba(0, 0, 0, 0.6);
    margin-top: 2px;
}
.detail-box {
    background: rgba(0, 0, 0, 0.03);
    border-radius: 6px;
    padding: 4px 12px 8px;
    margin-bottom: 8px;
}
.detail-empty {
    font-size: 12px;
    color: rgba(0, 0, 0, 0.5);
    padding: 8px 0;
}
.danger-zone {
    border: 1px solid rgba(198, 40, 40, 0.35);
    border-radius: 8px;
    padding: 12px 16px;
}
.danger-title {
    font-size: 14px;
    font-weight: 600;
    color: #c62828;
}
.danger-hint {
    font-size: 12px;
    color: rgba(0, 0, 0, 0.6);
    margin: 4px 0 10px;
}
.empty-state {
    text-align: center;
    padding: 24px 0;
    color: rgba(0, 0, 0, 0.6);
}
.is-dark .summary-box {
    background: rgba(255, 255, 255, 0.08);
}
.is-dark .summary-sub,
.is-dark .book-sub,
.is-dark .detail-empty,
.is-dark .danger-hint,
.is-dark .empty-state {
    color: rgba(255, 255, 255, 0.7);
}
.is-dark .book-item {
    border-bottom-color: rgba(255, 255, 255, 0.12);
}
.is-dark .book-cover-empty,
.is-dark .detail-box {
    background: rgba(255, 255, 255, 0.06);
}
.is-dark .danger-zone {
    border-color: rgba(239, 83, 80, 0.6);
}
.is-dark .danger-title {
    color: #ef5350;
}
</style>
