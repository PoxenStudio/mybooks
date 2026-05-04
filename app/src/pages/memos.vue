<template>
  <v-card>
    <v-card-title>
      {{ $t('memos.pageTitle') }}
      <v-spacer></v-spacer>
      <v-btn color="primary" @click="openMemoDialog">
        <v-icon left>mdi-plus</v-icon>
        {{ $t('memos.actionNew') }}
      </v-btn>
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
        <v-chip small :color="getTypeColor(item.memo_type)" :text-color="getTypeFontColor(item.memo_type)">
          {{ getTypeName(item.memo_type) }}
        </v-chip>
      </template>

      <template v-slot:item.stage="{ item }">
        <v-chip small :color="item.stage === 'done' ? 'success' : 'warning'" text-color="black">
          {{ item.stage === 'done' ? $t('memos.stageDone') : $t('memos.stageNew') }}
        </v-chip>
      </template>
    </v-data-table>

    <v-dialog v-model="memoDialog" max-width="500px">
        <v-card>
            <v-card-title class="headline">{{ $t('appHeader.memoDialogTitle') }}</v-card-title>
            <v-card-text>
                <v-select
                    v-model="memoType"
                    :items="memoTypeOptions"
                    item-text="text"
                    item-value="value"
                    :label="$t('appHeader.memoTypeLabel')"
                    outlined
                    dense
                ></v-select>
                <v-textarea
                    v-model="memoContent"
                    :placeholder="$t('appHeader.memoContentPlaceholder')"
                    outlined
                    rows="6"
                    hide-details
                ></v-textarea>
            </v-card-text>
            <v-card-actions>
                <v-spacer></v-spacer>
                <v-btn text @click="memoDialog = false">{{ $t('appHeader.memoCancel') }}</v-btn>
                <v-btn color="primary" @click="submitMemo" :loading="memoSubmitting">{{ $t('appHeader.memoSubmit') }}</v-btn>
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

      memoDialog: false,
      memoType: 0,
      memoContent: '',
      memoSubmitting: false,
    };
  },
  head() {
    return { title: this.$t('memos.pageTitle') };
  },
  computed: {
    headers() {
      return [
        { text: this.$t('memos.colId'), value: 'id', sortable: true, width: '80px' },
        { text: this.$t('memos.colType'), value: 'memo_type', sortable: true, width: '10%' },
        { text: this.$t('memos.colContent'), value: 'memo', sortable: false, width: '35%' },
        { text: this.$t('memos.colReply'), value: 'reply', sortable: false, width: '25%' },
        { text: this.$t('memos.colStage'), value: 'stage', sortable: true, width: '10%' },
        { text: this.$t('memos.colDate'), value: 'create_date', sortable: true, width: '15%' },
      ];
    },
    memoTypeOptions() {
        return [
            { text: this.$t('appHeader.memoTypeSuggestion'), value: 0 },
            { text: this.$t('appHeader.memoTypeBookRequest'), value: 1 },
            { text: this.$t('appHeader.memoTypeHelp'), value: 2 },
        ];
    },
  },
  mounted() {
    this.fetchItems();
  },
  methods: {
    fetchItems() {
      this.loading = true;
      this.$backend('/user/memo?page=1&page_size=100')
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
    getTypeFontColor(type) {
      if (type === 0) return 'white';
      if (type === 1) return 'white';
      return 'black';
    },
    openMemoDialog() {
        this.memoType = 0;
        this.memoContent = '';
        this.memoDialog = true;
    },
    submitMemo() {
        if (!this.memoContent.trim()) {
            this.$store.commit('show_snackbar', { message: this.$t('appHeader.memoContentRequired'), color: 'error' });
            return;
        }
        this.memoSubmitting = true;
        this.$backend("/user/memo", {
            method: "POST",
            body: JSON.stringify({
                memo: this.memoContent.trim(),
                memo_type: this.memoType
            })
        }).then(rsp => {
            if (rsp.err === 'ok') {
                this.$store.commit('show_snackbar', { message: this.$t('appHeader.memoSubmitSuccess'), color: 'success' });
                this.memoDialog = false;
                this.fetchItems();
            } else {
                this.$store.commit('show_snackbar', { message: rsp.msg || this.$t('appHeader.memoSubmitFailed'), color: 'error' });
            }
        }).catch(() => {
            this.$store.commit('show_snackbar', { message: this.$t('appHeader.memoSubmitFailed'), color: 'error' });
        }).finally(() => {
            this.memoSubmitting = false;
        });
    }
  },
};
</script>

<style scoped>
</style>
