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
            item-key="id"
            :expanded="expandedItems"
            class="elevation-1"
        >
            <template v-slot:item.total_reading_seconds="{ item }">
                {{ (item.total_reading_seconds / 3600).toFixed(1) }}
            </template>
            <template v-slot:item.download_quota="{ item }">
                {{ item.download_quota_used || 0 }}/{{ item.download_quota_limit ? item.download_quota_limit : '∞' }}
            </template>
            <template v-slot:item.detail="{ item }">
                <div>
                    <span v-if="item.extra.upload_history_count"> {{ $t('admin.users.upload_cnt', { count: item.extra.upload_history_count }) }} </span>
                </div>
                <v-btn small color="primary" class="rounded-btn" @click="toggleStatsDetail(item)">
                    {{ expandedUserId === item.id ? $t('admin.users.collapse_detail') : $t('admin.users.expand_detail') }}
                </v-btn>
            </template>
            <template v-slot:expanded-item="{ headers, item }">
                <td :colspan="headers.length" v-if="expandedUserId === item.id">
                    <div class="user-detail-banner">
                        <div class="user-detail-item">
                            <div class="user-detail-label">{{ $t('admin.users.provider') }}</div>
                            <div class="user-detail-value">{{ item.provider }}</div>
                        </div>
                        <div class="user-detail-item">
                            <div class="user-detail-label">{{ $t('admin.users.create_time') }}</div>
                            <div class="user-detail-value">{{ splitDateTime(item.create_time).date }} {{ splitDateTime(item.create_time).time }}</div>
                        </div>
                        <div class="user-detail-item">
                            <div class="user-detail-label">{{ $t('admin.users.access_time') }}</div>
                            <div class="user-detail-value">{{ splitDateTime(item.access_time).date }} {{ splitDateTime(item.access_time).time }}</div>
                        </div>
                        <div class="user-detail-item">
                            <div class="user-detail-label">{{ $t('admin.users.login_ip') }}</div>
                            <div class="user-detail-value">{{ item.extra.login_ip }}</div>
                        </div>
                    </div>
                    <reading-stats-banner :uid="item.id" :show-title="false" />
                </td>
            </template>
            <template v-slot:item.actions="{ item }">
                <v-menu offset-y right>
                    <template v-slot:activator="{ on }">
                        <v-btn color="#1B813E" class="white--text rounded-btn" small v-on="on">{{ $t('admin.users.modify_permissions') }} <v-icon small>mdi-dots-vertical</v-icon></v-btn>
                    </template>
                    <v-list dense>
                        <template v-for="perm in permissions">
                            <v-list-item :key="'disable-' + perm.name" v-if="item[perm.name]">
                                <v-list-item-title>
                                    <v-icon color="success">mdi-account-check</v-icon> {{ $t('admin.users.allowed', { permission: perm.text }) }}
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
                    </v-list>
                </v-menu>
                <v-btn small color="primary" class="white--text rounded-btn" @click="openReadingRangeDialog(item)" v-if="allowReadRangeSetting">{{ $t('admin.users.set_reading_range') }}</v-btn>
                <v-btn small color="#1B813E" class="white--text rounded-btn" v-if="enableDownloadQuota" @click="openDownloadQuotaMenu(item, $event)">{{ $t('admin.users.set_download_quota') }}</v-btn>
                <v-menu
                    v-if="enableDownloadQuota"
                    v-model="item._quotaMenuOpen"
                    absolute
                    :position-x="quotaMenuX"
                    :position-y="quotaMenuY"
                    :close-on-content-click="false"
                >
                    <v-card min-width="300">
                        <v-card-text class="pb-0">
                            <v-form :ref="'downloadQuotaForm-' + item.id">
                                <v-text-field
                                    v-model.number="item._quotaEditValue"
                                    :label="$t('admin.users.download_quota_label')"
                                    type="number"
                                    min="-1"
                                    max="1000"
                                    :rules="[rules.downloadQuota]"
                                    autofocus
                                    class="quota-input"
                                ></v-text-field>
                            </v-form>
                        </v-card-text>
                        <v-card-actions>
                            <v-spacer></v-spacer>
                            <v-btn text @click="item._quotaMenuOpen = false">{{ $t('admin.users.cancel') }}</v-btn>
                            <v-btn color="primary" @click="saveDownloadQuota(item)" :loading="savingDownloadQuota">{{ $t('admin.users.save') }}</v-btn>
                        </v-card-actions>
                    </v-card>
                </v-menu>
                <v-menu offset-y right>
                    <template v-slot:activator="{ on }">
                        <v-btn color="primary" class="rounded-btn" small v-on="on">{{ $t('admin.users.account_management') }} <v-icon small>mdi-dots-vertical</v-icon></v-btn>
                    </template>
                    <v-list dense>
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
                            v-if="item.allow_review === false"
                            @click="
                                setuser(item.id, { allow_review: true });
                                item.allow_review = true;
                            "
                        >
                            <v-list-item-title> {{ $t('admin.users.unban_review') }} </v-list-item-title>
                        </v-list-item>
                        <v-list-item
                            v-else
                            @click="
                                setuser(item.id, { allow_review: false });
                                item.allow_review = false;
                            "
                        >
                            <v-list-item-title> {{ $t('admin.users.ban_review') }} </v-list-item-title>
                        </v-list-item>
                        <v-list-item
                            @click="openChangePasswordDialog(item)"
                        >
                            <v-list-item-title> {{ $t('admin.users.change_password') }} </v-list-item-title>
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
        <reading-range-dialog
            ref="readingRangeDialog"
            :saving="savingReadingRange"
            @save="saveReadingRange"
        ></reading-range-dialog>

        <!-- Change Password Dialog -->
        <AppDialog
            v-model="showChangePasswordDialog"
            type="action"
            :title="$t('admin.users.change_password_dialog_title')"
            max-width="420px"
            dismiss-icon
            :confirm-text="$t('admin.users.change_password_save')"
            :confirm-loading="changingPassword"
            @dismiss="closeChangePasswordDialog"
            @confirm="submitChangePassword"
        >
            <v-form ref="changePasswordForm" @submit.prevent="submitChangePassword">
                <v-text-field
                    v-model="changePassword.password"
                    :label="$t('admin.users.new_password')"
                    type="password"
                    prepend-icon="mdi-lock"
                    autocomplete="new-password"
                    :rules="[rules.pass]"
                    required
                ></v-text-field>
                <v-text-field
                    v-model="changePassword.password2"
                    :label="$t('admin.users.confirm_new_password')"
                    type="password"
                    prepend-icon="mdi-lock-outline"
                    autocomplete="new-password2"
                    :rules="[validateChangePassword]"
                    required
                ></v-text-field>
            </v-form>
            <v-alert v-if="changePasswordError" type="error" class="mt-2">{{ changePasswordError }}</v-alert>
        </AppDialog>

        <!-- Add User Dialog -->
        <AppDialog
            v-model="showAddUserDialog"
            type="action"
            :title="$t('admin.users.add_user')"
            max-width="500px"
            dismiss-icon
            :confirm-text="$t('admin.users.add')"
            :confirm-loading="addingUser"
            @dismiss="closeAddUserDialog"
            @confirm="addUser"
        >
            <v-form ref="addUserForm" @submit.prevent="addUser">
                <v-text-field
                    required
                    prepend-icon="mdi-account"
                    v-model="newUser.username"
                    :label="$t('admin.users.username')"
                    type="text"
                    autocomplete="new-username"
                    :rules="[rules.user]"
                ></v-text-field>
                <v-text-field
                    required
                    prepend-icon="mdi-lock"
                    v-model="newUser.password"
                    :label="$t('admin.users.password')"
                    type="password"
                    autocomplete="new-password"
                    :rules="[rules.pass]"
                ></v-text-field>
                <v-text-field
                    required
                    prepend-icon="mdi-lock"
                    v-model="newUser.password2"
                    :label="$t('admin.users.confirm_password')"
                    type="password"
                    autocomplete="new-password2"
                    :rules="[validatePassword]"
                ></v-text-field>
                <v-text-field
                    required
                    prepend-icon="mdi-account-outline"
                    v-model="newUser.nickname"
                    :label="$t('admin.users.nickname')"
                    type="text"
                    autocomplete="new-nickname"
                    :rules="[rules.nick]"
                ></v-text-field>
                <v-text-field
                    required
                    prepend-icon="mdi-email"
                    v-model="newUser.email"
                    :label="$t('admin.users.email')"
                    type="text"
                    autocomplete="new-email"
                    :rules="[rules.email]"
                ></v-text-field>
            </v-form>
            <v-alert v-if="addUserError" type="error">{{ addUserError }}</v-alert>
        </AppDialog>
    </v-card>
