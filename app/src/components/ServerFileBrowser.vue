<template>
    <AppDialog
        v-model="show"
        type="action"
        :title="$t('upload.serverBrowseTitle')"
        icon="mdi-server"
        color="blue darken-4"
        max-width="640"
        :dismiss-label="$t('common.cancel')"
        :confirm-text="$t('upload.serverBrowseImport', { count: selected.length })"
        confirm-dark
        :confirm-loading="importing"
        :confirm-disabled="!selected.length"
        @confirm="doImport"
    >
        <div class="d-flex align-center flex-wrap mb-2">
            <v-chip :color="path ? '#003153' : 'amber darken-3'" dark small class="mr-1" @click="goTo('')">
                <v-icon small>mdi-home</v-icon>
                <span class="ml-1">/data</span>
            </v-chip>
            <template v-for="(crumb, idx) in crumbs">
                <v-icon :key="'sep' + idx" small>mdi-chevron-right</v-icon>
                <v-chip
                    :key="crumb.path"
                    :color="idx === crumbs.length - 1 ? 'amber darken-3' : '#003153'"
                    dark
                    small
                    class="mx-1"
                    @click="goTo(crumb.path)"
                >
                    {{ crumb.name }}
                </v-chip>
            </template>
        </div>

        <v-list dense class="py-0 server-file-list">
            <v-list-item class="server-file-head">
                <v-list-item-action class="mr-2">
                    <v-checkbox
                        :input-value="allChecked"
                        :indeterminate="someChecked && !allChecked"
                        :disabled="!files.length"
                        hide-details
                        class="mt-0 pt-0"
                        @change="toggleAll"
                    ></v-checkbox>
                </v-list-item-action>
                <v-list-item-content>
                    <div class="d-flex align-center">
                        <span class="sort-col name-col" @click="toggleSort('name')">
                            {{ $t('upload.serverBrowseName') }}
                            <v-icon small>{{ sortIcon('name') }}</v-icon>
                        </span>
                        <v-spacer></v-spacer>
                        <span class="sort-col time-col" @click="toggleSort('mtime')">
                            {{ $t('upload.serverBrowseModified') }}
                            <v-icon small>{{ sortIcon('mtime') }}</v-icon>
                        </span>
                    </div>
                </v-list-item-content>
            </v-list-item>
            <v-divider></v-divider>

            <div class="server-file-body">
                <v-progress-linear v-if="loading" indeterminate height="2"></v-progress-linear>
                <v-list-item v-if="path" @click="goTo(parentPath)">
                    <v-list-item-action class="mr-2"><v-icon color="amber darken-3">mdi-folder-arrow-up</v-icon></v-list-item-action>
                    <v-list-item-content><v-list-item-title>..</v-list-item-title></v-list-item-content>
                </v-list-item>
                <v-list-item v-for="item in sortedEntries" :key="item.name" @click="onRowClick(item)">
                    <v-list-item-action class="mr-2">
                        <v-icon v-if="item.is_dir" color="amber darken-3">mdi-folder</v-icon>
                        <v-checkbox
                            v-else
                            :input-value="isSelected(item)"
                            hide-details
                            class="mt-0 pt-0"
                            @click.stop
                            @change="toggleOne(item)"
                        ></v-checkbox>
                    </v-list-item-action>
                    <v-list-item-content>
                        <div class="d-flex align-center">
                            <span class="text-truncate">{{ item.name }}</span>
                            <v-spacer></v-spacer>
                            <span class="grey--text text-caption ml-2 flex-shrink-0">{{ formatTime(item.mtime) }}</span>
                        </div>
                    </v-list-item-content>
                </v-list-item>
                <div v-if="!loading && !sortedEntries.length" class="text-center grey--text py-6">
                    {{ $t('upload.serverBrowseEmpty') }}
                </div>
            </div>
        </v-list>
    </AppDialog>
</template>

