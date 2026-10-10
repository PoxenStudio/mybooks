<template>
    <v-card>
        <v-card-title> {{ $t('imports.title') }} </v-card-title>
        <v-card-text>
        <div v-html="$t('imports.instructions', {scan_dir: scan_dir})"></div>
        <div v-html="$t('imports.note')"></div>
        <div v-html="$t('imports.calibre')"></div>
        </v-card-text>
        <v-card-actions class="flex-column align-stretch">
            <v-row no-gutters class="w-100">
                <v-col cols="12" class="d-flex flex-wrap ga-2 mb-2">
                    <v-btn
                        :disabled="loading"
                        color="primary"
                        @click="getDataFromApi"
                        class="flex-shrink-0"
                        :icon="$vuetify.breakpoint.xs"
                    >
                        <v-icon>mdi-reload</v-icon>
                        <span v-if="!$vuetify.breakpoint.xs">{{ $t('imports.refresh') }}</span>
                    </v-btn>
                    <template v-if="bulkStatus">
                        <v-btn
                            :disabled="loading || bulkDeleting"
                            :outlined="$vuetify.breakpoint.xs"
                            color="#2d6d4b"
                            @click="importBooks"
                            class="flex-shrink-0"
                            :icon="$vuetify.breakpoint.xs"
                        >
                            <v-icon>mdi-import</v-icon>
                            <span v-if="!$vuetify.breakpoint.xs">{{ $t('imports.import_bulk') }}</span>
                        </v-btn>
                    </template>
                    <template v-else-if="selected.length > 0">
                        <v-btn
                            :disabled="loading || bulkDeleting"
                            :outlined="$vuetify.breakpoint.xs"
                            color="#2d6d4b"
                            @click="importBooks"
                            class="flex-shrink-0"
                            :icon="$vuetify.breakpoint.xs"
                        >
                            <v-icon>mdi-import</v-icon>
                            <span v-if="!$vuetify.breakpoint.xs">{{ $t('imports.import_selected') }}</span>
                        </v-btn>
                    </template>
                    <template v-else>
                        <v-btn
                            :disabled="loading || bulkDeleting"
                            :outlined="$vuetify.breakpoint.xs"
                            color="#2d6d4b"
                            @click="importBooks"
                            class="flex-shrink-0"
                            :icon="$vuetify.breakpoint.xs"
                        >
                            <v-icon>mdi-import</v-icon>
                            <span v-if="!$vuetify.breakpoint.xs">{{ $t('imports.import_all') }}</span>
                        </v-btn>
                    </template>
                    <v-btn
                        :disabled="loading || bulkDeleting"
                        :outlined="$vuetify.breakpoint.xs"
                        color="purple darken-1"
                        @click="importAudiobooks"
                        class="flex-shrink-0"
                        :icon="$vuetify.breakpoint.xs"
                    >
                        <v-icon>mdi-headphones</v-icon>
                        <span v-if="!$vuetify.breakpoint.xs">{{ $t('imports.import_audiobooks') }}</span>
                    </v-btn>
                    <v-btn
                        v-if="allowPhysicalBooks"
                        :disabled="loading || bulkDeleting"
                        :outlined="$vuetify.breakpoint.xs"
                        color="secondary"
                        @click="showBatchAddDialog"
                        class="flex-shrink-0"
                        :icon="$vuetify.breakpoint.xs"
                    >
                        <v-icon>mdi-book-plus-multiple</v-icon>
                        <span v-if="!$vuetify.breakpoint.xs">{{ $t('imports.batch_add_books') }}</span>
                    </v-btn>
                    <v-btn
                        v-if="importing || bulkDeleting"
                        :outlined="$vuetify.breakpoint.xs"
                        color="error"
                        @click="cancelImport"
                        class="flex-shrink-0"
                        :icon="$vuetify.breakpoint.xs"
                    >
                        <v-icon>mdi-cancel</v-icon>
                        <span v-if="!$vuetify.breakpoint.xs">{{ bulkDeleting ? $t('imports.cancel_bulk_delete') : $t('imports.cancel_import') }}</span>
                    </v-btn>
                    <template v-if="selected.length > 0">
                        <v-btn
                            :disabled="loading || bulkDeleting"
                            :outlined="$vuetify.breakpoint.xs"
                            color="primary"
                            @click="deleteRecord"
                            class="flex-shrink-0"
                            :icon="$vuetify.breakpoint.xs"
                        >
                            <v-icon>mdi-delete</v-icon>
                            <span v-if="!$vuetify.breakpoint.xs">{{ $t('imports.delete') }}</span>
                        </v-btn>
                    </template>
                    <spacer></spacer>
                </v-col>
            </v-row>
            <v-row no-gutters class="w-100">
                <v-col cols="12" sm="6" md="4" class="mb-2">
                    <v-select
                        v-model="skip_last_dirs"
                        :items="scanScopeOptionsLocalized"
                        :label="$t('imports.scan_scope')"
                        item-text="text"
                        item-value="value"
                        dense
                        outlined
                        hide-details
                    ></v-select>
                </v-col>
                <v-col cols="12" sm="6" md="4" class="mb-2">
                    <v-select
                        v-model="bulkStatus"
                        :items="bulkStatusOptionsLocalized"
                        :label="$t('imports.bulk_select_label')"
                        :clearable="true"
                        dense
                        outlined
                        hide-details
                    ></v-select>
                </v-col>
                <v-col cols="12" sm="6" md="4" class="mb-2">
                    <v-checkbox
                        v-model="importSole"
                        :label="$t('imports.import_sole_option')"
                        :disabled="loading || bulkDeleting"
                        hide-details
                        class="mt-1"
                    ></v-checkbox>
                </v-col>
            </v-row>
        </v-card-actions>
        <v-progress-linear
            v-if="importing || batchAdding || audioImporting || bulkDeleting"
            :value="progressPercent"
            height="24"
            color="green"
            background-color="green"
            style="opacity: 1;"
            class="mb-4"
        >
            <strong class="white--text">{{ progressPrefix }} {{ count_processed }} / {{ count_total }} ({{ progressPercent }}%)</strong>
        </v-progress-linear>
        <v-card-text>
            <div v-if="bulkStatus">{{ $t('imports.bulk_hint') }}</div>
            <div v-else-if="selected.length == 0">{{ $t('imports.select_files') }}</div>
            <div v-else>{{ $t('imports.selected_count', { count: selected.length }) }}</div>
        </v-card-text>
        <v-tabs v-model="filter_type" @change="getDataFromApi">
            <v-tab href="#todo">{{ $t('imports.todo', { count: count_todo }) }}</v-tab>
            <v-tab href="#done">{{ $t('imports.done', { count: count_done }) }}</v-tab>
        </v-tabs>
        <v-data-table
            dense
            class="elevation-1 text-body-2"
            show-select
            v-model="selected"
            item-key="hash"
            :search="search"
            :headers="headers"
            :items="items"
            :options.sync="options"
            :server-items-length="total"
            sort-by="create_time"
            sort-desc="true"
            :loading="loading"
            :page.sync="page"
            :items-per-page="100"
            :footer-props="{ 'items-per-page-options': [10, 50, 100, 1000, 5000, 10000] }"
            @item-selected="onUserSelect"
            @toggle-select-all="onUserSelect"
        >
            <template v-slot:top>
                <v-data-footer
                    :options.sync="options"
                    :pagination="topPagination"
                    :items-per-page-options="[10, 50, 100, 1000, 5000, 10000]"
                    @update:options="options = $event"
                />
            </template>
            <template v-slot:item.status="{ item }">
                <v-chip small v-if="item.status == 'ready'" class="success">{{ $t('imports.status.ready') }}</v-chip>
                <v-chip small v-else-if="item.status == 'exist'" class="lighten-4">{{ $t('imports.status.exist') }}</v-chip>
                <v-chip small v-else-if="item.status == 'imported'" class="primary">{{ $t('imports.status.imported') }}</v-chip>
                <v-chip small v-else-if="item.status == 'new'" class="grey">{{ $t('imports.status.new') }}</v-chip>
                <v-chip small v-else-if="item.status == 'drop'" class="warning" style="color:black;">{{ $t('imports.status.drop') }}</v-chip>
                <v-chip small v-else-if="item.status == 'invalid'" class="error" style="color:black;">{{ item.path.startsWith('/') ? $t('imports.status.invalid') : $t('imports.status.isbn_invalid') }}</v-chip>
                <v-chip small v-else-if="item.status == 'missed'" class="error" style="color:black;">{{ $t('imports.status.missed') }}</v-chip>
                <v-chip small v-else-if="item.status == 'permission'" class="error" style="color:black;">{{ $t('imports.status.permission') }}</v-chip>
                <v-chip small v-else class="info">{{ item.status }}</v-chip>
            </template>
            <template v-slot:item.path="{ item }">
                <v-icon v-if="item.import_type === 2" color="purple">mdi-headphones</v-icon>
                <v-icon v-else color="green">mdi-file-document</v-icon>
                <span>{{ item.path }}</span>
            </template>
            <template v-slot:item.title="{ item }">
                {{ $t('imports.book_title') }}<span v-if="item.book_id == 0"> {{ item.title }} </span>
                <a v-else target="_blank" :href="`/book/${item.book_id}`">{{ item.title }}</a> <br />
                {{ $t('imports.book_author') }}{{ item.author }}
            </template>
        </v-data-table>

        <!-- Ignored Errors from scan -->
        <v-card-text v-if="ignored_errors.length > 0">
            <v-alert type="warning" dense outlined icon="mdi-alert">
                <div class="mb-1">{{ $t('imports.ignored_errors_title') }}</div>
                <ul class="mt-1 mb-0">
                    <li v-for="(dir, i) in ignored_errors" :key="i" class="text-body-2">{{ dir }}</li>
                </ul>
                <div class="mt-1 caption">{{ $t('imports.ignored_errors_hint') }}</div>
            </v-alert>
        </v-card-text>

        <!-- Batch Add Dialog -->
        <AppDialog
            v-model="batchAddDialog"
            :persistent="false"
            type="action"
            :title="$t('imports.batch_add_dialog_title')"
            max-width="600px"
            :dismiss-disabled="batchAdding"
            confirm-icon="mdi-upload"
            :confirm-text="batchAdding ? $t('imports.batch_add_processing') : $t('imports.batch_add_start')"
            :confirm-loading="batchAdding"
            :confirm-disabled="!csvFile || batchAdding"
            @confirm="startBatchAdd"
        >
            <p>{{ $t('imports.batch_add_dialog_description') }}</p>
            <ul>
                <li>{{ $t('imports.batch_add_dialog_rule1') }}</li>
                <li>{{ $t('imports.batch_add_dialog_rule2') }}</li>
                <li>{{ $t('imports.batch_add_dialog_rule3') }}</li>
                <li>{{ $t('imports.batch_add_dialog_rule4') }}</li>
            </ul>
            <v-file-input
                v-model="csvFile"
                :label="$t('imports.batch_add_select_file')"
                accept=".csv"
                prepend-icon="mdi-file-delimited"
                :disabled="batchAdding"
            ></v-file-input>
        </AppDialog>

        <!-- Import by dirs dialog -->
        <AppDialog
            v-model="dirDialog"
            :persistent="false"
            type="action"
            :title="$t('imports.dirs_dialog_title')"
            max-width="600px"
            :confirm-text="$t('imports.dirs_dialog_confirm')"
            :confirm-disabled="selectedDirs.length == 0 || dirsLoading || loading"
            @confirm="importByDirs"
        >
            <p>{{ $t('imports.dirs_dialog_description', { scan_dir: scan_dir }) }}</p>
            <v-autocomplete
                v-model="selectedDirs"
                :items="availableDirs"
                :label="$t('imports.dirs_select_label')"
                :no-data-text="$t('imports.dirs_empty')"
                :loading="dirsLoading"
                multiple
                small-chips
                deletable-chips
                dense
                outlined
                hide-details
            ></v-autocomplete>
        </AppDialog>

        <!-- Bulk delete dialog -->
        <AppDialog
            v-model="bulkDeleteDialog"
            :persistent="false"
            type="confirm"
            :title="$t('imports.bulk_delete_title')"
            max-width="520px"
            :confirm-text="$t('imports.bulk_delete_confirm')"
            confirm-color="error"
            :confirm-disabled="bulkDeleting"
            @confirm="runBulkDelete"
        >
            <p>{{ $t('imports.bulk_delete_desc', { count: bulkDeleteCount, status: bulkStatusLabel }) }}</p>
            <p>{{ $t('imports.bulk_delete_audiobook_note') }}</p>
            <v-checkbox
                v-model="bulkDeleteFiles"
                :label="$t('imports.bulk_delete_files_option')"
                color="error"
                hide-details
                class="mt-0"
            ></v-checkbox>
            <p v-if="bulkDeleteFiles" class="error--text mb-0">{{ $t('imports.bulk_delete_files_warn') }}</p>
            <p v-else class="grey--text mb-0">{{ $t('imports.bulk_delete_records_only') }}</p>
        </AppDialog>
    </v-card>
