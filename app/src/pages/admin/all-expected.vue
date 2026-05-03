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
        <v-btn small color="primary" class="white--text mr-1" @click="openUploadDialog(item)">
          <v-icon small left>mdi-upload</v-icon>
          {{ $t('expected.upload') }}
        </v-btn>
        <v-btn small color="error" class="white--text" @click="deleteItem(item)">
          <v-icon small left>mdi-delete</v-icon>
          {{ $t('expected.delete') }}
        </v-btn>
      </template>
    </v-data-table>

    <!-- Upload Dialog -->
    <v-dialog v-model="showUploadDialog" persistent transition="dialog-bottom-transition" width="400">
      <v-card>
        <v-toolbar flat dense dark color="#003153">
          {{ $t('expected.uploadDialogTitle') }}
          <v-spacer></v-spacer>
          <v-btn text @click="closeUploadDialog">{{ $t('expected.cancel') }}</v-btn>
        </v-toolbar>
        <v-card-text class="pt-4">
          <v-file-input v-model="uploadFile" :label="$t('expected.selectFile')" prepend-icon="mdi-book-open-variant"></v-file-input>
        </v-card-text>
        <v-card-actions>
          <v-spacer></v-spacer>
          <v-btn :loading="uploading" color="primary" @click="submitUpload">{{ $t('expected.upload') }}</v-btn>
          <v-spacer></v-spacer>
        </v-card-actions>
      </v-card>
    </v-dialog>

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
      showUploadDialog: false,
      uploading: false,
      uploadItem: null,
      uploadFile: null,
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
    openUploadDialog(item) {
      this.uploadItem = item;
      this.uploadFile = null;
      this.showUploadDialog = true;
    },
    closeUploadDialog() {
      this.showUploadDialog = false;
      this.uploadItem = null;
      this.uploadFile = null;
    },
    parseSizeString(sizeStr) {
      if (!sizeStr || sizeStr === '0' || sizeStr === '0MB' || sizeStr === '0KB') return 0;
      const size = sizeStr.toLowerCase().trim();
      if (size.endsWith('mb')) return parseInt(size.slice(0, -2)) * 1024 * 1024;
      if (size.endsWith('kb')) return parseInt(size.slice(0, -2)) * 1024;
      return parseInt(size);
    },
    async submitUpload() {
      if (!this.uploadFile) {
        this.$alert('error', this.$t('upload.selectFile'));
        return;
      }
      this.uploading = true;
      try {
        const chunkThreshold = this.parseSizeString(
          (process.client && localStorage.getItem('chunk_upload_size')) || '0'
        );
        let rsp;
        if (chunkThreshold > 0 && this.uploadFile.size > chunkThreshold) {
          const file = this.uploadFile;
          const totalChunks = Math.ceil(file.size / chunkThreshold);
          let hashVal = 0;
          const str = file.name + file.size;
          for (let i = 0; i < str.length; i++) {
            hashVal = ((hashVal << 5) - hashVal + str.charCodeAt(i)) | 0;
          }
          const fileHash = Math.abs(hashVal).toString(16);
          for (let i = 0; i < totalChunks; i++) {
            const start = i * chunkThreshold;
            const formData = new FormData();
            formData.append('chunk', file.slice(start, Math.min(start + chunkThreshold, file.size)));
            formData.append('filename', file.name);
            formData.append('chunk_index', String(i));
            formData.append('total_chunks', String(totalChunks));
            formData.append('file_hash', fileHash);
            rsp = await this.$backend('/book/upload/chunk', { method: 'POST', body: formData });
            if (rsp.err !== 'ok') throw new Error(rsp.msg);
          }
        } else {
          const data = new FormData();
          data.append('ebook', this.uploadFile);
          rsp = await this.$backend('/book/upload', { method: 'POST', body: data });
        }
        if (rsp && rsp.err === 'ok') {
          const item = this.uploadItem;
          this.closeUploadDialog();
          await this.$backend('/user/expected', {
            method: 'DELETE',
            body: JSON.stringify({ id: item.id }),
          });
          this.items = this.items.filter(i => i.id !== item.id);
          this.$alert('success', this.$t('expected.uploadSuccess'));
        } else {
          this.$alert('error', (rsp && rsp.msg) || this.$t('upload.uploadFailed'));
        }
      } catch (e) {
        this.$alert('error', e.message || this.$t('upload.uploadFailed'));
      } finally {
        this.uploading = false;
      }
    },
  },
};
</script>

<style scoped>
</style>
