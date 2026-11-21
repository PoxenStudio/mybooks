<template>
    <AppDialog
        v-model="show"
        type="action"
        :title="$t('novelFormat.title')"
        icon="mdi-text-box-edit-outline"
        color="#2d6d4b"
        max-width="1180"
        scrollable
        hide-footer-button
        dismiss-icon
        :dismiss-disabled="processing || covering"
        @dismiss="close"
    >
        <div v-if="total === 0" class="py-8 text-center grey--text nf-empty">
            {{ $t('novelFormat.empty') }}
        </div>

        <template v-else>
            <!-- 批次进度 -->
            <div class="nf-head">
                <div class="nf-head-main">
                    <span class="text-subtitle-1 font-weight-bold">
                        {{ finished ? $t('novelFormat.finishedTitle') : $t('novelFormat.progress', { current: index + 1, total: total }) }}
                    </span>
                    <span v-if="currentBook && !finished" class="nf-book-title text-truncate">{{ currentBook.title }}</span>
                </div>
                <div class="nf-head-meta">
                    <v-chip x-small outlined class="mr-2">{{ $t('novelFormat.coveredCount', { count: coveredCount }) }}</v-chip>
                    <v-chip v-if="skipped.length" x-small outlined color="warning">{{ $t('novelFormat.skippedCount', { count: skipped.length }) }}</v-chip>
                    <span class="nf-percent">{{ progressPercent }}%</span>
                    <v-btn
                        v-if="!finished"
                        x-small
                        text
                        color="warning"
                        class="ml-2"
                        :disabled="processing || covering || loadingText"
                        @click="skipCurrent"
                    >
                        <v-icon x-small left>mdi-skip-next</v-icon>{{ $t('novelFormat.skip') }}
                    </v-btn>
                </div>
            </div>
            <v-progress-linear :value="progressPercent" height="14" color="green" rounded></v-progress-linear>

            <v-alert v-if="autoRunning" type="info" dense text class="mt-3 mb-0">
                <div class="d-flex align-center">
                    <span class="flex-grow-1">{{ $t('novelFormat.autoRunningHint') }}</span>
                    <v-btn x-small text color="info" @click="stopAuto">{{ $t('novelFormat.stopAuto') }}</v-btn>
                </div>
            </v-alert>

            <!-- 完成后的汇总 -->
            <div v-if="finished" class="nf-summary">
                <v-icon size="48" color="green">mdi-check-circle-outline</v-icon>
                <div class="text-h6 mt-2">{{ $t('novelFormat.finishedTitle') }}</div>
                <div class="grey--text mt-1">
                    {{ $t('novelFormat.finishedSummary', { done: coveredCount, total: total }) }}
                </div>
                <div v-if="skipped.length" class="grey--text mt-1">
                    {{ $t('novelFormat.skippedCount', { count: skipped.length }) }}
                </div>
                <v-btn color="primary" class="mt-4" @click="close">{{ $t('novelFormat.close') }}</v-btn>
            </div>

            <v-row v-else class="mt-3">
                <!-- 左列：原文 → 处理 → 结果 -->
                <v-col cols="12" md="7">
                    <v-card outlined class="nf-card">
                        <v-card-title class="nf-card-title">
                            <v-icon small left>mdi-book-open-page-variant-outline</v-icon>
                            <span>{{ $t('novelFormat.original') }}</span>
                            <v-spacer></v-spacer>
                            <v-chip x-small outlined class="mr-1">{{ encoding }}</v-chip>
                            <v-chip x-small outlined>{{ formatSize }}</v-chip>
                        </v-card-title>
                        <v-card-text class="pt-2">
                            <v-textarea
                                :value="sourceDisplay"
                                readonly
                                outlined
                                dense
                                hide-details
                                :rows="16"
                                :loading="loadingText"
                                :placeholder="loadingText ? $t('novelFormat.loading') : $t('novelFormat.noContent')"
                                class="nf-text"
                            ></v-textarea>
                            <div v-if="sourceTooLong" class="nf-hint mt-1">
                                {{ $t('novelFormat.previewOnly', { count: sourceStats.chars, limit: editLimitLabel }) }}
                            </div>
                            <div class="nf-stats">
                                <span>{{ $t('novelFormat.chars') }} {{ sourceStats.chars }}</span>
                                <span class="ml-4">{{ $t('novelFormat.lines') }} {{ sourceStats.lines }}</span>
                                <v-spacer></v-spacer>
                                <span v-if="loadFailed" class="error--text">{{ loadFailed }}</span>
                            </div>
                        </v-card-text>
                    </v-card>

                    <div class="mt-3">
                        <v-btn
                            block
                            large
                            color="primary"
                            :loading="processing"
                            :disabled="!sourceText || loadingText || covering"
                            @click="process"
                        >
                            <v-icon left>mdi-play-circle-outline</v-icon>
                            {{ $t('novelFormat.start') }}
                        </v-btn>
                        <div class="d-flex mt-2 align-center" style="gap: 4px;">
                            <v-tooltip bottom>
                                <template #activator="{ on, attrs }">
                                    <v-btn small outlined v-bind="attrs" v-on="on" :disabled="!sourceText" @click="splitChapters">
                                        <v-icon small>mdi-content-cut</v-icon>
                                    </v-btn>
                                </template>
                                <span>{{ $t('novelFormat.chapterSplit') }}</span>
                            </v-tooltip>
                            <v-tooltip bottom>
                                <template #activator="{ on, attrs }">
                                    <v-btn small outlined v-bind="attrs" v-on="on" :disabled="!sourceText" @click="reorderChapters">
                                        <v-icon small>mdi-sort-numeric-ascending</v-icon>
                                    </v-btn>
                                </template>
                                <span>{{ $t('novelFormat.chapterReorder') }}</span>
                            </v-tooltip>
                        </div>
                    </div>

                    <v-card v-if="result" outlined class="nf-card mt-3">
                        <v-card-title class="nf-card-title">
                            <v-icon small left>mdi-file-document-edit-outline</v-icon>
                            <span>{{ $t('novelFormat.result') }}</span>
                            <v-spacer></v-spacer>
                            <v-btn x-small text @click="copyResult">
                                <v-icon small left>mdi-content-copy</v-icon>{{ $t('novelFormat.copy') }}
                            </v-btn>
                            <v-btn x-small text @click="exportFile">
                                <v-icon small left>mdi-download</v-icon>{{ $t('novelFormat.export') }}
                            </v-btn>
                        </v-card-title>
                        <v-card-text class="pt-2">
                            <v-textarea :value="resultDisplay" readonly outlined dense hide-details :rows="14" class="nf-text"></v-textarea>
                            <div v-if="resultTooLong" class="nf-hint mt-1">
                                {{ $t('novelFormat.previewOnly', { count: resultStats.chars, limit: editLimitLabel }) }}
                            </div>
                            <div v-else class="nf-hint mt-1">{{ $t('novelFormat.readonlyHint') }}</div>
                            <div class="nf-stats">
                                <span>{{ $t('novelFormat.chars') }} {{ resultStats.chars }}</span>
                                <span class="ml-4">{{ $t('novelFormat.lines') }} {{ resultStats.lines }}</span>
                            </div>
                        </v-card-text>
                        <v-card-actions class="pt-0">
                            <v-spacer></v-spacer>
                            <v-btn small outlined :loading="covering" :disabled="processing" @click="coverOnly">
                                <v-icon small left>mdi-content-save-outline</v-icon>{{ $t('novelFormat.cover') }}
                            </v-btn>
                            <v-btn small color="primary" :loading="covering" :disabled="processing" @click="complete">
                                {{ $t('novelFormat.complete') }}
                                <v-icon small right>mdi-arrow-right</v-icon>
                            </v-btn>
                        </v-card-actions>
                    </v-card>
                </v-col>

                <!-- 右列：配置 -->
                <v-col cols="12" md="5">
                    <v-card outlined class="nf-card">
                        <v-card-title class="nf-card-title">
                            <v-icon small left>mdi-tune</v-icon>{{ $t('novelFormat.config') }}
                        </v-card-title>
                        <v-card-text class="pt-1">
                            <div class="nf-group-title">{{ $t('novelFormat.layout') }}</div>
                            <div class="nf-switch-row">
                                <span>{{ $t('novelFormat.smartLineBreak') }}</span>
                                <v-switch v-model="prefs.smartLineBreak" dense inset hide-details class="mt-0" color="primary"></v-switch>
                            </div>
                            <div v-if="prefs.smartLineBreak" class="nf-switch-row nf-sub">
                                <span>{{ $t('novelFormat.indent') }}</span>
                                <v-switch v-model="prefs.enableIndent" dense inset hide-details class="mt-0" color="primary"></v-switch>
                            </div>
                            <div class="nf-switch-row">
                                <span>{{ $t('novelFormat.paragraphSplit') }}</span>
                                <v-switch v-model="prefs.enableParagraphSplit" dense inset hide-details class="mt-0" color="primary"></v-switch>
                            </div>
                            <div class="nf-switch-row">
                                <span>{{ $t('novelFormat.trim') }}</span>
                                <v-switch v-model="prefs.enableTrim" dense inset hide-details class="mt-0" color="primary"></v-switch>
                            </div>

                            <v-divider class="my-2"></v-divider>
                            <div class="nf-group-title">{{ $t('novelFormat.chapter') }}</div>
                            <div class="nf-switch-row">
                                <span>{{ $t('novelFormat.chapterTitleSplit') }}</span>
                                <v-switch v-model="prefs.enableChapterSplit" dense inset hide-details class="mt-0" color="primary"></v-switch>
                            </div>
                            <div class="nf-switch-row">
                                <span>{{ $t('novelFormat.mergeDupTitles') }}</span>
                                <v-switch v-model="prefs.mergeDuplicateChapterTitles" dense inset hide-details class="mt-0" color="primary"></v-switch>
                            </div>
                            <div class="nf-switch-row">
                                <span>{{ $t('novelFormat.dedupeLines') }}</span>
                                <v-switch v-model="prefs.removeDuplicateLines" dense inset hide-details class="mt-0" color="primary"></v-switch>
                            </div>

                            <v-divider class="my-2"></v-divider>
                            <div class="nf-group-title">{{ $t('novelFormat.advanced') }}</div>
                            <div class="nf-switch-row">
                                <span>{{ $t('novelFormat.lineEndNumbers') }}</span>
                                <v-switch v-model="prefs.enableLineEndNumbers" dense inset hide-details class="mt-0" color="primary"></v-switch>
                            </div>

                            <!-- 自动识别作者：只读展示识别结果，开关决定覆盖时是否写回作者字段 -->
                            <div class="nf-author-row">
                                <span class="nf-author-label">{{ $t('novelFormat.autoAuthor') }}</span>
                                <v-text-field
                                    :value="detectedAuthor"
                                    readonly
                                    dense
                                    outlined
                                    hide-details
                                    :placeholder="$t('novelFormat.authorUnknown')"
                                    class="nf-author-input"
                                ></v-text-field>
                                <v-switch
                                    v-model="prefs.autoAuthor"
                                    dense
                                    inset
                                    hide-details
                                    class="mt-0"
                                    color="primary"
                                    :aria-label="$t('novelFormat.autoAuthor')"
                                ></v-switch>
                            </div>
                            <div class="nf-hint">{{ $t('novelFormat.autoAuthorHint') }}</div>
                            <div class="nf-field-label">{{ $t('novelFormat.conversion') }}</div>
                            <v-btn-toggle v-model="prefs.conversionMode" mandatory dense class="nf-toggle">
                                <v-btn small value="none">{{ $t('novelFormat.convNone') }}</v-btn>
                                <v-btn small value="t2s">{{ $t('novelFormat.convT2S') }}</v-btn>
                                <v-btn small value="s2t">{{ $t('novelFormat.convS2T') }}</v-btn>
                            </v-btn-toggle>

                            <div class="nf-field-label mt-3">{{ $t('novelFormat.specialStart') }}</div>
                            <v-text-field v-model="prefs.specialStart" dense outlined hide-details :placeholder="$t('novelFormat.specialStartHint')"></v-text-field>

                            <div class="nf-field-label mt-3">{{ $t('novelFormat.filterText') }}</div>
                            <v-text-field v-model="prefs.filterText" dense outlined hide-details :placeholder="$t('novelFormat.filterPlaceholder')"></v-text-field>
                            <v-text-field
                                v-if="prefs.filterText"
                                v-model.number="prefs.maxFilterLineLength"
                                class="mt-2"
                                dense
                                outlined
                                hide-details
                                type="number"
                                min="0"
                                :label="$t('novelFormat.maxLineLen')"
                                :hint="$t('novelFormat.maxLineLenHint')"
                                persistent-hint
                            ></v-text-field>

                            <v-divider class="my-3"></v-divider>
                            <div class="nf-switch-row">
                                <div>
                                    <div>{{ $t('novelFormat.autoExport') }}</div>
                                    <div class="nf-hint">{{ $t('novelFormat.autoExportHint') }}</div>
                                </div>
                                <v-switch v-model="prefs.autoExport" dense inset hide-details class="mt-0" color="primary"></v-switch>
                            </div>
                            <div class="nf-switch-row">
                                <div>
                                    <div>{{ $t('novelFormat.autoCover') }}</div>
                                    <div class="nf-hint">{{ $t('novelFormat.autoCoverHint') }}</div>
                                </div>
                                <v-switch v-model="prefs.autoCover" dense inset hide-details class="mt-0" color="green"></v-switch>
                            </div>
                        </v-card-text>
                    </v-card>
                </v-col>
            </v-row>

            <!-- 忽略规则：批次开始时的跳过判据，写在这里让用户不用翻文档 -->
            <div class="nf-rules">
                <div class="nf-rules-title">
                    <v-icon x-small left>mdi-information-outline</v-icon>
                    {{ $t('novelFormat.ignoreRules') }}
                </div>
                <ul class="nf-rules-list">
                    <li>{{ $t('novelFormat.ruleTagged') }}</li>
                    <li>{{ $t('novelFormat.ruleNoTxt') }}</li>
                    <li>{{ $t('novelFormat.ruleTagAfter') }}</li>
                </ul>
            </div>
        </template>
    </AppDialog>
