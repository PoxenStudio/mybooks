<template>
    <v-card>
        <v-card-title> {{ $t('imports.title') }} <v-chip small class="primary">Beta</v-chip> </v-card-title>
        <v-card-text>
        {{ $t('imports.instructions', {scan_dir: scan_dir}) }}<br/>
        {{ $t('imports.note') }}<br/>
        {{ $t('imports.calibre') }}
        </v-card-text>
        <v-card-actions>
            <v-btn :disabled="loading" outlined color="primary" @click="getDataFromApi"><v-icon>mdi-reload</v-icon>{{ $t('imports.refresh') }}</v-btn>
            <v-btn :disabled="loading" color="primary" @click="scan_books"><v-icon>mdi-file-find</v-icon>{{ $t('imports.scan_books') }}</v-btn>
            <template v-if="selected.length > 0">
                <v-btn :disabled="loading" color="secondary" @click="import_books"><v-icon>mdi-import</v-icon>{{ $t('imports.import_selected') }}</v-btn>
                <v-btn :disabled="loading" outlined color="primary" @click="delete_record"><v-icon>mdi-delete</v-icon>{{ $t('imports.delete') }}</v-btn>
            </template>
            <template v-else>
                <v-btn :disabled="loading" color="warning" @click="import_books"><v-icon>mdi-import</v-icon>{{ $t('imports.import_all') }}</v-btn>
            </template>
        </v-card-actions>
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
            <template v-slot:item.status="{ item }">
                <v-chip small v-if="item.status == 'ready'" class="success">{{ $t('imports.status.ready') }}</v-chip>
                <v-chip small v-else-if="item.status == 'exist'" class="lighten-4">{{ $t('imports.status.exist') }}</v-chip>
                <v-chip small v-else-if="item.status == 'imported'" class="primary">{{ $t('imports.status.imported') }}</v-chip>
                <v-chip small v-else-if="item.status == 'new'" class="grey">{{ $t('imports.status.new') }}</v-chip>
                <v-chip small v-else class="info">{{ item.status }}</v-chip>
            </template>
            <template v-slot:item.title="{ item }">
                {{ $t('imports.book_title') }}<span v-if="item.book_id == 0"> {{ item.title }} </span>
                <a v-else target="_blank" :href="`/book/${item.book_id}`">{{ item.title }}</a> <br />
                {{ $t('imports.book_author') }}{{ item.author }}
            </template>
        </v-data-table>
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
        options: {},
        count_todo: 0,
        count_done: 0,
        headers: [
            { text: "ID", sortable: true, value: "id" },
            { text: "状态", sortable: true, value: "status" },
            { text: "路径", sortable: true, value: "path" },
            { text: "扫描信息", sortable: false, value: "title" },
            { text: "时间", sortable: true, value: "create_time", width: "200px" },
        ],
        progress: {
            done: 0,
            total: 0,
            status: "finish",
        },
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
        this.getDataFromApi();
    },
    computed: {
        pageCount: function () {
            return parseInt(this.total / 20);
        },
    },
    methods: {
        getDataFromApi() {
            this.loading = true;
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
            this.$backend("/admin/scan/list?" + data.toString())
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
                })
                .finally(() => {
                    this.loading = false;
                });
        },
        loop_check_status(url, callback) {
            setTimeout(() => {
                this.$backend(url)
                    .then((rsp) => {
                        if (rsp.err != "ok") {
                            this.$alert("error", rsp.msg);
                            return;
                        }
                        if (callback(rsp)) {
                            setTimeout(() => {
                                this.loop_check_status(url, callback);
                            }, 1000);
                        } else {
                            this.getDataFromApi();
                            this.$alert("info", "处理完毕！");
                        }
                    })
            }, 2000);
        },
        scan_books() {
            this.loading = true;
            this.$backend("/admin/scan/run", {
                method: "POST",
            }).then((rsp) => {
                    if (rsp.err !== "ok") {
                        this.$alert("error", rsp.msg);
                        return;
                    }

                    //this.check_scan_status();
                    this.loop_check_status("/admin/scan/status", (rsp) => {
                        this.scan = rsp.status;
                        this.count_done = rsp.summary.done;
                        this.count_todo = rsp.summary.todo;
                        if (this.scan.new === 0) {
                            this.loading = false;
                            return false;
                        }
                        this.loading = true;
                        return true;
                    });
                })
        },
        import_books() {
            this.loading = true;
            var hashlist = "all";
            if (this.selected.length > 0) {
                hashlist = this.selected.map((v) => {
                        return v.hash;
                    });
            }
            this.$backend("/admin/import/run", {
                method: "POST",
                body: JSON.stringify({
                    hashlist: hashlist,
                }),
            })
                .then((rsp) => {
                    if (rsp.err !== "ok") {
                        this.$alert("error", rsp.msg);
                    }

                    //this.check_import_status();
                    this.loop_check_status("/admin/import/status", (rsp) => {
                        this.import = rsp.status;
                        this.count_done = rsp.summary.done;
                        this.count_todo = rsp.summary.todo;
                        if (this.import.ready === 0) {
                            this.loading = false;
                            return false;
                        }
                        this.loading = true;
                        return true;
                    });
                    this.selected = [];
                })
        },
        delete_record() {
            console.log(this.selected);
            this.loading = true;
            this.$backend("/admin/scan/delete", {
                method: "POST",
                body: JSON.stringify({
                    hashlist: this.selected.map((v) => {
                        return v.hash;
                    }),
                }),
            })
                .then((rsp) => {
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
        mark_as(status) {
            this.loading = true;
            this.$backend("/admin/scan/mark", {
                method: "POST",
                body: JSON.stringify({ hashlist: this.selected, status: status }),
            })
                .then((rsp) => {
                    if (rsp.err !== "ok") {
                        this.$alert("error", rsp.msg);
                    }
                })
                .finally(() => {
                    this.loading = false;
                });
            this.items.map((v) => {
                if (this.selected.indexOf(v.hash)) {
                    v.status = status;
                }
            });
        },
    },
};
</script>
