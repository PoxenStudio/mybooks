<template>
    <v-card>
        <v-card-title>
            {{ $t('admin.users.title') }}
            <v-btn color="primary" @click="showAddUserDialog = true" class="ml-4">
                <v-icon left>mdi-account-plus</v-icon>
                {{ $t('admin.users.add_user') }}
            </v-btn>
        </v-card-title>
        <v-data-table
            :headers="headers"
            :items="items"
            :options.sync="options"
            :server-items-length="total"
            :loading="loading"
            :items-per-page="10"
            :footer-props="{ 'items-per-page-options': [10, 50, 100] }"
            class="elevation-1"
        >
            <template v-slot:item.login_ip="{ item }">
                {{ item.extra.login_ip }}
            </template>
            <template v-slot:item.detail="{ item }">
                <span v-if="item.extra.visit_history"> {{ $t('admin.users.visit', { count: item.extra.visit_history.length }) }} </span>
                <span v-if="item.extra.read_history"> {{ $t('admin.users.read_cnt', { count: item.extra.read_history.length }) }} </span>
                <span v-if="item.extra.push_history"> {{ $t('admin.users.push_cnt', { count: item.extra.push_history.length }) }} </span>
                <span v-if="item.extra.download_history_count"> {{ $t('admin.users.download_cnt', { count: item.extra.download_history_count }) }} </span>
                <span v-if="item.extra.upload_history_count"> {{ $t('admin.users.upload_cnt', { count: item.extra.upload_history_count }) }} </span>
                <span v-if="item.vipquota"> {{ $t('admin.users.vipquota', { count: item.vipquota }) }} </span>
            </template>
            <template v-slot:item.actions="{ item }">
                <v-btn small color="#336666" class="white--text" @click="openReadingRangeDialog(item)" v-if="allowReadRangeSetting">{{ $t('admin.users.set_reading_range') }}</v-btn>
                <v-menu offset-y right>
                    <template v-slot:activator="{ on }">
                        <v-btn color="primary" small v-on="on">{{ $t('admin.users.actions') }} <v-icon small>more_vert</v-icon></v-btn>
                    </template>
                    <v-list dense>
                        <v-subheader>{{ $t('admin.users.modify_permissions') }}</v-subheader>
                        <template v-for="perm in permissions">
                            <v-list-item :key="'disable-' + perm.name" v-if="item[perm.name]">
                                <v-list-item-title
                                    ><v-icon color="success">mdi-account-check</v-icon> {{ $t('admin.users.allowed', { permission: perm.text }) }}
                                </v-list-item-title>
                                <v-list-item-action>
                                    <v-btn
                                        text
                                        small
                                        color="error"
                                        @click="
                                            setuser(item.id, { permission: perm.code.toUpperCase() });
                                            item[perm.name] = !item[perm.name];
                                        "
                                    >
                                        {{ $t('admin.users.disable') }}
                                    </v-btn>
                                </v-list-item-action>
                            </v-list-item>
                            <v-list-item :key="'enable-' + perm.name" v-else>
                                <v-list-item-title
                                    ><v-icon color="danger">mdi-account-remove</v-icon> {{ $t('admin.users.prohibited', { permission: perm.text }) }}
                                </v-list-item-title>
                                <v-list-item-action>
                                    <v-btn
                                        text
                                        small
                                        color="primary"
                                        @click="
                                            setuser(item.id, { permission: perm.code.toLowerCase() });
                                            item[perm.name] = !item[perm.name];
                                        "
                                    >
                                        {{ $t('admin.users.enable') }}
                                    </v-btn>
                                </v-list-item-action>
                            </v-list-item>
                        </template>

                        <v-divider></v-divider>
                        <v-subheader>{{ $t('admin.users.account_management') }}</v-subheader>
                        <v-list-item
                            v-if="!item.is_active"
                            @click="
                                setuser(item.id, { active: true });
                                item.is_active = true;
                            "
                        >
                            <v-list-item-title> {{ $t('admin.users.activate_account') }} </v-list-item-title>
                        </v-list-item>
                        <v-list-item
                            v-if="item.is_admin"
                            @click="
                                setuser(item.id, { admin: false });
                                item.is_admin = !item.is_admin;
                            "
                        >
                            <v-list-item-title> {{ $t('admin.users.remove_admin') }} </v-list-item-title>
                        </v-list-item>
                        <v-list-item
                            v-else
                            @click="
                                setuser(item.id, { admin: true });
                                item.is_admin = item.is_admin = !item.is_admin;
                            "
                        >
                            <v-list-item-title> {{ $t('admin.users.set_admin') }} </v-list-item-title>
                        </v-list-item>
                        <v-list-item
                            @click="
                                setuser(item.id, { delete: item.username });
                                getDataFromApi()
                            "
                        >
                            <v-list-item-title> {{ $t('admin.users.delete_user') }} </v-list-item-title>
                        </v-list-item>
                    </v-list>
                </v-menu>
            </template>
        </v-data-table>

        <!-- Reading Range Dialog -->
        <v-dialog v-model="showReadingRangeDialog" max-width="600px" persistent>
            <v-card>
                <v-card-title>
                    {{ $t('admin.users.reading_range_dialog_title') }}
                    <v-spacer></v-spacer>
                    <v-btn icon @click="showReadingRangeDialog = false">
                        <v-icon>mdi-close</v-icon>
                    </v-btn>
                </v-card-title>
                <v-card-text>
                    <!-- Mode radio group -->
                    <v-radio-group v-model="readingRange.mode" mandatory>
                        <v-radio :label="$t('admin.users.reading_range_all')" :value="0"></v-radio>
                        <v-radio :label="$t('admin.users.reading_range_whitelist')" :value="1"></v-radio>
                        <v-radio :label="$t('admin.users.reading_range_blacklist')" :value="2"></v-radio>
                    </v-radio-group>

                    <template v-if="readingRange.mode !== 0">
                        <!-- Categories multi-select -->
                        <v-select
                            v-model="readingRange.selectedCategories"
                            :items="allCategories"
                            item-text="name"
                            item-value="name"
                            :label="$t('admin.users.reading_range_categories_label')"
                            multiple
                            chips
                            small-chips
                            deletable-chips
                            :loading="loadingCategories"
                            class="mb-2"
                        ></v-select>

                        <!-- Tag search + chips -->
                        <div class="mb-1 subtitle-2">{{ $t('admin.users.reading_range_tags_label') }}</div>
                        <v-text-field
                            v-model="tagSearchInput"
                            :label="$t('admin.users.reading_range_tags_hint')"
                            :loading="loadingTags"
                            clearable
                            dense
                            outlined
                            @input="onTagSearchInput"
                            @click:clear="tagSuggestions = []"
                        ></v-text-field>
                        <!-- Tag suggestions list -->
                        <v-list dense class="mb-2" v-if="tagSuggestions.length > 0" style="max-height:160px;overflow-y:auto;border:1px solid #ddd;border-radius:4px;">
                            <v-list-item
                                v-for="tag in tagSuggestions"
                                :key="tag.name"
                                @click="addTag(tag.name)"
                                :disabled="readingRange.selectedTags.includes(tag.name)"
                            >
                                <v-list-item-title>{{ tag.name }} <span class="grey--text caption">({{ tag.count }})</span></v-list-item-title>
                                <v-list-item-action>
                                    <v-icon small color="primary">mdi-plus</v-icon>
                                </v-list-item-action>
                            </v-list-item>
                            <v-list-item v-if="tagSuggestions.length === 0 && tagSearchInput">
                                <v-list-item-title class="grey--text">{{ $t('admin.users.reading_range_tags_no_result') }}</v-list-item-title>
                            </v-list-item>
                        </v-list>
                        <!-- Selected tags chips -->
                        <div v-if="readingRange.selectedTags.length > 0" class="d-flex flex-wrap gap-1 mt-1">
                            <v-chip
                                v-for="tag in readingRange.selectedTags"
                                :key="tag"
                                close
                                small
                                @click:close="removeTag(tag)"
                            >{{ tag }}</v-chip>
                        </div>
                    </template>
                </v-card-text>
                <v-card-actions>
                    <v-spacer></v-spacer>
                    <v-btn text @click="showReadingRangeDialog = false">{{ $t('admin.users.cancel') }}</v-btn>
                    <v-btn color="primary" @click="saveReadingRange" :loading="savingReadingRange">{{ $t('admin.users.reading_range_save') }}</v-btn>
                </v-card-actions>
            </v-card>
        </v-dialog>

        <!-- Add User Dialog -->
        <v-dialog v-model="showAddUserDialog" max-width="500px" persistent>
            <v-card>
                <v-card-title>
                    {{ $t('admin.users.add_user') }}
                    <v-spacer></v-spacer>
                    <v-btn icon @click="closeAddUserDialog">
                        <v-icon>mdi-close</v-icon>
                    </v-btn>
                </v-card-title>
                <v-card-text>
                    <v-form ref="addUserForm" @submit.prevent="addUser">
                        <v-text-field
                            required
                            prepend-icon="person"
                            v-model="newUser.username"
                            :label="$t('admin.users.username')"
                            type="text"
                            autocomplete="new-username"
                            :rules="[rules.user]"
                        ></v-text-field>
                        <v-text-field
                            required
                            prepend-icon="lock"
                            v-model="newUser.password"
                            :label="$t('admin.users.password')"
                            type="password"
                            autocomplete="new-password"
                            :rules="[rules.pass]"
                        ></v-text-field>
                        <v-text-field
                            required
                            prepend-icon="lock"
                            v-model="newUser.password2"
                            :label="$t('admin.users.confirm_password')"
                            type="password"
                            autocomplete="new-password2"
                            :rules="[validatePassword]"
                        ></v-text-field>
                        <v-text-field
                            required
                            prepend-icon="face"
                            v-model="newUser.nickname"
                            :label="$t('admin.users.nickname')"
                            type="text"
                            autocomplete="new-nickname"
                            :rules="[rules.nick]"
                        ></v-text-field>
                        <v-text-field
                            required
                            prepend-icon="email"
                            v-model="newUser.email"
                            :label="$t('admin.users.email')"
                            type="text"
                            autocomplete="new-email"
                            :rules="[rules.email]"
                        ></v-text-field>
                    </v-form>
                    <v-alert v-if="addUserError" type="error">{{ addUserError }}</v-alert>
                </v-card-text>
                <v-card-actions>
                    <v-spacer></v-spacer>
                    <v-btn text @click="closeAddUserDialog">{{ $t('admin.users.cancel') }}</v-btn>
                    <v-btn color="primary" @click="addUser" :loading="addingUser">{{ $t('admin.users.add') }}</v-btn>
                </v-card-actions>
            </v-card>
        </v-dialog>
    </v-card>