</template>

<script>
import AppDialog from '~/components/AppDialog.vue';
import { formatNovelText, splitInlineChapterTitles, reorderChaptersByTitle } from '~/utils/novel/novelUtils';
import { detectAuthor } from '~/utils/novel/authorDetect';

const PREFS_KEY = 'novelFormat.prefs';
// 与后端 novel_format.REVISED_TAG 保持一致：覆盖成功后自动打的标记标签
const REVISED_TAG = '精校';
// 文本框里最多渲染多少字：百万字以上塞进 textarea 会把主线程卡住（上游工具同样做了截断预览）。
// 截断只影响展示，result 数据仍是全文，覆盖/导出用的都是完整内容。
const EDIT_DISPLAY_LIMIT = 50000;

const DEFAULT_PREFS = {
    conversionMode: 'none',
    smartLineBreak: true,
    enableIndent: true,
    enableChapterSplit: true,
    enableLineEndNumbers: false,
    enableParagraphSplit: false,
    enableTrim: true,
    removeDuplicateLines: true,
    mergeDuplicateChapterTitles: true,
    specialStart: '',
    filterText: '',
    maxFilterLineLength: 0,
    autoExport: false,
    autoCover: false,
    autoAuthor: false,
};

const countStats = (text) => {
    const value = text || '';
    return {
        chars: value.length.toLocaleString('en-US'),
        lines: (value ? value.split('\n').length : 0).toLocaleString('en-US'),
    };
};

