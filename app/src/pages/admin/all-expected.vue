<template>
  <v-card>
    <v-card-title>
      {{ $t('expected.allPageTitle') }}
    </v-card-title>
    <v-card-text class="pb-0">
      <v-select
        v-model="selectedUserId"
        :items="userFilterOptions"
        item-text="text"
        item-value="value"
        :label="$t('expected.filterByUser')"
        dense
        outlined
        hide-details
        style="max-width: 200px;"
      ></v-select>
    </v-card-text>

    <v-data-table
      :headers="headers"
      :items="filteredItems"
      :loading="loading"
      :sort-by.sync="sortBy"
      :sort-desc.sync="sortDesc"
      :footer-props="{ 'items-per-page-options': [10, 50, 100] }"
      class="elevation-1"
    >
      <template v-slot:item.actions="{ item }">
        <v-btn small color="error" class="white--text" @click="deleteItem(item)">
          <v-icon small left>mdi-delete</v-icon>
          {{ $t('expected.delete') }}
        </v-btn>
      </template>
    </v-data-table>

    <!-- Add Dialog -->
    <v-dialog v-model="showAddDialog" max-width="480px" persistent>
      <v-card>
        <v-card-title>
          {{ $t('expected.addDialogTitle') }}
          <v-spacer></v-spacer>
          <v-btn icon @click="closeAddDialog">
            <v-icon>mdi-close</v-icon>
          </v-btn>
        </v-card-title>
        <v-card-text>
          <v-form ref="addForm">
            <v-text-field
              v-model="newItem.title"
              :label="$t('expected.fieldTitle')"
              :rules="[v => !!v.trim() || $t('expected.titleRequired')]"
              required
              autofocus
            ></v-text-field>
            <v-text-field
              v-model="newItem.author"
              :label="$t('expected.fieldAuthor')"
            ></v-text-field>
            <v-text-field
              v-model="newItem.publisher"
              :label="$t('expected.fieldPublisher')"
            ></v-text-field>
          </v-form>
          <v-alert v-if="addError" type="error" class="mt-2">{{ addError }}</v-alert>
        </v-card-text>
        <v-card-actions>
          <v-spacer></v-spacer>
          <v-btn text @click="closeAddDialog">{{ $t('expected.cancel') }}</v-btn>
          <v-btn color="primary" @click="submitAdd" :loading="adding">{{ $t('expected.add') }}</v-btn>
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
      isAdmin: false,
      users: {},
      usersMap: {},
      selectedUserId: 0,
      loading: false,
      sortBy: 'create_time',
      sortDesc: true,
      showAddDialog: false,
      adding: false,
      addError: '',
      newItem: {
        title: '',
        author: '',
        publisher: '',
      },
    };
  },
  head() {
    return { title: this.$t('expected.pageTitle') };
  },
  computed: {
    userFilterOptions() {
      const opts = [{ text: this.$t('expected.allUsers'), value: 0 }];
      for (const [name, uid] of Object.entries(this.usersMap)) {
        if (String(uid) !== '0') {
          opts.push({ text: name, value: uid });
        }
      }
      return opts;
    },
    filteredItems() {
      if (!this.selectedUserId || String(this.selectedUserId) === '0') return this.items;
      return this.items.filter(item => String(item.reader_id) === String(this.selectedUserId));
    },
    headers() {
      return [
        { text: this.$t('expected.colReaderName'), value: 'reader_name', sortable: true, width: '20%' },
        { text: this.$t('expected.colTitle'), value: 'title', sortable: true, width: '25%' },
        { text: this.$t('expected.colAuthor'), value: 'author', sortable: true },
        { text: this.$t('expected.colPublisher'), value: 'publisher', sortable: true },
        { text: this.$t('expected.colCreateTime'), value: 'create_time', sortable: true },
        { text: this.$t('expected.colActions'), value: 'actions', sortable: false },
      ];
    },
  },
  mounted() {
    this.fetchItems();
  },
  methods: {
    fetchItems() {
      this.loading = true;
      this.$backend('/user/expected?user=0')
        .then(rsp => {
          if (rsp.err !== 'ok' || !rsp.data || !rsp.data.items) {
            this.$alert('error', rsp.msg);
            return;
          }
          this.items = rsp.data.items;
          this.isAdmin = rsp.data.is_admin;
          if (rsp.data.users && Object.keys(rsp.data.users).length > 0) {
            this.users = rsp.data.users;
            this.usersMap = { [this.$t('expected.allUsers')]: 0};
            for (const uid in rsp.data.users) {
              this.usersMap[rsp.data.users[uid]] = uid;
            }
          }
        })
        .finally(() => {
          this.loading = false;
        });
    },
    closeAddDialog() {
      this.showAddDialog = false;
      this.addError = '';
      this.newItem = { title: '', author: '', publisher: '' };
      if (this.$refs.addForm) {
        this.$refs.addForm.resetValidation();
      }
    },
    submitAdd() {
      if (!this.$refs.addForm.validate()) return;
      this.adding = true;
      this.addError = '';
      this.$backend('/user/expected', {
        method: 'POST',
        body: JSON.stringify({
          title: this.newItem.title.trim(),
          author: this.newItem.author.trim(),
          publisher: this.newItem.publisher.trim(),
        }),
      })
        .then(rsp => {
          if (rsp.err !== 'ok') {
            this.addError = rsp.msg;
          } else {
            this.items.unshift(rsp.item);
            this.closeAddDialog();
          }
        })
        .finally(() => {
          this.adding = false;
        });
    },
    deleteItem(item) {
      if (!confirm(this.$t('expected.deleteConfirm', { title: item.title }))) return;
      this.$backend('/user/expected', {
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
