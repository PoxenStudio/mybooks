<template>
    <v-card>
        <v-card-title> {{ $t('admin.users.title') }} </v-card-title>
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