export default {
    components: { AppDialog },
    props: {
        value: { type: Boolean, default: false },
        books: { type: Array, default: () => [] },
    },
    data: () => ({
        index: 0,
        sourceText: '',
        result: '',
        encoding: 'utf-8',
        loadingText: false,
        processing: false,
        covering: false,
        autoRunning: false,
        finished: false,
        coveredIds: [],
        skipped: [],
        processed: 0,
        loadFailed: '',
        bookSize: 0,
        authorGuess: '',
        prefs: { ...DEFAULT_PREFS },
    }),
    computed: {
        show: {
            get() { return this.value; },
            set(val) { this.$emit('input', val); },
        },
        total() { return this.books.length; },
        currentBook() { return this.books[this.index] || null; },
        coveredCount() { return this.coveredIds.length; },
        progressPercent() {
            if (!this.total) return 0;
            return Math.min(100, Math.round((this.processed / this.total) * 100));
        },
        sourceStats() { return countStats(this.sourceText); },
        detectedAuthor() { return this.authorGuess; },
        resultStats() { return countStats(this.result); },
        editLimitLabel() { return EDIT_DISPLAY_LIMIT.toLocaleString('en-US'); },
        sourceTooLong() { return this.sourceText.length > EDIT_DISPLAY_LIMIT; },
        sourceDisplay() {
            return this.sourceTooLong ? `${this.sourceText.slice(0, EDIT_DISPLAY_LIMIT)}\n\n…` : this.sourceText;
        },
        resultTooLong() { return this.result.length > EDIT_DISPLAY_LIMIT; },
        resultDisplay() {
            return this.resultTooLong ? `${this.result.slice(0, EDIT_DISPLAY_LIMIT)}\n\n…` : this.result;
        },
        formatSize() {
            const size = Number(this.bookSize) || 0;
            if (!size) return '';
            if (size > 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} MB`;
            return `${Math.max(1, Math.round(size / 1024))} KB`;
        },
    },
    watch: {
        value(val) {
            if (val) {
                this.restorePrefs();
                this.start();
            } else {
                this.stopAuto();
            }
        },
        prefs: {
            deep: true,
            handler(val) {
                try {
                    localStorage.setItem(PREFS_KEY, JSON.stringify(val));
                } catch (e) {
                    // 隐私模式 / 存储写满时忽略：偏好丢失不影响本次处理
                }
            },
        },
    },
    methods: {
        restorePrefs() {
            try {
                const raw = localStorage.getItem(PREFS_KEY);
                const saved = raw ? JSON.parse(raw) : {};
                this.prefs = { ...DEFAULT_PREFS, ...saved };
            } catch (e) {
                this.prefs = { ...DEFAULT_PREFS };
            }
        },
        start() {
            this.index = 0;
            this.processed = 0;
            this.coveredIds = [];
            this.skipped = [];
            this.finished = false;
            this.autoRunning = false;
            this.sourceText = '';
            this.result = '';
            this.loadFailed = '';
            this.bookSize = 0;
            this.authorGuess = '';
            // 批次级忽略规则（与弹窗底部的说明一致）：
            // 已带「精校」标签的书跳过（避免重复校正），没有 TXT 的书跳过（排版算法只吃纯文本）
            while (this.index < this.total) {
                const book = this.books[this.index];
                const fmts = book.formats || [];
                const tags = book.tags || [];
                let reason = '';
                if (tags.includes(REVISED_TAG)) {
                    reason = this.$t('novelFormat.alreadyRevised');
                } else if (fmts.length && !fmts.includes('TXT')) {
                    reason = this.$t('novelFormat.noTxtFormat');
                }
                if (!reason) break;
                this.skipped.push({ id: book.id, title: book.title, reason });
                this.processed += 1;
                this.index += 1;
            }
            if (this.index >= this.total) {
                this.finishBatch();
                return;
            }
            this.loadCurrent();
        },
        async loadCurrent() {
            if (this.index >= this.total) {
                this.finishBatch();
                return;
            }
            const book = this.currentBook;
            this.loadingText = true;
            this.loadFailed = '';
            this.sourceText = '';
            this.result = '';
            try {
                const rsp = await this.$backend(`/novel_format/${book.id}/text`);
                if (rsp.err !== 'ok') {
                    this.loadFailed = rsp.msg || this.$t('novelFormat.loadFailed');
                    this.recordSkip(book, this.loadFailed);
                    if (this.autoRunning) {
                        await this.advance();
                    }
                    return;
                }
                this.sourceText = rsp.data.content || '';
                this.encoding = rsp.data.encoding || 'utf-8';
                this.bookSize = rsp.data.size || 0;
                this.authorGuess = detectAuthor(this.sourceText, book.title);
                if (!this.sourceText) {
                    this.loadFailed = this.$t('novelFormat.noContent');
                    this.recordSkip(book, this.loadFailed);
                    if (this.autoRunning) await this.advance();
                    return;
                }
                if (this.autoRunning) {
                    this.loadingText = false;
                    await this.process();
                }
            } catch (e) {
                this.loadFailed = (e && e.message) || this.$t('novelFormat.loadFailed');
                this.recordSkip(book, this.loadFailed);
                this.autoRunning = false;
            } finally {
                this.loadingText = false;
            }
        },
        recordSkip(book, reason) {
            if (!this.skipped.some((s) => s.id === book.id)) {
                this.skipped.push({ id: book.id, title: book.title, reason });
            }
        },
        buildOptions() {
            return {
                enableChapterSplit: this.prefs.enableChapterSplit,
                filterText: this.prefs.filterText,
                maxFilterLineLength: Number(this.prefs.maxFilterLineLength) || 0,
                enableLineEndNumbers: this.prefs.enableLineEndNumbers,
                enableParagraphSplit: this.prefs.enableParagraphSplit,
                smartLineBreak: this.prefs.smartLineBreak,
                enableTrim: this.prefs.enableTrim,
                mergeDuplicateChapterTitles: this.prefs.mergeDuplicateChapterTitles,
                removeDuplicateLines: this.prefs.removeDuplicateLines,
                enableIndent: this.prefs.enableIndent,
                specialStart: this.prefs.specialStart,
            };
        },
        async process() {
            if (!this.sourceText.trim()) {
                this.$alert('warning', this.$t('novelFormat.noContent'));
                return;
            }
            this.processing = true;
            this.autoRunning = !!this.prefs.autoCover;
            try {
                let text = this.sourceText;
                if (this.prefs.conversionMode !== 'none') {
                    const rsp = await this.$backend('/novel_format/convert', {
                        method: 'POST',
                        body: JSON.stringify({ text, direction: this.prefs.conversionMode }),
                    });
                    if (rsp.err !== 'ok') throw new Error(rsp.msg || this.$t('novelFormat.convertFailed'));
                    text = rsp.data.text;
                }
                this.result = await formatNovelText(text, this.buildOptions());
                if (this.prefs.autoExport) this.exportFile();
                if (this.autoRunning) {
                    await this.coverAndAdvance();
                }
            } catch (e) {
                this.autoRunning = false;
                this.$alert('error', (e && e.message) || this.$t('novelFormat.processFailed'));
            } finally {
                this.processing = false;
            }
        },
        async saveToBook() {
            const book = this.currentBook;
            if (!book) return;
            const rsp = await this.$backend(`/novel_format/${book.id}/save`, {
                method: 'POST',
                body: JSON.stringify({
                    content: this.result,
                    encoding: this.encoding,
                    author: this.prefs.autoAuthor && this.authorGuess ? this.authorGuess : '',
                }),
            });
            if (rsp.err !== 'ok') throw new Error(rsp.msg || this.$t('novelFormat.coverFailed'));
            // 按书籍去重：同一本反复点「覆盖」只算一本，计数口径是「覆盖过的书」而非点击次数
            if (!this.coveredIds.includes(book.id)) {
                this.coveredIds.push(book.id);
            }
            this.$alert('success', this.$t('novelFormat.coverSuccess', { title: book.title }));
        },
        async coverOnly() {
            if (!this.result) {
                this.$alert('warning', this.$t('novelFormat.noResult'));
                return;
            }
            this.covering = true;
            try {
                await this.saveToBook();
            } catch (e) {
                this.$alert('error', (e && e.message) || this.$t('novelFormat.coverFailed'));
            } finally {
                this.covering = false;
            }
        },
        async coverAndAdvance() {
            this.covering = true;
            try {
                await this.saveToBook();
            } catch (e) {
                // 自动覆盖失败就停下，避免在没写回的情况下继续吞掉后续书籍
                this.autoRunning = false;
                this.$alert('error', (e && e.message) || this.$t('novelFormat.coverFailed'));
                return;
            } finally {
                this.covering = false;
            }
            await this.advance();
        },
        async complete() {
            if (!this.result) {
                await this.advance();
                return;
            }
            if (this.prefs.autoCover) {
                this.autoRunning = true;
                await this.coverAndAdvance();
                return;
            }
            await this.advance();
        },
        skipCurrent() {
            const book = this.currentBook;
            if (book) this.recordSkip(book, this.$t('novelFormat.manualSkip'));
            this.advance();
        },
        async advance() {            this.processed = Math.min(this.total, this.processed + 1);
            this.index += 1;
            this.sourceText = '';
            this.result = '';
            this.loadFailed = '';
            this.bookSize = 0;
            this.authorGuess = '';
            if (this.index >= this.total) {
                this.finishBatch();
                return;
            }
            await this.loadCurrent();
        },
        finishBatch() {
            this.finished = true;
            this.autoRunning = false;
            this.$emit('finished');
        },
        stopAuto() {
            this.autoRunning = false;
        },
        splitChapters() {
            this.result = splitInlineChapterTitles(this.sourceText);
            this.$alert('success', this.$t('novelFormat.chapterSplitDone'));
        },
        reorderChapters() {
            const { output, chapters } = reorderChaptersByTitle(this.sourceText);
            if (!chapters) {
                this.$alert('info', this.$t('novelFormat.reorderNone'));
                return;
            }
            this.result = output;
            this.$alert('success', this.$t('novelFormat.reorderDone', { count: chapters }));
        },
        copyResult() {
            const text = this.result || '';
            if (!text) return;
            if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(text)
                    .then(() => this.$alert('success', this.$t('novelFormat.copied')))
                    .catch(() => this.$alert('error', this.$t('novelFormat.copyFailed')));
            } else {
                const el = document.createElement('textarea');
                el.value = text;
                document.body.appendChild(el);
                el.select();
                document.execCommand('copy');
                document.body.removeChild(el);
                this.$alert('success', this.$t('novelFormat.copied'));
            }
        },
        exportFile() {
            const text = this.result || '';
            if (!text) return;
            const name = `${(this.currentBook && this.currentBook.title) || 'novel'}.txt`;
            const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = name.replace(/[\\/:*?"<>|]/g, '_');
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            setTimeout(() => URL.revokeObjectURL(url), 1000);
        },
        close() {
            this.stopAuto();
            this.show = false;
        },
    },
};
</script>

<style scoped>
.nf-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 12px;
    margin-bottom: 8px;
}
.nf-head-main {
    display: flex;
    align-items: baseline;
    gap: 10px;
    min-width: 0;
}
.nf-book-title {
    color: rgba(0, 0, 0, 0.6);
    max-width: 420px;
}.nf-head-meta {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    justify-content: flex-end;
    gap: 6px;
    white-space: nowrap;
}
.nf-percent {
    font-weight: 600;
    color: #2d6d4b;
    margin-left: 6px;
}
.nf-card {
    border-radius: 8px;
}
.nf-card-title {
    font-size: 14px;
    font-weight: 600;
    padding-bottom: 4px;
}
.nf-text >>> textarea {
    font-family: Consolas, Monaco, "Courier New", monospace;
    font-size: 12px;
    line-height: 1.55;
}
.nf-stats {
    display: flex;
    align-items: center;
    font-size: 11px;
    color: rgba(0, 0, 0, 0.6);
    margin-top: 6px;
}
.nf-group-title {
    font-size: 12px;
    font-weight: 600;
    color: rgba(0, 0, 0, 0.6);
    margin-bottom: 4px;
}
.nf-switch-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    font-size: 13px;
    min-height: 36px;
}
.nf-switch-row .v-input--switch {
    margin-top: 0;
}
.nf-sub {
    padding-left: 16px;
}
.nf-hint {
    font-size: 11px;
    color: rgba(0, 0, 0, 0.55);
    line-height: 1.3;
}
.nf-field-label {
    font-size: 12px;
    color: rgba(0, 0, 0, 0.7);
    margin-bottom: 4px;
}
.nf-toggle {
    flex-wrap: wrap;
}
.nf-summary {
    text-align: center;
    padding: 48px 0;
}

.nf-rules {
    margin-top: 12px;
    padding-top: 8px;
    border-top: 1px solid rgba(0, 0, 0, 0.08);
    font-size: 11px;
    line-height: 1.6;
    color: rgba(0, 0, 0, 0.55);
}
.nf-rules-title {
    font-weight: 600;
    margin-bottom: 2px;
}
.nf-rules-list {
    margin: 0;
    padding-left: 18px;
}

.nf-author-row {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 8px;
}
.nf-author-label {
    font-size: 13px;
    white-space: nowrap;
}
.nf-author-input {
    flex: 1 1 auto;
    min-width: 0;
}
.nf-author-row .v-input--switch {
    flex: 0 0 auto;
    margin-top: 0;
}
.theme--dark .nf-author-label {
    color: rgba(255, 255, 255, 0.7);
}

/* ---- 暗色主题：自定义文字色必须跟着全局主题走，否则黑字落在深色卡片上看不见 ---- */
.theme--dark .nf-book-title,
.theme--dark .nf-group-title,
.theme--dark .nf-field-label {
    color: rgba(255, 255, 255, 0.7);
}
.theme--dark .nf-stats {
    color: rgba(255, 255, 255, 0.7);
}
.theme--dark .nf-hint {
    color: rgba(255, 255, 255, 0.55);
}
.theme--dark .nf-rules {
    border-top-color: rgba(255, 255, 255, 0.12);
    color: rgba(255, 255, 255, 0.55);
}
.theme--dark .nf-percent {
    color: #81c784;
}
.theme--dark .nf-summary .grey--text,
.theme--dark .nf-empty {
    color: rgba(255, 255, 255, 0.7) !important;
}

</style>