<script>
export default {
    props: {
        value: { type: Boolean, default: false },
    },
    data: () => ({
        path: '',
        entries: [],
        selected: [],
        loading: false,
        importing: false,
        sortKey: 'name',
        sortAsc: true,
    }),
    computed: {
        show: {
            get() {
                return this.value;
            },
            set(val) {
                this.$emit('input', val);
            },
        },
        segments() {
            return this.path ? this.path.split('/') : [];
        },
        crumbs() {
            return this.segments.map((name, idx) => ({ name, path: this.segments.slice(0, idx + 1).join('/') }));
        },
        parentPath() {
            return this.segments.slice(0, -1).join('/');
        },
        files() {
            return this.entries.filter((e) => !e.is_dir);
        },
        sortedEntries() {
            const dir = this.sortAsc ? 1 : -1;
            const key = this.sortKey;
            const cmp = (a, b) => (key === 'mtime' ? a.mtime - b.mtime : a.name.localeCompare(b.name, undefined, { numeric: true }));
            return [...this.entries].sort((a, b) => {
                if (a.is_dir !== b.is_dir) return a.is_dir ? -1 : 1;
                return cmp(a, b) * dir;
            });
        },
        allChecked() {
            return this.files.length > 0 && this.files.every((f) => this.isSelected(f));
        },
        someChecked() {
            return this.files.some((f) => this.isSelected(f));
        },
    },
    watch: {
        value(val) {
            if (val) {
                this.selected = [];
                this.load('');
            }
        },
    },
    methods: {
        fullPath(item) {
            return this.path ? `${this.path}/${item.name}` : item.name;
        },
        isSelected(item) {
            return this.selected.includes(this.fullPath(item));
        },
        toggleOne(item) {
            const p = this.fullPath(item);
            this.selected = this.selected.includes(p) ? this.selected.filter((s) => s !== p) : [...this.selected, p];
        },
        toggleAll(checked) {
            const current = this.files.map((f) => this.fullPath(f));
            const rest = this.selected.filter((s) => !current.includes(s));
            this.selected = checked ? [...rest, ...current] : rest;
        },
        onRowClick(item) {
            if (item.is_dir) {
                this.goTo(this.fullPath(item));
            } else {
                this.toggleOne(item);
            }
        },
        goTo(path) {
            this.load(path);
        },
        toggleSort(key) {
            if (this.sortKey === key) {
                this.sortAsc = !this.sortAsc;
            } else {
                this.sortKey = key;
                this.sortAsc = key === 'name';
            }
        },
        sortIcon(key) {
            if (this.sortKey !== key) return 'mdi-swap-vertical';
            return this.sortAsc ? 'mdi-arrow-up' : 'mdi-arrow-down';
        },
        formatTime(ts) {
            const d = new Date(ts * 1000);
            const p = (n) => String(n).padStart(2, '0');
            return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
        },
        async load(path) {
            this.loading = true;
            try {
                const rsp = await this.$backend(`/admin/server_files/list?path=${encodeURIComponent(path)}`);
                if (rsp.err !== 'ok') {
                    this.$alert('error', rsp.msg);
                    return;
                }
                this.path = rsp.path;
                this.entries = rsp.entries;
            } catch (error) {
                this.$alert('error', this.$t('upload.serverBrowseFailed'));
            } finally {
                this.loading = false;
            }
        },
        async doImport() {
            this.importing = true;
            try {
                const rsp = await this.$backend('/admin/server_files/import', {
                    method: 'POST',
                    body: JSON.stringify({ paths: this.selected }),
                });
                if (rsp.err !== 'ok') {
                    this.$alert('error', rsp.msg);
                    return;
                }
                this.show = false;
                this.$emit('imported', { importId: rsp.import_id, count: rsp.file_count });
            } catch (error) {
                this.$alert('error', this.$t('upload.serverBrowseFailed'));
            } finally {
                this.importing = false;
            }
        },
    },
};
</script>

<style scoped>
.server-file-body {
    max-height: 360px;
    overflow-y: auto;
}

.sort-col {
    cursor: pointer;
    user-select: none;
    font-size: 13px;
    font-weight: 500;
}
</style>
