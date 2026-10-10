<template>
  <v-card>
    <v-card-title>{{ $t('share.manage.title') }}</v-card-title>

    <v-data-table
      :headers="headers"
      :items="items"
      :loading="loading"
      :server-items-length="total"
      :options.sync="tableOptions"
      :footer-props="{ 'items-per-page-options': [10, 50, 100] }"
      item-key="id"
      class="elevation-1"
    >
      <template v-slot:item.title="{ item }">
        <div class="d-flex align-center py-1">
          <v-img :src="item.thumb" :aspect-ratio="11 / 15" max-width="36" class="flex-grow-0 mr-3" style="border-radius: 4px"></v-img>
          <nuxt-link :to="`/book/${item.book_id}`">{{ item.title || `#${item.book_id}` }}</nuxt-link>
        </div>
      </template>

      <template v-slot:item.permissions="{ item }">
        <v-chip v-if="item.allow_read" x-small color="primary" text-color="white" class="mr-1">{{ $t('share.manage.read') }}</v-chip>
        <v-chip v-if="item.allow_download" x-small color="teal" text-color="white">{{ $t('share.manage.download') }}</v-chip>
      </template>

      <template v-slot:item.expire_time="{ item }">
        {{ item.expire_time ? formatTime(item.expire_time) : $t('share.expireForever') }}
      </template>

      <template v-slot:item.view_count="{ item }">
        {{ item.view_count }} / {{ item.max_views > 0 ? item.max_views : '∞' }}
      </template>

      <template v-slot:item.state="{ item }">
        <v-chip small :color="stateColor(item.state)" text-color="white">{{ $t('share.state.' + item.state) }}</v-chip>
      </template>

      <template v-slot:item.update_time="{ item }">
        {{ formatTime(item.update_time) }}
      </template>

      <template v-slot:item.actions="{ item }">
        <v-btn icon small :title="$t('share.copyLink')" @click="copyLink(item)">
          <v-icon small>mdi-content-copy</v-icon>
        </v-btn>
        <v-btn v-if="item.status === 1" icon small :title="$t('share.cancelShare')" @click="askCancel(item)">
          <v-icon small>mdi-link-off</v-icon>
        </v-btn>
        <v-btn icon small :title="$t('common.delete')" @click="askDelete(item)">
          <v-icon small>mdi-delete-outline</v-icon>
        </v-btn>
      </template>
    </v-data-table>

    <AppDialog
      v-model="cancelDialog"
      type="confirm"
      :title="$t('share.cancelShare')"
      color="deep-orange"
      confirm-dark
      max-width="420"
      :confirm-text="$t('share.cancelShare')"
      :confirm-loading="acting"
      @confirm="doAction('cancel')"
    >
      {{ $t('share.cancelConfirm') }}
    </AppDialog>

    <AppDialog
      v-model="deleteDialog"
      type="confirm"
      :title="$t('share.manage.deleteTitle')"
      color="deep-orange"
      confirm-dark
      max-width="420"
      :confirm-text="$t('common.delete')"
      :confirm-loading="acting"
      @confirm="doAction('delete')"
    >
      {{ $t('share.manage.deleteConfirm') }}
    </AppDialog>
  </v-card>
</template>

<script>
export default {
  data() {
    return {
      items: [],
      total: 0,
      loading: false,
      acting: false,
      tableOptions: { page: 1, itemsPerPage: 10 },
      current: null,
      cancelDialog: false,
      deleteDialog: false,
    };
  },
  head() {
    return { title: this.$t('share.manage.title') };
  },
  computed: {
    headers() {
      return [
        { text: this.$t('share.manage.colBook'), value: 'title', sortable: false },
        { text: this.$t('share.manage.colPermissions'), value: 'permissions', sortable: false },
        { text: this.$t('share.manage.colExpire'), value: 'expire_time', sortable: false },
        { text: this.$t('share.manage.colViews'), value: 'view_count', sortable: false },
        { text: this.$t('share.manage.colState'), value: 'state', sortable: false },
        { text: this.$t('share.manage.colUpdated'), value: 'update_time', sortable: false },
        { text: this.$t('share.manage.colActions'), value: 'actions', sortable: false },
      ];
    },
  },
  watch: {
    tableOptions: {
      handler() {
        this.fetchItems();
      },
      deep: true,
    },
  },
  mounted() {
    this.fetchItems();
  },
  methods: {
    formatTime(value) {
      return value ? new Date(value).toLocaleString() : '';
    },
    stateColor(state) {
      if (state === 'active') return 'success';
      if (state === 'cancelled') return 'grey';
      return 'orange';
    },
    fetchItems() {
      this.loading = true;
      const size = this.tableOptions.itemsPerPage || 10;
      const start = ((this.tableOptions.page || 1) - 1) * size;
      this.$backend(`/admin/shares?start=${start}&limit=${size}`)
        .then((rsp) => {
          if (rsp.err !== 'ok') {
            this.$alert('error', rsp.msg);
            return;
          }
          this.items = rsp.shares || [];
          this.total = rsp.total || 0;
        })
        .finally(() => {
          this.loading = false;
        });
    },
    async copyLink(item) {
      try {
        await navigator.clipboard.writeText(window.location.origin + item.path);
        this.$alert('success', this.$t('share.copied'));
      } catch (e) {
        this.$alert('error', this.$t('message.operationFailed'));
      }
    },
    askCancel(item) {
      this.current = item;
      this.cancelDialog = true;
    },
    askDelete(item) {
      this.current = item;
      this.deleteDialog = true;
    },
    async doAction(action) {
      if (this.acting || !this.current) return;
      this.acting = true;
      try {
        const rsp = await this.$backend(`/admin/share/${this.current.id}/${action}`, { method: 'POST' });
        if (rsp.err === 'ok') {
          this.cancelDialog = false;
          this.deleteDialog = false;
          this.$alert('success', rsp.msg || this.$t('message.operationSuccess'));
          this.fetchItems();
        } else {
          this.$alert('error', rsp.msg || this.$t('message.operationFailed'));
        }
      } catch (e) {
        this.$alert('error', this.$t('message.networkError'));
      } finally {
        this.acting = false;
      }
    },
  },
};
</script>