</template>

<script>
import ReadingStatsBanner from '~/components/ReadingStatsBanner.vue';
import ReadingRangeDialog from '~/components/ReadingRangeDialog.vue';

export default {
    components: { ReadingStatsBanner, ReadingRangeDialog },
    data: () => ({
        page: 1,
        items: [],
        total: 0,
        loading: true,
        expandedUserId: null,
        options: {},
        baseHeaders: [],
        permissions: [],
        enableDownloadQuota: false,
        showAddUserDialog: false,
        addingUser: false,
        addUserError: "",
        // Reading range dialog
        savingReadingRange: false,
        readingRangeUserId: null,
        allowReadRangeSetting: false,
        // Download quota menu (open state & edit value live per-row on each item, see getDataFromApi)
        savingDownloadQuota: false,
        quotaMenuX: 0,
        quotaMenuY: 0,
        // Change password dialog
        showChangePasswordDialog: false,
        changingPassword: false,
        changePasswordUserId: null,
        changePasswordError: "",
        changePassword: { password: "", password2: "" },
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
            downloadQuota: v => (Number.isInteger(v) && v >= -1 && v <= 1000) || '-1 ~ 1000 的整数',
        },
    }),
    created() {
        this.baseHeaders = [
            { text: this.$t('admin.users.id'), sortable: true, value: "id", width: 80 },
            { text: this.$t('admin.users.username'), sortable: true, value: "username" },
            { text: this.$t('admin.users.nickname'), sortable: false, value: "name" },
            { text: this.$t('admin.users.email'), sortable: true, value: "email" },
            { text: this.$t('admin.users.total_reading_hours'), sortable: true, value: "total_reading_seconds" },
            { text: this.$t('admin.users.download_count'), sortable: true, value: "download_count" },
            { text: this.$t('admin.users.download_quota'), sortable: false, value: "download_quota" },
            { text: this.$t('admin.users.push_count'), sortable: true, value: "push_count" },
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
        expandedItems() {
            return this.items.filter((i) => i.id === this.expandedUserId);
        },
        headers() {
            return this.baseHeaders.filter((h) => h.value !== "download_quota" || this.enableDownloadQuota);
        },
    },
    methods: {
        splitDateTime(value) {
            if (!value) {
                return { date: "", time: "" };
            }
            const [date, time = ""] = value.split(" ");
            return { date, time };
        },
        toggleStatsDetail(item) {
            this.expandedUserId = this.expandedUserId === item.id ? null : item.id;
        },
        openReadingRangeDialog(item) {
            this.readingRangeUserId = item.id;
            this.$refs.readingRangeDialog.open({
                mode: item.read_limit || 0,
                categories: item.limit_categories || "",
                tags: item.limit_tags || "",
            });
        },
        saveReadingRange(range) {
            this.savingReadingRange = true;
            const payload = {
                id: this.readingRangeUserId,
                read_limit: range.mode,
                limit_categories: range.categories,
                limit_tags: range.tags,
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
                    this.$refs.readingRangeDialog.close();
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
        openDownloadQuotaMenu(item, event) {
            // 对话框右侧与按钮右侧对齐，顶部在按钮下方（对话框宽度对应 v-card 的 min-width="300"）
            const rect = event.currentTarget.getBoundingClientRect();
            this.quotaMenuX = rect.right - 300;
            this.quotaMenuY = rect.bottom;
            // 每次打开都重置为服务端当前值，避免上次未保存的修改残留
            item._quotaEditValue = item.download_daily_quota ?? -1;
            item._quotaMenuOpen = true;
            this.$nextTick(() => {
                const form = this.$refs['downloadQuotaForm-' + item.id];
                if (form) form.resetValidation();
            });
        },
        saveDownloadQuota(item) {
            const form = this.$refs['downloadQuotaForm-' + item.id];
            if (form && !form.validate()) return;
            this.savingDownloadQuota = true;
            this.$backend("/admin/users", {
                body: JSON.stringify({ id: item.id, download_daily_quota: item._quotaEditValue }),
                method: "POST",
            })
            .then(rsp => {
                if (rsp.err !== "ok") {
                    this.$alert("error", rsp.msg);
                } else {
                    this.$alert("success", this.$t('admin.users.download_quota_save_ok'));
                    item._quotaMenuOpen = false;
                    this.getDataFromApi();
                }
            })
            .finally(() => { this.savingDownloadQuota = false; });
        },
        validatePassword: function(v) {
            if ( v.length < 6 ) {
                return '最少6个字符';
            }
            return v == this.newUser.password || "密码不匹配";
        },
        openChangePasswordDialog(item) {
            this.changePasswordUserId = item.id;
            this.changePassword = { password: "", password2: "" };
            this.changePasswordError = "";
            this.showChangePasswordDialog = true;
            this.$nextTick(() => {
                if (this.$refs.changePasswordForm) this.$refs.changePasswordForm.resetValidation();
            });
        },
        closeChangePasswordDialog() {
            this.showChangePasswordDialog = false;
            this.changePasswordError = "";
            this.changePassword = { password: "", password2: "" };
            if (this.$refs.changePasswordForm) this.$refs.changePasswordForm.resetValidation();
        },
        validateChangePassword(v) {
            if (v.length < 6) return '最少6个字符';
            return v === this.changePassword.password || this.$t('admin.users.password_mismatch');
        },
        submitChangePassword() {
            if (!this.$refs.changePasswordForm.validate()) return;
            this.changingPassword = true;
            this.changePasswordError = "";
            this.$backend("/admin/users", {
                body: JSON.stringify({ id: this.changePasswordUserId, password: this.changePassword.password }),
                method: "POST",
            })
            .then(rsp => {
                if (rsp.err !== "ok") {
                    this.changePasswordError = rsp.msg;
                } else {
                    this.$alert("success", this.$t('admin.users.change_password_ok'));
                    this.closeChangePasswordDialog();
                }
            })
            .finally(() => { this.changingPassword = false; });
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
            this.expandedUserId = null;
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
                    this.items = (rsp.users.items || []).map((u) => ({
                        ...u,
                        _quotaMenuOpen: false,
                        _quotaEditValue: u.download_daily_quota ?? -1,
                    }));
                    this.total = rsp.users.total;
                    this.allowReadRangeSetting = rsp.settings?.allow_read_range_setting || false;
                    this.enableDownloadQuota = rsp.settings?.enable_download_quota || false;
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

<style scoped>
.v-application .v-btn.rounded-btn:not(.v-btn--round):not(.v-btn--icon) {
    border-radius: 6px !important;
}
.user-detail-banner {
    display: grid;
    grid-template-columns: 1fr 1fr;
    grid-template-rows: 1fr 1fr;
    gap: 12px;
    padding: 12px 16px;
    margin: 8px 0 16px;
}
.user-detail-label {
    font-size: 12px;
}
.user-detail-value {
    font-size: 14px;
    font-weight: 500;
}
.quota-input >>> .v-label {
    line-height: 1.2;
}
.quota-input >>> .v-input__control {
    margin-top: 12px;
}
</style>
