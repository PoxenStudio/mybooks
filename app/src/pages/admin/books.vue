<template>
    <v-card>
        <v-card-title> {{ $t('admin.books.title') }}</v-card-title>
        <v-card-text> {{ $t('admin.books.description') }} </v-card-text>
        <v-card-actions class="pa-4">
            <!-- 第一行：主要操作按钮 -->
            <v-row no-gutters>
                <v-col cols="12" class="d-flex flex-wrap ga-2 mb-2">
                    <v-btn
                        :disabled="loading"
                        outlined
                        color="primary"
                        @click="getDataFromApi"
                        class="flex-shrink-0"
                        :icon="$vuetify.breakpoint.xs"
                        :small="$vuetify.breakpoint.xs"
                    >
                        <v-icon>mdi-reload</v-icon>
                        <span v-if="!$vuetify.breakpoint.xs">{{ $t('admin.books.refresh') }}</span>
                    </v-btn>
                    <v-menu offset-y>
                        <template v-slot:activator="{ on, attrs }">
                            <v-btn
                                :disabled="loading || scraping"
                                outlined
                                color="purple"
                                class="flex-shrink-0"
                                :icon="$vuetify.breakpoint.xs"
                                :small="$vuetify.breakpoint.xs"
                                v-bind="attrs"
                                v-on="on"
                            >
                                <v-icon>mdi-dots-vertical</v-icon>
                                <span v-if="!$vuetify.breakpoint.xs">{{ $t('admin.books.batchProcess') }}</span>
                            </v-btn>
                        </template>
                        <v-list>
                            <v-list-item @click="show_clear_rare_tags_dialog">
                                <v-list-item-icon>
                                    <v-icon>mdi-tag-remove-outline</v-icon>
                                </v-list-item-icon>
                                <v-list-item-title>{{ $t('admin.books.clearRareTags') }}</v-list-item-title>
                            </v-list-item>
                            <v-list-item @click="ai_fill" :disabled="books_selected.length === 0">
                                <v-list-item-icon>
                                    <v-icon>mdi-robot</v-icon>
                                </v-list-item-icon>
                                <v-list-item-title>{{ $t('admin.books.aiUpdate') }}</v-list-item-title>
                            </v-list-item>
                            <v-list-item @click="show_exchange_type_dialog" :disabled="books_selected.length === 0">
                                <v-list-item-icon>
                                    <v-icon>mdi-swap-horizontal</v-icon>
                                </v-list-item-icon>
                                <v-list-item-title>{{ $t('admin.books.exchangeType') }}</v-list-item-title>
                            </v-list-item>
                        </v-list>
                    </v-menu>
                    <v-btn
                        :disabled="loading || scraping"
                        outlined
                        color="info"
                        @click="show_dialog_auto_file"
                        class="flex-shrink-0"
                        :icon="$vuetify.breakpoint.xs"
                        :small="$vuetify.breakpoint.xs"
                    >
                        <v-icon>mdi-book-refresh-outline</v-icon>
                        <span v-if="!$vuetify.breakpoint.xs">{{ $t('admin.books.autoUpdate') }}</span>
                    </v-btn>
                    <v-btn
                        v-if="!loading && books_selected.length > 0"
                        outlined
                        color="error"
                        @click="deleteSelectedBooks"
                        class="flex-shrink-0"
                        :icon="$vuetify.breakpoint.xs"
                        :small="$vuetify.breakpoint.xs"
                    >
                        <v-icon>mdi-delete</v-icon>
                        <span v-if="!$vuetify.breakpoint.xs">{{ $t('admin.books.deleteSelected') }}</span>
                    </v-btn>
                    <v-select
                        dense
                        v-model="book_type_filter"
                        :items="[
                            { text: $t('admin.books.allBooks'), value: -1 },
                            { text: $t('admin.books.bookEBook'), value: 0 },
                            { text: $t('admin.books.bookPhysical'), value: 1 }
                        ]"
                        :label="$t('admin.books.bookTypeFilter')"
                        outlined
                        hide-details
                        class="flex-shrink-0"
                        style="max-width: 200px; min-width: 150px;"
                    ></v-select>
                    <v-text-field
                        dense
                        @keyup.enter="getDataFromApi"
                        v-model="search"
                        append-icon="mdi-magnify"
                        :label="$t('admin.books.search')"
                        single-line
                        hide-details
                        outlined
                    ></v-text-field>
                </v-col>
            </v-row>
        </v-card-actions>
        <v-progress-linear
            v-if="scraping && progress.count_total > 0"
            :value="progressPercent"
            height="24"
            color="green"
            background-color="green"
            style="opacity: 1;"
            class="mb-4"
        >
            <strong class="white--text">{{ $t('admin.books.scraping') }} {{ progress.count_processed }} / {{ progress.count_total }} ({{ $t('admin.books.failed') }}: {{ progress.count_failed }}, {{ $t('admin.books.skipped') }}: {{ progress.count_skipped }}) ({{ progressPercent }}%)</strong>
        </v-progress-linear>
        <v-data-table
            dense
            class="elevation-1 text-body-2"
            show-select
            v-model="books_selected"
            item-key="id"
            :search="search"
            :headers="responsiveHeaders"
            :items="items"
            :options.sync="options"
            :server-items-length="total"
            :loading="loading"
            :items-per-page="100"
            :footer-props="{ 'items-per-page-options': [10, 50, 100, 1000] }"
            :mobile-breakpoint="600"
        >
            <template v-slot:top>
                <v-data-footer
                    :options.sync="options"
                    :pagination="topPagination"
                    :items-per-page-options="[10, 50, 100, 1000]"
                    @update:options="options = $event"
                />
            </template>
            <template v-slot:item.status="{ item }">
                <v-chip small v-if="item.status == 'ready'" class="success">{{ $t('admin.books.status.ready') }}</v-chip>
                <v-chip small v-else-if="item.status == 'exist'" class="lighten-4">{{ $t('admin.books.status.exist') }}</v-chip>
                <v-chip small v-else-if="item.status == 'imported'" class="primary">{{ $t('admin.books.status.imported') }}</v-chip>
                <v-chip small v-else-if="item.status == 'new'" class="grey">{{ $t('admin.books.status.new') }}</v-chip>
                <v-chip small v-else class="info">{{ item.status }}</v-chip>
            </template>
            <template v-slot:item.img="{ item }">
                <a target="_blank" :href="item.img">
                    <v-img
                        :src="item.thumb"
                        :aspect-ratio="3/4"
                    />
                </a>
            </template>
            <template v-slot:item.id="{ item }">
                <a target="_blank" :href="`/book/${item.id}`">{{ item.id }}</a>
            </template>
            <template v-slot:item.book_type="{ item }">
                <v-chip small :color="item.book_type === 1 ? 'success' : 'primary'">
                    {{ item.book_type === 1 ? $t('admin.books.bookPhysical') : $t('admin.books.bookEBook') }}
                </v-chip>
            </template>
            <template v-slot:item.book_count="{ item }">
                <v-edit-dialog
                    v-if="item.book_type === 1"
                    large
                    :return-value.sync="item.book_count"
                    @save="save(item, 'book_count')"
                    save-text="保存"
                    cancel-text="取消"
                >
                    <span>{{ item.book_count || 0 }}</span>
                    <template v-slot:input>
                        <div class="mt-4 text-h6">修改数量</div>
                        <v-text-field
                            v-model.number="item.book_count"
                            label="在库数量"
                            type="number"
                            min="0"
                            max="100"
                            :rules="[v => v >= 0 && v <= 100 || '数量必须在0-100之间']"
                            counter
                        ></v-text-field>
                    </template>
                </v-edit-dialog>
                <span v-else>-</span>
            </template>
            <template v-slot:item.title="{ item }">
                <v-edit-dialog large :return-value.sync="item.title" @save="save(item, 'title')" save-text="保存" cancel-text="取消">
                    <span class="three-lines" style="max-width: 200px; min-width: 120px; ">{{ item.title }}</span>
                    <template v-slot:input>
                        <div class="mt-4 text-h6">修改字段</div>
                        <v-textarea v-model="item.title" label="书名" style="min-width: 400px" counter></v-textarea>
                    </template>
                </v-edit-dialog>
            </template>

            <template v-slot:item.author="{ item }">
                <v-edit-dialog large :return-value.sync="item.author" @save="save(item, 'authors')" save-text="保存" cancel-text="取消">
                    <span class="three-lines" style="max-width: 200px" v-if="item.authors">{{ item.authors.join("/") }}</span>
                    <span v-else> - </span>
                    <template v-slot:input>
                        <!-- AUTHORS -->
                        <div class="mt-4 text-h6">修改字段</div>
                        <v-combobox
                            v-model="item.authors"
                            :items="item.authors"
                            label="作者"
                            :search-input.sync="tag_input"
                            hide-selected
                            multiple
                            small-chips
                        >
                            <template v-slot:no-data>
                                <v-list-item>
                                    <span v-if="!tag_input">请输入新的名称</span>
                                    <div v-else>
                                        <span class="subheading">添加</span>
                                        <v-chip color="green lighten-3" label small rounded> {{ tag_input }} </v-chip>
                                    </div>
                                </v-list-item>
                            </template>
                            <!-- tag chip & close -->
                            <template v-slot:selection="{ attrs, item, parent, selected }">
                                <v-chip v-bind="attrs" color="green lighten-3" :input-value="selected" label small>
                                    <span class="pr-2"> {{ item }} </span>
                                    <v-icon small @click="parent.selectItem(item)">close</v-icon>
                                </v-chip>
                            </template>
                        </v-combobox>
                    </template>
                </v-edit-dialog>
            </template>

            <template v-slot:item.rating="{ item }">
                <v-edit-dialog large :return-value.sync="item.rating" @save="save(item, 'rating')" save-text="保存" cancel-text="取消">
                    <span v-if="item.rating != null">{{ item.rating }} 星</span>
                    <span v-else> - </span>
                    <template v-slot:input>
                        <div class="mt-4 text-h6">修改评分</div>
                        <v-rating label="评分" v-model="item.rating" color="yellow accent-4" length="10" dense></v-rating>
                    </template>
                </v-edit-dialog>
            </template>

            <template v-slot:item.category="{ item }">
                <v-edit-dialog large :return-value.sync="item.category" @save="save(item, 'category')" save-text="保存" cancel-text="取消">
                    <span v-if="item.category != null">{{ item.category || '未分类'}}</span>
                    <span v-else> - </span>
                    <template v-slot:input>
                        <div class="mt-4 text-h6">修改分类</div>
                        <v-select :items="categories" v-model="item.category" color="yellow accent-4" dense></v-select>
                    </template>
                </v-edit-dialog>
            </template>

            <template v-slot:item.publisher="{ item }">
                <v-edit-dialog
                    large
                    :return-value.sync="item.publisher"
                    @save="save(item, 'publisher')"
                    save-text="保存"
                    cancel-text="取消"
                >
                    <span v-if="item.publisher != null" class="three-lines" style="max-width: 110px; min-width: 60px; ">{{ item.publisher }}</span>
                    <span v-else> - </span>
                    <template v-slot:input>
                        <div class="mt-4 text-h6">修改字段</div>
                        <v-text-field v-model="item.publisher" label="出版社" counter></v-text-field>
                    </template>
                </v-edit-dialog>
            </template>

            <template v-slot:item.tags="{ item }">
                <v-edit-dialog large :return-value.sync="item.tags" @save="save(item, 'tags')" save-text="保存" cancel-text="取消">
                    <span style="width: 200px" class="three-lines" v-if="item.tags">{{ item.tags.join("/") }}</span>
                    <span v-else> - </span>
                    <template v-slot:input>
                        <!-- TAGS -->
                        <div class="mt-4 text-h6">修改字段</div>
                        <v-combobox
                            v-model="item.tags"
                            :items="item.tags"
                            label="标签列表"
                            :search-input.sync="tag_input"
                            hide-selected
                            multiple
                            small-chips
                        >
                            <template v-slot:no-data>
                                <v-list-item>
                                    <span v-if="!tag_input">请输入新的标签名称</span>
                                    <div v-else>
                                        <span class="subheading">添加标签</span>
                                        <v-chip color="green lighten-3" label small rounded> {{ tag_input }} </v-chip>
                                    </div>
                                </v-list-item>
                            </template>
                            <!-- tag chip & close -->
                            <template v-slot:selection="{ attrs, item, parent, selected }">
                                <v-chip v-bind="attrs" color="green lighten-3" :input-value="selected" label small>
                                    <span class="pr-2"> {{ item }} </span>
                                    <v-icon small @click="parent.selectItem(item)">close</v-icon>
                                </v-chip>
                            </template>
                        </v-combobox>
                    </template>
                </v-edit-dialog>
            </template>

            <template v-slot:item.comments="{ item }">
                <v-edit-dialog large :return-value.sync="item.comments" @save="save(item, 'comments')" save-text="保存" cancel-text="取消">
                    <span :title="item.comments" style="width: 300px" class="three-lines">{{ item.comments.substr(0, 80) }}</span>
                    <template v-slot:input>
                        <div class="mt-4 text-h6">修改字段</div>
                        <v-textarea v-model="item.comments" label="简介"></v-textarea>
                    </template>
                </v-edit-dialog>
            </template>

            <template v-slot:item.actions="{ item }">
                <v-menu offset-y right>
                    <template v-slot:activator="{ on }">
                        <v-btn
                            color="primary"
                            :small="!$vuetify.breakpoint.xs"
                            :x-small="$vuetify.breakpoint.xs"
                            :icon="$vuetify.breakpoint.xs"
                            v-on="on"
                        >
                            <v-icon :small="!$vuetify.breakpoint.xs" :x-small="$vuetify.breakpoint.xs">more_vert</v-icon>
                            <span v-if="!$vuetify.breakpoint.xs">操作</span>
                        </v-btn>
                    </template>
                    <v-list dense>
                        <v-list-item @click="delete_book(item)">
                            <v-list-item-title>删除此书</v-list-item-title>
                        </v-list-item>
                    </v-list>
                </v-menu>
            </template>
        </v-data-table>

        <!-- 小浮窗提醒 -->
        <v-snackbar v-model="snack" top :timeout="3000" :color="snackColor">
            {{ snackText }}

            <template v-slot:action="{ attrs }">
                <v-btn v-bind="attrs" text @click="snack = false"> {{ $t('admin.books.close') }} </v-btn>
            </template>
        </v-snackbar>

        <!-- 提醒拉取图书的规则说明 -->
        <v-dialog v-model="meta_dialog" persistent transition="dialog-bottom-transition" width="500">
            <v-card>
                <v-toolbar flat dense dark color="primary"> {{ $t('admin.books.reminderTitle') }} </v-toolbar>
                <v-card-title></v-card-title>
                <v-card-text>
                    <p> {{ $t('admin.books.reminder.description') }} </p>
                    <p> {{ $t('admin.books.reminder.rule1') }} </p>
                    <p> {{ $t('admin.books.reminder.rule2') }} </p>
                    <p> {{ $t('admin.books.reminder.rule3') }} </p>
                    <p> {{ $t('admin.books.reminder.estimate', { minutes: auto_fill_mins }) }} </p>
                </v-card-text>
                <v-card-actions>
                    <v-btn @click="meta_dialog = !meta_dialog">{{ $t('admin.books.cancel') }}</v-btn>
                    <v-spacer></v-spacer>
                    <v-btn color="primary" @click="auto_fill">{{ $t('admin.books.execute') }}</v-btn>
                </v-card-actions>
            </v-card>
        </v-dialog>

        <!-- 图书类型互转确认对话框 -->
        <v-dialog v-model="exchange_type_dialog" persistent transition="dialog-bottom-transition" width="500">
            <v-card>
                <v-toolbar flat dense dark color="warning"> {{ $t('admin.books.reminderTitle') }} </v-toolbar>
                <v-card-title></v-card-title>
                <v-card-text>
                    <p> {{ $t('admin.books.exchangeTypeConfirm') }} </p>
                </v-card-text>
                <v-card-actions>
                    <v-btn @click="exchange_type_dialog = false">{{ $t('admin.books.cancel') }}</v-btn>
                    <v-spacer></v-spacer>
                    <v-btn color="warning" @click="exchangeBookType">{{ $t('admin.books.execute') }}</v-btn>
                </v-card-actions>
            </v-card>
        </v-dialog>

        <!-- 清理稀少标签确认对话框 -->
        <v-dialog v-model="clear_rare_tags_dialog" persistent transition="dialog-bottom-transition" width="500">
            <v-card>
                <v-toolbar flat dense dark color="secondary"> {{ $t('admin.books.reminderTitle') }} </v-toolbar>
                <v-card-title></v-card-title>
                <v-card-text>
                    <p> {{ $t('admin.books.clearRareTagsConfirm') }} </p>
                </v-card-text>
                <v-card-actions>
                    <v-btn @click="clear_rare_tags_dialog = false">{{ $t('admin.books.cancel') }}</v-btn>
                    <v-spacer></v-spacer>
                    <v-btn color="secondary" @click="clearRareTags">{{ $t('admin.books.execute') }}</v-btn>
                </v-card-actions>
            </v-card>
        </v-dialog>