</template>

<script>
export default {
    data: () => ({
        page: 1,
        items: [],
        total: 0,
        loading: true,
        options: { sortBy: ["access_time"], sortDesc: [true] },
        headers: [],
        permissions: [],
        showAddUserDialog: false,
        addingUser: false,
        addUserError: "",
        // Reading range dialog
        showReadingRangeDialog: false,
        savingReadingRange: false,
        readingRangeUserId: null,
        readingRange: {
            mode: 0,
            selectedCategories: [],
            selectedTags: [],
        },
        allCategories: [],
        loadingCategories: false,
        tagSearchInput: "",
        tagSuggestions: [],
        loadingTags: false,
        tagSearchTimer: null,
        allowReadRangeSetting: false,
        newUser: {
            username: "",
            password: "",
            password2: "",
            nickname: "",
            email: ""
        },
        rules: {
            user: v => ( 20 >= v.length && v.length >= 3) || '3 ~ 20 字符',
            pass: v => ( 20 >= v.length && v.length >= 6) || '6 ~ 20 字符',
            nick: v => v.length >= 2 || '最少2个字符',
            email: function (email) {
                var re = /^(([^<>()[\]\\.,;:\s@"]+(\.[^<>()[\]\\.,;:\s@"]+)*)|(".+"))@((\[[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\])|(([a-zA-Z\-0-9]+\.)+[a-zA-Z]{2,}))$/;
                return re.test(email) || "错误的邮箱格式";
            },
        },
    }),
    created() {
        this.headers = [
            { text: this.$t('admin.users.id'), sortable: true, value: "id" },
            { text: this.$t('admin.users.username'), sortable: true, value: "username" },
            { text: this.$t('admin.users.nickname'), sortable: false, value: "name" },
            { text: this.$t('admin.users.email'), sortable: true, value: "email" },
            { text: this.$t('admin.users.provider'), sortable: false, value: "provider" },
            { text: this.$t('admin.users.create_time'), sortable: true, value: "create_time" },
            { text: this.$t('admin.users.access_time'), sortable: true, value: "access_time" },
            { text: this.$t('admin.users.login_ip'), sortable: false, value: "login_ip" },
            { text: this.$t('admin.users.detail'), sortable: false, value: "detail" },
            { text: this.$t('admin.users.actions'), sortable: false, value: "actions" },
        ];

        this.permissions = [
            { code: "l", name: "can_login", text: this.$t('admin.users.login') },
            { code: "u", name: "can_upload", text: this.$t('admin.users.upload') },
            { code: "s", name: "can_save", text: this.$t('admin.users.download') },
            { code: "e", name: "can_edit", text: this.$t('admin.users.edit') },
            { code: "d", name: "can_delete", text: this.$t('admin.users.delete') },
            { code: "p", name: "can_push", text: this.$t('admin.users.push') },
            { code: "r", name: "can_read", text: this.$t('admin.users.read') },
        ];
    },
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
        openReadingRangeDialog(item) {
            this.readingRangeUserId = item.id;
            this.readingRange = {
                mode: item.read_limit || 0,
                selectedCategories: item.limit_categories ? item.limit_categories.split(',').filter(Boolean) : [],
                selectedTags: item.limit_tags ? item.limit_tags.split(',').filter(Boolean) : [],
            };
            this.tagSearchInput = "";
            this.tagSuggestions = [];
            this.showReadingRangeDialog = true;
            this.fetchCategories();
        },
        fetchCategories() {
            if (this.allCategories.length > 0) return;
            this.loadingCategories = true;
            this.$backend("/categories")
                .then(rsp => {
                    if (rsp.err === "ok") {
                        this.allCategories = rsp.categories || [];
                    }
                })
                .finally(() => { this.loadingCategories = false; });
        },
        onTagSearchInput(val) {
            if (this.tagSearchTimer) clearTimeout(this.tagSearchTimer);
            if (!val || val.trim().length === 0) {
                this.tagSuggestions = [];
                return;
            }
            this.tagSearchTimer = setTimeout(() => {
                this.loadingTags = true;
                this.$backend("/tags/search?q=" + encodeURIComponent(val.trim()) + "&limit=20")
                    .then(rsp => {
                        if (rsp.err === "ok") {
                            this.tagSuggestions = rsp.tags || [];
                        }
                    })
                    .finally(() => { this.loadingTags = false; });
            }, 300);
        },
        addTag(name) {
            if (!this.readingRange.selectedTags.includes(name)) {
                this.readingRange.selectedTags.push(name);
            }
        },
        removeTag(name) {
            this.readingRange.selectedTags = this.readingRange.selectedTags.filter(t => t !== name);
        },
        saveReadingRange() {
            this.savingReadingRange = true;
            const payload = {
                id: this.readingRangeUserId,
                read_limit: this.readingRange.mode,
                limit_categories: this.readingRange.mode === 0 ? "" : this.readingRange.selectedCategories.join(','),
                limit_tags: this.readingRange.mode === 0 ? "" : this.readingRange.selectedTags.join(','),
            };
            this.$backend("/admin/users", {
                body: JSON.stringify(payload),
                method: "POST",
            })
            .then(rsp => {
                if (rsp.err !== "ok") {
                    this.$alert("error", rsp.msg);
                } else {
                    this.$alert("success", this.$t('admin.users.reading_range_save_ok'));
                    this.showReadingRangeDialog = false;
                    // Update local item to reflect saved state
                    const user = this.items.find(u => u.id === this.readingRangeUserId);
                    if (user) {
                        user.read_limit = payload.read_limit;
                        user.limit_categories = payload.limit_categories;
                        user.limit_tags = payload.limit_tags;
                    }
                }
            })
            .finally(() => { this.savingReadingRange = false; });
        },
        validatePassword: function(v) {
            if ( v.length < 6 ) {
                return '最少6个字符';
            }
            return v == this.newUser.password || "密码不匹配";
        },
        closeAddUserDialog() {
            this.showAddUserDialog = false;
            this.addUserError = "";
            this.newUser = {
                username: "",
                password: "",
                password2: "",
                nickname: "",
                email: ""
            };
            if (this.$refs.addUserForm) {
                this.$refs.addUserForm.resetValidation();
            }
        },
        addUser() {
            if (!this.$refs.addUserForm.validate()) {
                return false;
            }

            this.addingUser = true;
            this.addUserError = "";

            var data = new URLSearchParams();
            data.append('username', this.newUser.username);
            data.append('password', this.newUser.password);
            data.append('nickname', this.newUser.nickname);
            data.append('email', this.newUser.email);

            this.$backend('/user/new', {
                method: 'POST',
                body: data,
            })
            .then(rsp => {
                if (rsp.err != 'ok') {
                    this.addUserError = rsp.msg;
                } else {
                    this.closeAddUserDialog();
                    this.getDataFromApi(); // 刷新用户列表
                    this.$alert("success", rsp.msg || "用户添加成功");
                }
            })
            .finally(() => {
                this.addingUser = false;
            });
        },
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
            this.$backend("/admin/users?" + data.toString())
                .then((rsp) => {
                    if (rsp.err != "ok") {
                        this.items = [];
                        this.total = 0;
                        alert(rsp.msg);
                        return false;
                    }
                    this.items = rsp.users.items;
                    this.total = rsp.users.total;
                    this.allowReadRangeSetting = rsp.settings?.allow_read_range_setting || false;
                })
                .finally(() => {
                    this.loading = false;
                });
        },
        setuser(uid, action) {
            action.id = uid;
            this.$backend("/admin/users", {
                body: JSON.stringify(action),
                method: "POST",
            }).then((rsp) => {
                if (rsp.err != "ok") {
                    this.$alert("error", rsp.msg);
                }
            });
        },
    },
};
</script>
