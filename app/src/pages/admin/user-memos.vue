<template>
  <v-card>
    <v-card-title>
      {{ $t('memos.pageTitle') }}
    </v-card-title>

    <v-data-table
      :headers="headers"
      :items="items"
      :loading="loading"
      :sort-by.sync="sortBy"
      :sort-desc.sync="sortDesc"
      :footer-props="{ 'items-per-page-options': [20, 50, 100] }"
      class="elevation-1"
    >
      <template v-slot:item.memo_type="{ item }">
        <v-chip small :color="getTypeColor(item.memo_type)" text-color="white">
          {{ getTypeName(item.memo_type) }}
        </v-chip>
      </template>
      
      <template v-slot:item.stage="{ item }">
        <v-chip small :color="item.stage === 'done' ? 'success' : 'warning'" text-color="white">
          {{ item.stage === 'done' ? $t('memos.stageDone') : $t('memos.stageNew') }}
        </v-chip>
      </template>

      <template v-slot:item.actions="{ item }">
        <v-btn small color="success" class="white--text mr-2 mb-1" v-if="item.stage !== 'done'" @click="openReplyDialog(item)">
          <v-icon small left>mdi-check</v-icon>
          {{ $t('memos.actionComplete') }}
        </v-btn>
        <v-btn small color="error" class="white--text mb-1" @click="deleteItem(item)">
          <v-icon small left>mdi-delete</v-icon>
          {{ $t('memos.actionDelete') }}
        </v-btn>
      </template>
    </v-data-table>

    <!-- Reply Dialog -->
    <v-dialog v-model="showReplyDialog" max-width="500px" persistent>
      <v-card>
        <v-card-title>{{ $t('memos.replyDialogTitle') }}</v-card-title>
        <v-card-text>
          <v-textarea
            v-model="replyContent"
            :placeholder="$t('memos.replyPlaceholder')"
            outlined
            rows="3"
            hide-details
          ></v-textarea>
        </v-card-text>
        <v-card-actions>
          <v-spacer></v-spacer>
          <v-btn text @click="showReplyDialog = false">{{ $t('memos.replyCancel') }}</v-btn>
          <v-btn color="primary" @click="submitReply" :loading="replySubmitting">{{ $t('memos.replySubmit') }}</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </v-card>
</template>

<script>
export default {
  data() {
    return {
      items: [],
      loading: false,
      sortBy: 'create_date',
      sortDesc: true,
      showReplyDialog: false,
      replySubmitting: false,
      replyContent: '',
      currentMemoItem: null,
    };
  },
  head() {
    return { title: this.$t('memos.pageTitle') };
  },
  computed: {
    headers() {
      return [
        { text: this.$t('memos.colId'), value: 'id', sortable: true, width: '80px' },
        { text: this.$t('memos.colReaderName'), value: 'reader_name', sortable: true, width: '15%' },
        { text: this.$t('memos.colType'), value: 'memo_type', sortable: true, width: '10%' },
        { text: this.$t('memos.colContent'), value: 'memo', sortable: false, width: '35%' },
        { text: this.$t('memos.colStage'), value: 'stage', sortable: true, width: '10%' },
        { text: this.$t('memos.colDate'), value: 'create_date', sortable: true, width: '15%' },
        { text: this.$t('memos.colActions'), value: 'actions', sortable: false },
      ];
    },
  },
  mounted() {
    this.fetchItems();
  },
  methods: {
    fetchItems() {
      this.loading = true;
      this.$backend('/user/memo?page=1&page_size=1000')
        .then(rsp => {
          if (rsp.err !== 'ok' || !rsp.data || !rsp.data.items) {
            this.$alert('error', rsp.msg);
            return;
          }
          this.items = rsp.data.items;
        })
        .finally(() => {
          this.loading = false;
        });
    },
    getTypeName(type) {
      if (type === 0) return this.$t('memos.typeSuggestion');
      if (type === 1) return this.$t('memos.typeRequest');
      if (type === 2) return this.$t('memos.typeHelp');
      return String(type);
    },
    getTypeColor(type) {
      if (type === 0) return 'blue';
      if (type === 1) return 'purple';
      if (type === 2) return 'orange';
      return 'grey';
    },
    openReplyDialog(item) {
      this.currentMemoItem = item;
      this.replyContent = this.$t('memos.replyDefault');
      this.showReplyDialog = true;
    },
    submitReply() {
      if (!this.replyContent.trim()) {
        this.replyContent = this.$t('memos.replyDefault');
      }
      this.replySubmitting = true;
      this.$backend('/user/memo', {
        method: 'POST',
        body: JSON.stringify({
          id: this.currentMemoItem.id,
          action: 'done',
          reply: this.replyContent.trim(),
        }),
      }).then(rsp => {
        if (rsp.err !== 'ok') {
          this.$alert('error', rsp.msg);
        } else {
          this.currentMemoItem.stage = 'done';
          this.currentMemoItem.reply = this.replyContent.trim();
          this.$alert('success', this.$t('memos.actionComplete') + ' OK');
          this.showReplyDialog = false;
        }
      }).finally(() => {
        this.replySubmitting = false;
      });
    },
    deleteItem(item) {
      if (!confirm(this.$t('memos.deleteConfirm'))) return;
      this.$backend('/user/memo', {
        method: 'DELETE',
        body: JSON.stringify({ id: item.id }),
      }).then(rsp => {
        if (rsp.err !== 'ok') {
          this.$alert('error', rsp.msg);
        } else {
          this.items = this.items.filter(i => i.id !== item.id);
        }
      });
    },
  },
};
</script>

<style scoped>
</style>