</v-card>
</template>

<script>
export default {
    data: () => ({
        snack: false,
        snackColor: "",
        snackText: "",
        meta_dialog: false,
        exchange_type_dialog: false,
        clear_rare_tags_dialog: false,
        adding_book: false,
        books_selected: [],
        tag_input: null,
        search: "",
        book_type_filter: -1,
        page: 1,
        items: [],
        total: 0,
        loading: false,
        scraping: false,
        options: { sortBy: ["id"], sortDesc: [true] },
        headers: [
            { text: "封面", sortable: false, value: "img", width: "80px" },
            { text: "ID", sortable: true, value: "id", width: "80px" },
            { text: "类型", sortable: false, value: "book_type", width: "80px" },
            { text: "数量", sortable: false, value: "book_count", width: "70px" },
            { text: "书名", sortable: true, value: "title" },
            { text: "作者", sortable: true, value: "author", width: "100px" },
            { text: "分类", sortable: false, value: "category", width: "80px"},
            { text: "评分", sortable: false, value: "rating", width: "60px" },
            { text: "出版社", sortable: false, value: "publisher" },
            { text: "标签", sortable: true, value: "tags", width: "100px" },
            { text: "简介", sortable: true, value: "comments" },
            { text: "操作", sortable: false, value: "actions" },
        ],
        progress: {
            count_total: 0,
            count_processed: 0,
            count_done: 0,
            count_failed: 0,
            count_skipped: 0,
        },
        categories: [],
    }),
    created() {
        this.checkCurrentState();
        this.getSettings();
    },
    watch: {
        options: {
            handler() {
                this.getDataFromApi();
            },
            deep: true,
        },
        book_type_filter() {
            this.getDataFromApi();
        },
    },
    computed: {
        auto_fill_mins: function() {
            return Math.floor(this.total/60) + 1;
        },
        progressPercent() {
            if (!this.progress.count_total) {
                return 0;
            }
            const pct = Math.round((this.progress.count_processed / this.progress.count_total) * 100);
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
        responsiveHeaders: function() {
            // 根据屏幕宽度返回不同的headers配置
            if (this.$vuetify.breakpoint.xs) {
                // 超小屏幕（手机）：显示封面、ID、书名、作者和操作
                return [
                    { text: "封面", sortable: false, value: "img", width: "40px" },
                    { text: "ID", sortable: true, value: "id", width: "50px" },
                    { text: "书名", sortable: true, value: "title" },
                    { text: "作者", sortable: true, value: "author", width: "80px" },
                    { text: "操作", sortable: false, value: "actions", width: "60px" },
                ];
            } else if (this.$vuetify.breakpoint.sm) {
                // 小屏幕（平板）：显示核心信息
                return [
                    { text: "封面", sortable: false, value: "img", width: "70px" },
                    { text: "ID", sortable: true, value: "id", width: "60px" },
                    { text: "类型", sortable: false, value: "book_type", width: "70px" },
                    { text: "书名", sortable: true, value: "title" },
                    { text: "作者", sortable: true, value: "author", width: "100px" },
                    { text: "操作", sortable: false, value: "actions", width: "80px" },
                ];
            } else {
                // 中等屏幕及以上：显示所有列
                return this.headers;
            }
        }
    },
    methods: {
        getDataFromApi() {
            this.loading = true;
            const { sortBy, sortDesc, page, itemsPerPage } = this.options;

            var data = new URLSearchParams();
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
            if (this.search != undefined) {
                data.append("search", this.search);
            }
            if (this.book_type_filter != undefined && this.book_type_filter != -1) {
                data.append("type", this.book_type_filter);
            }
            this.$backend("/admin/book/list?" + data.toString())
                .then((rsp) => {
                    if (rsp.err != "ok") {
                        this.items = [];
                        this.total = 0;
                        this.$alert("error", rsp.msg);
                        return false;
                    }
                    this.items = rsp.items;
                    this.total = rsp.total;
                })
                .finally(() => {
                    this.loading = false;
                });
        },
        // 通用方法：获取选中书籍的ID列表
        getSelectedBookIds() {
            if (this.books_selected.length == 0) {
                this.$alert("info", this.$t("admin.books.noSelectedBook"));
                return null;
            }
            return this.books_selected.map((book) => book.id);
        },

        // 通用方法：处理API响应
        handleApiResponse(rsp, successMessage = null) {
            if (rsp.err != "ok") {
                this.$alert("error", rsp.msg);
                return false;
            } else if (successMessage) {
                this.snack = true;
                this.snackColor = "success";
                this.snackText = successMessage || rsp.msg;
            }
            return true;
        },

        deleteSelectedBooks() {
            const books_ids = this.getSelectedBookIds();
            if (!books_ids) return;

            this.loading = true;
            this.$backend("/admin/books/delete", {
                method: "POST",
                body: JSON.stringify({"idlist": books_ids}),
            })
                .then((rsp) => {
                    this.handleApiResponse(rsp);
                    this.books_selected = [];
                    this.getDataFromApi();
                })
                .finally(() => {
                    this.loading = false;
                });
        },

        show_dialog_auto_file() {
            this.meta_dialog = true;
        },

        show_exchange_type_dialog() {
            this.exchange_type_dialog = true;
        },

        show_clear_rare_tags_dialog() {
            this.clear_rare_tags_dialog = true;
        },

        clearRareTags() {
            this.loading = true;
            this.clear_rare_tags_dialog = false;
            this.$backend("/clear_rare_tags", {
                method: "POST",
                body: JSON.stringify({}),
            })
                .then((rsp) => {
                    if (this.handleApiResponse(rsp)) {
                        this.checkCurrentState();
                    }
                    this.getDataFromApi();
                })
                .finally(() => {
                    this.loading = false;
                });
        },

        exchangeBookType() {
            const books_ids = this.getSelectedBookIds();
            if (!books_ids) return;

            this.loading = true;
            this.exchange_type_dialog = false;
            this.$backend("/book/exchange_type", {
                method: "POST",
                body: JSON.stringify({"idlist": books_ids}),
            })
                .then((rsp) => {
                    this.handleApiResponse(rsp);
                    this.books_selected = [];
                    this.getDataFromApi();
                    this.$alert("success", rsp.msg);
                })
                .finally(() => {
                    this.loading = false;
                });
        },
        auto_fill() {
            this.$backend("/admin/book/fill", {
                method: "POST",
                body: JSON.stringify({"idlist": "all"}),
            })
            .then((rsp) => {
                this.meta_dialog = false;
                if (rsp.err != "ok") {
                    this.$alert("error", rsp.msg);
                    return;
                }
                this.$alert("success", rsp.msg);
                // Start checking status
                this.checkCurrentState();
            })
        },

        ai_fill() {
            const idlist = this.getSelectedBookIds();
            if (!idlist) return;
            this.$backend("/admin/book/aifill", {
                method: "POST",
                body: JSON.stringify({ idlist }),
            }).then((rsp) => {
                if (rsp.err != "ok") {
                    this.$alert("error", rsp.msg);
                    return;
                }
                this.$alert("success", rsp.msg);
            });
        },

        delete_book(book) {
            this.loading = true;
            this.$backend("/book/" + book.id + "/delete", {
                method: "POST",
                body: "",
            })
                .then((rsp) => {
                    this.handleApiResponse(rsp);
                    this.getDataFromApi();
                })
                .finally(() => {
                    this.loading = false;
                });
        },

        save(book, field) {
            var edit = {};
            edit[field] = book[field];
            // If books_selected is more than 1 means batch update
            if (this.books_selected.length > 1) {
                edit['ids'] = this.books_selected.map((book) => book.id);
            }
            this.saving = true;
            this.$backend("/book/" + book.id + "/edit", {
                method: "POST",
                body: JSON.stringify(edit),
            }).then((rsp) => {
                if (this.handleApiResponse(rsp)) {
                    // Update the updated books in the response
                    if (this.books_selected.length > 1 && rsp.books?.length > 0) {
                        this.books_selected.forEach((book) => {
                            if (rsp.books.includes(book.id)) {
                                book[field] = edit[field];
                            }
                        });
                    }
                }
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
                        }
                    })
            }, 2000);
        },
        checkCurrentState() {
            this.$backend("/admin/book/fill", {
                method: "GET",
            })
            .then((rsp) => {
                if (rsp.err !== "ok" || !rsp.status) {
                    return;
                }
                // Check if scraping is in progress
                if (rsp.status.running) {
                    this.scraping = true;
                    this.loop_check_status("/admin/book/fill", (rsp) => {
                        this.progress.count_total = rsp.status.total || 0;
                        this.progress.count_failed = rsp.status.fail || 0;
                        this.progress.count_skipped = rsp.status.skip || 0;
                        this.progress.count_done = rsp.status.done || 0;
                        this.progress.count_processed = (rsp.status.done || 0) + (rsp.status.fail || 0) + (rsp.status.skip || 0);
                        if (!rsp.status.running) {
                            this.scraping = false;
                            this.progress.count_total = 0;
                            this.progress.count_processed = 0;
                            this.progress.count_done = 0;
                            this.progress.count_failed = 0;
                            this.progress.count_skipped = 0;
                            return false;
                        }
                        return true;
                    });
                } else {
                    this.scraping = false;
                    this.progress.count_total = 0;
                    this.progress.count_processed = 0;
                    this.progress.count_done = 0;
                    this.progress.count_failed = 0;
                    this.progress.count_skipped = 0;
                }
            })
        },
        async getSettings() {
            try {
                const response = await this.$backend('/admin/settings');
                if (response.err === 'ok' && response.settings) {
                    if (response.settings.BOOK_NAV) {
                        this.categories = response.settings.BOOK_NAV.split('\n').map(line => {
                            const parts = line.split('=');
                            return parts[0].trim();
                        }).filter(c => c);
                    }
                }
            } catch (error) {
                console.error('Failed to get settings:', error);
            }
        },
    },
};
</script>

