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
    <AppDialog
      v-model="showUploadDialog"
      type="action"
      :title="$t('expected.uploadDialogTitle')"
      color="blue darken-4"
      confirm-dark
      width="400"
      transition="dialog-bottom-transition"
      :dismiss-label="$t('expected.cancel')"
      :confirm-text="$t('expected.upload')"
      :confirm-loading="uploading"
      @dismiss="closeUploadDialog"
      @confirm="submitUpload"
    >
      <v-radio-group v-model="uploadBookType" row class="mt-0">
        <v-radio :label="$t('expected.ebook')" value="ebook"></v-radio>
        <v-radio v-if="physicalModuleOn" :label="$t('expected.physicalBook')" value="physical"></v-radio>
      </v-radio-group>
      <v-file-input v-if="uploadBookType === 'ebook'" v-model="uploadFile" :label="$t('expected.selectFile')" prepend-icon="mdi-book-open-variant"></v-file-input>
      <v-text-field v-else ref="isbnField" v-model="uploadIsbn" :label="$t('expected.isbnNumber')" :rules="debouncedIsbnRules" prepend-icon="mdi-barcode" clearable @input="clearValidationCache"></v-text-field>
    </AppDialog>

    <!-- Delete Confirm Dialog -->
    <AppDialog
      v-model="showDeleteDialog"
      type="confirm"
      :title="$t('expected.delete')"
      icon="mdi-delete-outline"
      color="deep-orange"
      confirm-dark
      max-width="480px"
      :confirm-text="$t('expected.delete')"
      @confirm="confirmDelete"
    >
      {{ deleteTarget ? $t('expected.deleteConfirm', { title: deleteTarget.title }) : '' }}
    </AppDialog>
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
      newItem: {
        title: '',
        author: '',
        publisher: '',
      },
      showUploadDialog: false,
      uploading: false,
      showDeleteDialog: false,
      deleteTarget: null,
      uploadItem: null,
      uploadFile: null,
      uploadBookType: 'ebook',
      uploadIsbn: '',
      shouldValidate: false,
      // 由 buildDebouncedIsbnRules() 构建，见该方法注释
      debouncedIsbnRules: [],
      showValidationErrors: false,
    };
  },
  head() {
    return { title: this.$t('expected.pageTitle') };
  },
  computed: {
    // 实体书模块关闭时缺书登记的「实体书」上传方式一并隐藏
    physicalModuleOn() {
      const mods = (this.$store.state.sys && this.$store.state.sys.modules) || {};
      return mods.physical !== false;
    },
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
    isValidIsbn() {
      // Vue 的 computed 本身已按 this.uploadIsbn 做依赖缓存，不需要手动缓存
      if (!this.uploadIsbn) {
        return false;
      }
      const cleanIsbn = this.uploadIsbn.replace(/[-\s]/g, '');
      return /^[0-9]{9}[0-9X]$/.test(cleanIsbn) || /^[0-9]{13}$/.test(cleanIsbn);
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
    this.buildDebouncedIsbnRules();
  },
  methods: {
    // 构建防抖验证规则（原来放在 computed 里"只构建一次"，构建过程里要给
    // shouldValidate 赋值，会触发 vue/no-side-effects-in-computed-properties；
    // 挪到普通方法里，需要重置时显式调用即可）。
    buildDebouncedIsbnRules() {
        const debounce = (func, wait) => {
            let timeout;
            return function executedFunction(...args) {
                const later = () => {
                    clearTimeout(timeout);
                    func.apply(this, args);
                };
                clearTimeout(timeout);
                timeout = setTimeout(later, wait);
            };
        };

        const validateWithDebounce = debounce(() => {
            this.shouldValidate = true;
            this.$nextTick(() => {
                this.$refs.isbnField && this.$refs.isbnField.validate();
            });
        }, 300);

        this.debouncedIsbnRules = [
            v => {
                // 如果没有输入内容且没有手动触发验证，不显示错误
                if (!v && !this.showValidationErrors) {
                    return true;
                }
                if (!this.shouldValidate && v) {
                    validateWithDebounce();
                    return true; // 暂时通过验证，等待防抖完成
                }
                return !!v || this.$t('upload.isbnRequired');
            },
            v => {
                // 如果没有输入内容且没有手动触发验证，不显示错误
                if (!v && !this.showValidationErrors) {
                    return true;
                }
                if (!this.shouldValidate && v) {
                    return true; // 暂时通过验证，等待防抖完成
                }
                return (v && v.length >= 10) || this.$t('upload.isbnMinLength');
            },
            v => {
                // 如果没有输入内容且没有手动触发验证，不显示错误
                if (!v && !this.showValidationErrors) {
                    return true;
                }
                if (!this.shouldValidate && v) {
                    return true; // 暂时通过验证，等待防抖完成
                }
                return (v && /^[0-9\-X]+$/.test(v)) || this.$t('upload.isbnInvalidFormat');
            },
            v => {
                // 如果没有输入内容且没有手动触发验证，不显示错误
                if (!v && !this.showValidationErrors) {
                    return true;
                }
                if (!this.shouldValidate && v) {
                    return true; // 暂时通过验证，等待防抖完成
                }
                return this.isValidIsbn || this.$t('upload.invalidIsbn');
            },
        ];
    },
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
    deleteItem(item) {
      this.deleteTarget = item;
      this.showDeleteDialog = true;
    },
    confirmDelete() {
      const item = this.deleteTarget;
      if (!item) return;
      this.$backend('/user/expected', {
        method: 'DELETE',
        body: JSON.stringify({ id: item.id }),
      }).then(rsp => {
        if (rsp.err !== 'ok') {
          this.$alert('error', rsp.msg);
        } else {
          this.items = this.items.filter(i => i.id !== item.id);
        }
      }).finally(() => {
        this.showDeleteDialog = false;
        this.deleteTarget = null;
      });
    },
    openUploadDialog(item) {
      this.uploadItem = item;
      this.uploadFile = null;
      this.uploadIsbn = '';
      this.uploadBookType = 'ebook';
      this.showValidationErrors = false;
      this.buildDebouncedIsbnRules();
      this.shouldValidate = false;
      this.showUploadDialog = true;
    },
    closeUploadDialog() {
      this.showUploadDialog = false;
      this.uploadItem = null;
      this.uploadFile = null;
      this.uploadIsbn = '';
      this.uploadBookType = 'ebook';
      this.showValidationErrors = false;
      this.buildDebouncedIsbnRules();
      this.shouldValidate = false;
    },
    clearValidationCache() {
      this.shouldValidate = false;
      if (this.uploadIsbn && this.showValidationErrors) {
        this.showValidationErrors = false;
        this.buildDebouncedIsbnRules();
      }
    },
    parseSizeString(sizeStr) {
      if (!sizeStr || sizeStr === '0' || sizeStr === '0MB' || sizeStr === '0KB') return 0;
      const size = sizeStr.toLowerCase().trim();
      if (size.endsWith('mb')) return parseInt(size.slice(0, -2)) * 1024 * 1024;
      if (size.endsWith('kb')) return parseInt(size.slice(0, -2)) * 1024;
      return parseInt(size);
    },
    async submitUpload() {
      this.uploading = true;
      try {
        if (this.uploadBookType === 'physical') {
          const isbn = (this.uploadIsbn || '').trim();
          if (!isbn) {
            this.$alert('error', this.$t('expected.isbnRequired'));
            return;
          }
          const rsp = await this.$backend('/book/add', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ isbn }),
          });
          if (rsp && rsp.err === 'ok') {
            const item = this.uploadItem;
            this.closeUploadDialog();
            await this.$backend('/user/expected', {
              method: 'DELETE',
              body: JSON.stringify({ id: item.id }),
            });
            this.items = this.items.filter(i => i.id !== item.id);
            this.$alert('success', this.$t('expected.physicalBookSuccess'));
          } else {
            this.$alert('error', (rsp && rsp.msg) || this.$t('upload.uploadFailed'));
          }
          return;
        }

        if (!this.uploadFile) {
          this.$alert('error', this.$t('upload.selectFile'));
          return;
        }
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