</template>

<script>
export default {
    data: () => ({
        filter_type: "todo",
        selected: [],
        scan_dir: "/data/books/imports/",
        search: "",
        page: 1,
        items: [],
        total: 0,
        loading: false,
        importing: false,
        batchAdding: false,
        audioImporting: false,
        batchAddDialog: false,
        csvFile: null,
        dirDialog: false,
        dirsLoading: false,
        availableDirs: [],
        selectedDirs: [],
        skip_last_dirs: 0,
        prevScope: 0,
        bulkStatus: null,
        bulkDeleteDialog: false,
        bulkDeleting: false,
        bulkDeleteFiles: false,
        importSole: false,
        statusCounts: {},
        scanScopeOptions: [
            { text: "imports.scan_scope_all", value: 0 },
            { text: "imports.scan_scope_full_noskip", value: 4 },
            { text: "imports.scope_by_dirs", value: 3 },
        ],
        options: {},
        count_todo: 0,
        count_done: 0,
        count_total: 0,
        count_processed: 0,
        ignored_errors: [],
        headers: [
            { text: "状态", sortable: true, value: "status" },
            { text: "路径", sortable: true, value: "path" },
            { text: "扫描信息", sortable: false, value: "title" },
            { text: "时间", sortable: true, value: "create_time", width: "200px" },
        ],
    }),
    watch: {
        options: {
            handler() {
                this.getDataFromApi();
            },
            deep: true,
        },
        skip_last_dirs(val) {
            // 「按分类导入」并入扫描范围：选中即弹目录选择框；对话框关闭后回退到原范围
            if (val === 3) {
                this.openDirDialog();
            } else {
                this.prevScope = val;
            }
        },
        dirDialog(val) {
            if (!val && this.skip_last_dirs === 3) {
                this.skip_last_dirs = this.prevScope;
            }
        },
        bulkStatus(val) {
            if (!val) {
                return;
            }
            // 批量选择是服务端选择器的可视提示：只勾选当前页匹配行，动作作用于跨页全量
            this.applyBulkVisualSelection();
        },
    },
    mounted() {
        this.checkCurrentState();
        this.getDataFromApi();
    },
    computed: {
        allowPhysicalBooks() {
            return !!(this.$store.state.sys && this.$store.state.sys.allow && this.$store.state.sys.allow.physical_books);
        },
        pageCount: function () {
            return parseInt(this.total / 20);
        },
        progressPercent() {
            if (!this.count_total) {
                return 0;
            }
            const pct = Math.round((this.count_processed / this.count_total) * 100);
            if (pct < 0) return 0;
            if (pct > 100) return 100;
            return pct;
        },
        topPagination() {
            const { page = 1, itemsPerPage = 100 } = this.options;
            const pageCount = itemsPerPage <= 0 ? 1 : Math.ceil(this.total / itemsPerPage);
            return {
                page,
                itemsPerPage,
                pageStart: (page - 1) * itemsPerPage,
                pageStop: Math.min(page * itemsPerPage, this.total),
                pageCount,
                itemsLength: this.total,
            };
        },
        progressPrefix() {
            if (this.importing) return this.$t('imports.progressImporting');
            if (this.batchAdding) return this.$t('imports.progressBatchAdding');
            if (this.audioImporting) return this.$t('imports.progressAudioImporting');
            if (this.bulkDeleting) return this.$t('imports.progressBulkDeleting');
            return "";
        },
        scanScopeOptionsLocalized() {
            return this.scanScopeOptions.map((item) => ({
                text: this.$t(item.text),
                value: item.value,
            }));
        },
        bulkStatusOptionsLocalized() {
            // 选项不带数量：批量动作的作用范围由后端选择器决定（跨页全量）
            return [
                { text: this.$t("imports.bulk_all_todo"), value: "todo" },
                { text: this.$t("imports.status.ready"), value: "ready" },
                { text: this.$t("imports.status.new"), value: "new" },
                { text: this.$t("imports.status.drop"), value: "drop" },
                { text: this.$t("imports.status.exist"), value: "exist" },
                { text: this.$t("imports.status.invalid"), value: "invalid" },
                { text: this.$t("imports.status.missed"), value: "missed" },
                { text: this.$t("imports.status.permission"), value: "permission" },
            ];
        },
        bulkStatusLabel() {
            if (!this.bulkStatus) return "";
            if (this.bulkStatus === "todo") return this.$t("imports.bulk_all_todo");
            return this.$t("imports.status." + this.bulkStatus);
        },
        bulkDeleteCount() {
            if (!this.bulkStatus) return 0;
            // todo 口径必须与后端 not_in([IMPORTED]) 一致（含存在同名），直接对 counts 求和
            if (this.bulkStatus === "todo") {
                let sum = 0;
                Object.keys(this.statusCounts || {}).forEach((k) => {
                    if (k !== "imported") sum += this.statusCounts[k] || 0;
                });
                return sum;
            }
            return (this.statusCounts && this.statusCounts[this.bulkStatus]) || 0;
        },
    },
    methods: {
        getDataFromApi() {
            const { sortBy, sortDesc, page, itemsPerPage } = this.options;

            var data = new URLSearchParams();
            data.append("filter", this.filter_type);
            if (page != undefined) {
                data.append("page", page);
            }
            if (sortBy != undefined) {
                data.append("sort", sortBy);
            }
            if (sortDesc != undefined) {
                data.append("desc", sortDesc);
            }
            if (itemsPerPage != undefined) {
                data.append("num", itemsPerPage);
            }
            this.$backend("/admin/import/list?" + data.toString())
                .then((rsp) => {
                    if (rsp.err != "ok") {
                        this.items = [];
                        this.total = 0;
                        alert(rsp.msg);
                        return false;
                    }
                    this.items = rsp.items;
                    this.total = rsp.total;
                    this.scan_dir = rsp.scan_dir;
                    this.count_done = rsp.summary.done;
                    this.count_todo = rsp.summary.todo;
                    this.statusCounts = rsp.summary.counts || {};
                    this.count_total = 0;
                    this.importing = rsp.importing;
                    if (rsp.ignored_errors && rsp.ignored_errors.length > 0) {
                        this.ignored_errors = rsp.ignored_errors;
                    }
                    if (this.bulkStatus) {
                        this.applyBulkVisualSelection();
                    }
                }).finally(() => {
                    if (!this.importing && !this.audioImporting && !this.batchAdding && !this.bulkDeleting) {
                        this.loading = false;
                    }
                });
        },
        loopCheckStatus(url, callback) {
            setTimeout(() => {
                this.$backend(url)
                    .then((rsp) => {
                        if (rsp.err != "ok") {
                            this.$alert("error", rsp.msg);
                            return;
                        }
                        if (callback(rsp)) {
                            setTimeout(() => {
                                this.loopCheckStatus(url, callback);
                            }, 1000);
                        } else {
                            this.getDataFromApi();
                        }
                    })
            }, 2000);
        },
        beginImportPolling() {
            this.loopCheckStatus("/admin/import/status", (rsp) => {
                this.import = rsp.status;
                this.count_done = rsp.summary.done;
                this.count_todo = rsp.summary.todo;

                this.count_total = rsp.status.total;
                this.count_processed = rsp.status.processed;

                this.importing = rsp.importing || false;
                if (!this.importing) {
                    this.loading = false;
                    return false;
                }
                this.loading = true;
                return true;
            });
        },
        runImport(payload) {
            if (this.bulkDeleting) {
                this.$alert("warning", this.$t("imports.bulk_delete_running"));
                return Promise.resolve(false);
            }
            this.loading = true;
            // 本次导入的书籍全部设为私藏，作用于本次运行的所有导入形态（全部/勾选/状态筛选/按目录）
            return this.$backend("/admin/import/run", {
                method: "POST",
                body: JSON.stringify(Object.assign({ sole: this.importSole }, payload)),
            }).then((rsp) => {
                if (rsp.err !== "ok") {
                    this.$alert("error", rsp.msg);
                    this.loading = false;
                    return false;
                }
                this.selected = [];
                this.bulkStatus = null;
                this.importSole = false;
                this.beginImportPolling();
                return true;
            }).catch(() => {
                this.loading = false;
                return false;
            });
        },
        importBooks() {
            if (this.bulkStatus) {
                // 服务端选择器：按状态跨页全量，后端固定不走 force（哈希复用、不重算）
                const filelist = this.bulkStatus === "ready" ? "ready" : { filter: this.bulkStatus };
                return this.runImport({ filelist });
            }
            const filelist = this.selected.length > 0
                ? this.selected.map((v) => v.path)
                : "all";
            // 手动勾选保持既有语义：强制重导（忽略哈希/导入记录去重）
            return this.runImport({
                filelist: filelist,
                skip_last_dirs: this.skip_last_dirs,
                force: this.selected.length > 0
            });
        },
        importByDirs() {
            if (this.selectedDirs.length == 0) {
                return Promise.resolve(false);
            }
            return this.runImport({ filelist: { dirs: this.selectedDirs } }).then((ok) => {
                if (ok) {
                    this.dirDialog = false;
                }
                return ok;
            });
        },
        applyBulkVisualSelection() {
            if (!this.bulkStatus) {
                return;
            }
            // 有声书记录（import_type=2）不被服务端选择器与批量删除覆盖，不参与可视勾选，
            // 否则勾上了却删不掉（列表仍显示它们，只是不进批量范围）
            const matches = this.items.filter(
                (item) =>
                    item.import_type !== 2 &&
                    (this.bulkStatus === "todo" ? item.status !== "imported" : item.status === this.bulkStatus)
            );
            this.selected = matches;
        },
        onUserSelect() {
            // 手动勾选/表头全选即退出批量模式，恢复逐条 force 语义
            if (this.bulkStatus) {
                this.bulkStatus = null;
            }
        },
        openDirDialog() {
            this.selectedDirs = [];
            this.dirDialog = true;
            this.dirsLoading = true;
            this.$backend("/admin/import/dirs")
                .then((rsp) => {
                    if (rsp.err === "ok") {
                        this.availableDirs = rsp.dirs || [];
                    } else {
                        this.$alert("error", rsp.msg);
                        this.availableDirs = [];
                    }
                })
                .catch(() => {
                    this.$alert("error", this.$t("imports.dirs_load_failed"));
                    this.availableDirs = [];
                })
                .finally(() => {
                    this.dirsLoading = false;
                });
        },
        cancelImport() {
            this.$backend("/admin/import/cancel", {
                method: "POST",
            }).then((rsp) => {
                    this.$alert("success", rsp.msg);
                    this.getDataFromApi();
                })
                .catch((err) => {
                    this.$alert("error", err.message);
                })
        },
        deleteRecord() {
            if (this.bulkStatus) {
                // 批量模式：删除全部匹配记录（跨页全量）；是否连源文件一起删由复选框决定，
                // 默认不勾——真删是不可恢复动作，必须显式确认
                this.bulkDeleteFiles = false;
                this.bulkDeleteDialog = true;
                return;
            }
            this.loading = true;
            this.$backend("/admin/import/delete", {
                method: "POST",
                body: JSON.stringify({
                    hashlist: this.selected.map((v) => {
                        return v.hash;
                    }),
                }),
            }).then((rsp) => {
                    if (rsp.err !== "ok") {
                        this.$alert("error", rsp.msg);
                    }
                    this.selected = [];
                    this.getDataFromApi();
                })
                .finally(() => {
                    this.loading = false;
                });
        },
        runBulkDelete() {
            if (!this.bulkStatus || this.bulkDeleting) {
                return;
            }
            this.bulkDeleting = true;
            this.loading = true;
            this.$backend("/admin/import/bulk_delete", {
                method: "POST",
                body: JSON.stringify({
                    status: this.bulkStatus,
                    delete_files: this.bulkDeleteFiles,
                }),
            }).then((rsp) => {
                if (rsp.err !== "ok") {
                    this.$alert("error", rsp.msg);
                    this.bulkDeleting = false;
                    this.loading = false;
                    return;
                }
                this.bulkDeleteDialog = false;
                this.loopBulkDeleteStatus();
            }).catch(() => {
                this.bulkDeleting = false;
                this.loading = false;
            });
        },
        loopBulkDeleteStatus() {
            // 专用轮询：err 与网络失败都必须复位 bulkDeleting/loading，进度条不能永挂
            setTimeout(() => {
                this.$backend("/admin/import/bulk_delete/status")
                    .then((st) => {
                        if (st.err !== "ok") {
                            this.$alert("error", st.msg);
                            this.bulkDeleting = false;
                            this.loading = false;
                            return;
                        }
                        const state = st.state || {};
                        this.bulkDeleting = st.bulk_deleting || false;
                        this.count_total = state.total || 0;
                        this.count_processed = state.processed || 0;
                        if (!st.bulk_deleting) {
                            this.loading = false;
                            this.bulkStatus = null;
                            this.selected = [];
                            if (state.cancelled) {
                                // 用户主动取消：已提交批次不回滚，展示已处理条数
                                this.$alert("warning", this.$t("imports.bulk_delete_cancelled", {
                                    total: state.processed || 0,
                                }));
                            } else if (state.err) {
                                this.$alert("error", state.err);
                            } else {
                                this.$alert("success", this.$t("imports.bulk_delete_done", {
                                    total: state.processed || 0,
                                    files: state.deleted_files || 0,
                                }));
                            }
                            this.getDataFromApi();
                            return;
                        }
                        this.loading = true;
                        this.loopBulkDeleteStatus();
                    })
                    .catch(() => {
                        this.$alert("error", this.$t("imports.bulk_delete_status_failed"));
                        this.bulkDeleting = false;
                        this.loading = false;
                    });
            }, 2000);
        },
        checkCurrentState() {
            // Check scan status first
            this.$backend("/admin/import/status")
                .then((rsp) => {
                    if (rsp.err !== "ok") {
                        return;
                    }
                    if (rsp.status && rsp.importing) {
                        this.loading = true;
                        this.loopCheckStatus("/admin/import/status", (rsp) => {
                            this.scan = rsp.status;
                            this.count_done = rsp.summary.done;
                            this.count_todo = rsp.summary.todo;
                            this.count_total = rsp.status.total;
                            this.count_processed = rsp.status.processed;
                            this.importing = rsp.importing;
                            if (!rsp.importing) {
                                this.loading = false;
                                if (rsp.ignored_errors && rsp.ignored_errors.length > 0) {
                                    this.ignored_errors = rsp.ignored_errors;
                                } else {
                                    this.ignored_errors = [];
                                }
                                return false;
                            }
                            this.loading = true;
                            return true;
                        });
                    } else {
                        this.importing = false;
                    }
                    if (rsp.ignored_errors && rsp.ignored_errors.length > 0) {
                        this.ignored_errors = rsp.ignored_errors;
                    } else {
                        this.ignored_errors = [];
                    }
                });

            // Check audio import status
            this.$backend("/admin/audio_import/status")
                .then((rsp) => {
                    if (rsp.err !== "ok") {
                        return;
                    }
                    if (rsp.audio_importing) {
                        this.audioImporting = true;
                        this.loading = true;
                        this.loopCheckStatus("/admin/audio_import/status", (rsp) => {
                            this.count_total = rsp.status.total || 0;
                            this.count_processed = (rsp.status.imported || 0) + (rsp.status.exist || 0);
                            this.count_done = rsp.summary.done;
                            this.count_todo = rsp.summary.todo;
                            this.audioImporting = rsp.audio_importing || false;
                            if (!rsp.audio_importing) {
                                this.loading = false;
                                return false;
                            }
                            this.loading = true;
                            return true;
                        });
                    } else {
                        this.audioImporting = false;
                    }
                });

            // Check batch add status
            this.$backend("/admin/batch_add/status")
                .then((rsp) => {
                    if (rsp.err !== "ok") {
                        return;
                    }

                    if (rsp.batch_adding) {
                        this.batchAdding = true;
                        this.loading = true;
                        this.loopCheckStatus("/admin/batch_add/status", (rsp) => {
                            this.count_total = rsp.status.total || 0;
                            this.count_processed = rsp.status.processed || 0;
                            this.count_done = rsp.summary.done;
                            this.count_todo = rsp.summary.todo;
                            this.batchAdding = rsp.batch_adding || false;

                            if (!rsp.batch_adding) {
                                this.loading = false;
                                return false;
                            }
                            this.loading = true;
                            return true;
                        });
                    } else {
                        this.batchAdding = false;
                    }
                });

            // Check bulk delete status (刷新后恢复轮询)
            this.$backend("/admin/import/bulk_delete/status")
                .then((rsp) => {
                    if (rsp.err !== "ok") {
                        return;
                    }
                    if (rsp.bulk_deleting) {
                        this.bulkDeleting = true;
                        this.loading = true;
                        this.loopBulkDeleteStatus();
                    }
                });
        },
        checkImportState() {
            this.$backend("/admin/import/status")
                .then((rsp) => {
                    if (rsp.err !== "ok") {
                        return;
                    }

                    // If importing is in progress
                    if (rsp.status && rsp.importing > 0) {
                        this.loading = true;
                        this.loopCheckStatus("/admin/import/status", (rsp) => {
                            this.import = rsp.status;
                            this.count_done = rsp.summary.done;
                            this.count_todo = rsp.summary.todo;
                            this.count_total = rsp.status.total;
                            this.count_processed = rsp.status.processed;
                            this.importing = rsp.importing;
                            if (!rsp.importing || this.import.ready === 0) {
                                this.loading = false;
                                return false;
                            }
                            this.loading = true;
                            return true;
                        });
                    }
                });
        },
        importAudiobooks() {
            this.loading = true;
            this.$backend("/admin/audio_import/run", { method: "POST" })
                .then((rsp) => {
                    if (rsp.err !== "ok") {
                        this.$alert("error", rsp.msg);
                        this.loading = false;
                        return;
                    }
                    this.audioImporting = true;
                    this.loopCheckStatus("/admin/audio_import/status", (rsp) => {
                        this.count_total = rsp.status.total || 0;
                        this.count_processed = this.count_total - (rsp.status.ready || 0);
                        this.count_done = rsp.summary.done;
                        this.count_todo = rsp.summary.todo;
                        this.audioImporting = rsp.audio_importing || false;
                        if (!rsp.audio_importing) {
                            this.loading = false;
                            return false;
                        }
                        this.loading = true;
                        return true;
                    });
                });
        },
        showBatchAddDialog() {
            this.batchAddDialog = true;
            this.csvFile = null;
        },
        startBatchAdd() {
            if (!this.csvFile) {
                this.$alert("error", this.$t('imports.batch_add_no_file'));
                return;
            }

            this.batchAdding = true;
            this.loading = true;

            // 立即创建 FormData，避免文件引用问题
            const formData = new FormData();
            // 确保文件名被正确传递
            formData.append('csv_file', this.csvFile, this.csvFile.name);
            // 不要设置 Content-Type，让浏览器自动设置 multipart/form-data 边界
            this.$backend("/admin/batch_add/run", {
                method: "POST",
                body: formData,
            })
                .then((rsp) => {
                    if (rsp.err !== "ok") {
                        this.$alert("error", rsp.msg);
                        this.batchAdding = false;
                        this.loading = false;
                        return;
                    }

                    this.batchAddDialog = false;
                    this.csvFile = null;

                    // 开始轮询状态
                    this.loopCheckStatus("/admin/batch_add/status", (rsp) => {
                        this.count_total = rsp.status.total || 0;
                        this.count_processed = rsp.status.processed || 0;
                        this.count_done = rsp.summary.done;
                        this.count_todo = rsp.summary.todo;
                        this.batchAdding = rsp.batch_adding || false;

                        if (!rsp.batch_adding) {
                            this.loading = false;
                            this.getDataFromApi();
                            return false;
                        }
                        this.loading = true;
                        return true;
                    });
                })
                .catch((err) => {
                    console.error("Batch add error:", err);
                    this.$alert("error", err.message || "上传失败");
                    this.batchAdding = false;
                    this.loading = false;
                });
        },
    },
};
</script>

<style>
/* 确保间距工具类正常工作 */
.ga-2 > * {
    margin: 4px !important;
}
.ga-2 > *:first-child {
    margin-left: 0 !important;
}
.ga-2 > *:last-child {
    margin-right: 0 !important;
}

/* 小屏时调大图标的大小 */
@media (max-width: 600px) {
    /* 调大图标按钮的大小 */
    .v-btn--icon {
        width: 48px !important;
        height: 48px !important;
    }

    /* 调大图标本身的大小 */
    .v-btn--icon .v-icon {
        font-size: 24px !important;
    }
}
</style>