<style>
.three-lines {
    overflow: hidden;
    text-overflow: ellipsis;
    display: -webkit-box;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 3;
    line-clamp: 3;
    white-space: normal;
}

/* 响应式优化 */
@media (max-width: 960px) {
    /* 在中等屏幕以下时，按钮文字可以更紧凑 */
    .v-btn .v-icon {
        margin-right: 4px !important;
    }

    /* 表格在中屏幕上的优化 */
    .v-data-table th {
        font-size: 12px !important;
        padding: 0 8px !important;
    }
}

@media (max-width: 600px) {
    /* 在小屏幕上优化按钮间距 */
    .v-card-actions {
        padding: 12px !important;
    }

    /* 按钮在小屏幕上使用更小的尺寸 */
    .v-btn:not(.v-btn--icon) {
        min-width: auto !important;
        padding: 0 12px !important;
    }

    /* 搜索框在小屏幕上占满宽度 */
    .v-text-field {
        width: 100% !important;
    }

    /* 表格在小屏幕上的优化 */
    .v-data-table {
        font-size: 14px !important;
    }

    .v-data-table th,
    .v-data-table td {
        padding: 6px 8px !important;
        font-size: 14px !important;
    }

    /* 表格标题在小屏幕上隐藏或缩短 */
    .v-data-table .text-start {
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        max-width: 100px;
    }

    /* 封面图片在小屏幕上保持30x40的固定尺寸 */
    .v-data-table .v-image {
        min-width: 30px !important;
        max-width: 30px !important;
        width: 30px !important;
        min-height: 40px !important;
        max-height: 40px !important;
        height: 40px !important;
        margin-left: auto !important;
        display: block !important;
    }

    /* 确保图片单元格也有合适的宽度和右对齐 - 桌面端表格 */
    .v-data-table td:has(.v-image) {
        width: 100% !important;
        min-width: 40px !important;
        padding: 6px !important;
    }

    /* 确保图片链接也是右对齐的 - 桌面端表格 */
    .v-data-table td:has(.v-image) a {
        display: flex !important;
        justify-content: flex-end !important;
        width: 100% !important;
    }

    /* 移动端表格整体布局 */
    .v-data-table__mobile-table-row {
        font-size: 14px !important;
        margin-bottom: 16px !important;
        border-bottom: 1px solid rgba(0,0,0,0.1) !important;
        padding-bottom: 12px !important;
    }

    /* 移动端表格行 */
    .v-data-table__mobile-row {
        display: flex !important;
        flex-direction: row !important;
        align-items: center !important;
        padding: 8px 12px !important;
        margin-bottom: 0 !important;
        border-bottom: none !important;
        width: 100% !important;
        min-width: auto !important;
    }

    /* 移动端表格标题 */
    .v-data-table__mobile-row__header {
        font-size: 14px !important;
        font-weight: 600 !important;
        margin-right: 12px !important;
        min-width: 70px !important;
        color: rgba(0,0,0,0.7) !important;
        flex-shrink: 0 !important;
    }

    /* 移动端表格单元格内容 */
    .v-data-table__mobile-row__cell {
        font-size: 14px !important;
        flex: 1 !important;
        word-break: break-word !important;
        min-width: 0 !important;
        padding: 0 !important;
    }

    /* 封面图片所在行的特殊处理 */
    .v-data-table__mobile-row:nth-child(2) {
        width: 100% !important;
        min-width: 100% !important;
        min-height: 100px !important;
        align-items: flex-start !important;
        padding: 12px !important;
    }

    /* 封面图片所在行的内容 */
    .v-data-table__mobile-row:nth-child(2) .v-data-table__mobile-row__cell {
        flex: 1 !important;
        display: flex !important;
        justify-content: center !important;
        align-items: center !important;
        min-height: 100px !important;
    }

    /* 封面图片 */
    .v-data-table__mobile-row:nth-child(2) .v-data-table__mobile-row__cell .v-image {
        min-width: 100px !important;
        max-width: 120px !important;
        width: 100px !important;
        min-height: 160px !important;
        max-height: 160px !important;
        height: 160px !important;
        margin: 0 !important;
    }

    /* 为不同类型的字段设置不同的最小宽度 */
    .v-data-table__mobile-row:nth-child(1) .v-data-table__mobile-row__header {
        min-width: 50px !important;
    }

    .v-data-table__mobile-row:nth-child(3) .v-data-table__mobile-row__header {
        min-width: 40px !important;
    }

    .v-data-table__mobile-row:nth-child(4) .v-data-table__mobile-row__header {
        min-width: 60px !important;
    }

    .v-data-table__mobile-row:nth-child(5) .v-data-table__mobile-row__header {
        min-width: 60px !important;
    }

    .v-data-table__mobile-row:nth-child(6) .v-data-table__mobile-row__header {
        min-width: 60px !important;
    }

    /* Chip组件在小屏幕上保持合适大小 */
    .v-chip {
        font-size: 12px !important;
        height: 24px !important;
        padding: 0 8px !important;
    }
}

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

/* 移动端按钮组优化 */
@media (max-width: 599px) {
    .flex-wrap .v-btn {
        margin: 2px !important;
        min-width: 36px !important;
    }

    /* 图标按钮在移动端的间距 */
    .v-btn--icon {
        width: 36px !important;
        height: 36px !important;
    }
}

/* 为超宽屏幕优化 */
@media (min-width: 1920px) {
    .v-data-table {
        font-size: 14px !important;
    }
}
</style>
