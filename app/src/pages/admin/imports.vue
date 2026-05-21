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
                    <template v-if="selected.length > 0">
                        <v-btn
                            :disabled="loading"
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
                            :disabled="loading"
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
                        :disabled="loading"
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
                        :disabled="loading"
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
                        v-if="importing"
                        :outlined="$vuetify.breakpoint.xs"
                        color="error"
                        @click="cancelImport"
                        class="flex-shrink-0"
                        :icon="$vuetify.breakpoint.xs"
                    >
                        <v-icon>mdi-cancel</v-icon>
                        <span v-if="!$vuetify.breakpoint.xs">{{ $t('imports.cancel_import') }}</span>
                    </v-btn>
                    <template v-if="selected.length > 0">
                        <v-btn
                            :disabled="loading"
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
            </v-row>
        </v-card-actions>
        <v-progress-linear
            v-if="importing || batchAdding || audioImporting"
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
            <div v-if="selected.length == 0">{{ $t('imports.select_files') }}</div>
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
                <v-chip small v-else-if="item.status == 'invalid'" class="error" style="color:black;">{{ $t('imports.status.invalid') }}</v-chip>
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
        <v-dialog v-model="batchAddDialog" max-width="600px">
            <v-card>
                <v-card-title>{{ $t('imports.batch_add_dialog_title') }}</v-card-title>
                <v-card-text>
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
                </v-card-text>
                <v-card-actions>
                    <v-spacer></v-spacer>
                    <v-btn text @click="batchAddDialog = false" :disabled="batchAdding">{{ $t('common.cancel') }}</v-btn>
                    <v-btn color="primary" @click="startBatchAdd" :disabled="!csvFile || batchAdding">
                        <v-icon left v-if="!batchAdding">mdi-upload</v-icon>
                        <v-progress-circular v-if="batchAdding" indeterminate size="20" class="mr-2"></v-progress-circular>
                        {{ batchAdding ? $t('imports.batch_add_processing') : $t('imports.batch_add_start') }}
                    </v-btn>
                </v-card-actions>
            </v-card>
        </v-dialog>
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
        skip_last_dirs: 0,
        scanScopeOptions: [
            { text: "imports.scan_scope_all", value: 0 },
            { text: "imports.scan_scope_exclude_last", value: 1 },
            { text: "imports.scan_scope_exclude_all", value: 2 },
        ],
        options: {},
        count_todo: 0,
        count_done: 0,
        count_total: 0,
        count_processed: 0,
        ignored_errors: [],
        headers: [
            { text: "ID", sortable: true, value: "id" },
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
    },
    mounted() {
        this.checkCurrentState();
        this.getDataFromApi();
    },
    computed: {
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
            return "";
        },
        scanScopeOptionsLocalized() {
            return this.scanScopeOptions.map((item) => ({
                text: this.$t(item.text),
                value: item.value,
            }));
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
                    this.count_total = 0;
                    this.importing = rsp.importing;
                    if (rsp.ignored_errors && rsp.ignored_errors.length > 0) {
                        this.ignored_errors = rsp.ignored_errors;
                    }
                }).finally(() => {
                    if (!this.importing && !this.audioImporting && !this.batchAdding) {
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
        importBooks() {
            this.loading = true;
            var filelist = "all";
            if (this.selected.length > 0) {
                filelist = this.selected.map((v) => {
                        return v.path;
                    });
            }
            const payload = {
                filelist: filelist,
                skip_last_dirs: this.skip_last_dirs,
                force: this.selected.length > 0
            };
            this.$backend("/admin/import/run", {
                method: "POST",
                body: JSON.stringify(payload),
            })
                .then((rsp) => {
                    if (rsp.err !== "ok") {
                        this.$alert("error", rsp.msg);
                        this.loading = false;
                        return;
                    }

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
                    this.selected = [];
                })
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