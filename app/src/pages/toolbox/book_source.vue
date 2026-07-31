<template>
  <v-container fluid class="pa-4">
    <v-row class="mb-3" align="center">
      <v-col class="text-center">
        <span class="text-h5 font-weight-bold">{{ $t('bookSource.title') }}</span>
      </v-col>
      <v-col cols="auto">
        <v-btn small color="error" @click="$router.go(-1)">
          <v-icon small left>mdi-close</v-icon>{{ $t('bookSource.close') }}
        </v-btn>
      </v-col>
    </v-row>

    <!-- 顶部标签栏 -->
    <v-row class="mb-3">
      <v-col cols="12">
        <div class="d-inline-flex" style="border:1px solid rgba(0,0,0,0.12);border-radius:8px;overflow:hidden">
          <v-btn small text :class="currentTab === 'search' ? 'primary primary--text' : ''"
            @click="currentTab = 'search'" class="ma-0">
            <v-icon left small>mdi-magnify</v-icon>{{ $t('bookSource.tabSearch') }}
          </v-btn>
          <v-btn small text :class="currentTab === 'sources' ? 'primary primary--text' : ''"
            @click="currentTab = 'sources'" class="ma-0">
            <v-icon left small>mdi-book-open-variant</v-icon>{{ $t('bookSource.tabSources') }}
          </v-btn>
        </div>
      </v-col>
    </v-row>

    <!-- ═══ 标签页：搜索下载 ═══ -->
    <template v-if="currentTab === 'search'">
      <v-card outlined rounded="xl" class="bs-card pa-0 mb-3">
        <v-card-title class="py-2 text-subtitle-1">
          {{ $t('bookSource.searchTitle') }}
        </v-card-title>
        <v-divider></v-divider>
        <v-card-text class="pt-3">
          <v-row align="center" dense>
            <v-col cols="12" sm="9" class="pb-2 pb-sm-0">
              <v-text-field v-model="keyword" :label="$t('bookSource.keywordLabel')"
                dense outlined hide-details prepend-inner-icon="mdi-magnify"
                @keydown.enter="doSearch" clearable></v-text-field>
            </v-col>
            <v-col cols="12" sm="3">
              <v-btn color="primary" @click="doSearch" :loading="searching" block
                :disabled="!keyword">
                <v-icon left small>mdi-magnify</v-icon> {{ $t('bookSource.searchBtn') }}
              </v-btn>
            </v-col>
          </v-row>
          <div class="text-caption grey--text mt-1">
            {{ $t('bookSource.searchHint', { n: enabledSourceCount }) }}
          </div>
        </v-card-text>
      </v-card>

      <transition name="bs-fade">
        <v-card v-if="searchResults.length > 0" outlined rounded="xl" class="bs-card pa-0 mb-3">
          <v-card-title class="py-2 text-subtitle-1 d-flex align-center">
            <span>{{ $t('bookSource.resultTitle') }} ({{ searchResults.length }})</span>
            <v-spacer></v-spacer>
            <v-btn small color="success" @click="showConfirmAll = true" :loading="downloadingAll">
              <v-icon left small>mdi-download-multiple</v-icon> {{ $t('bookSource.downloadAll') }}
            </v-btn>
          </v-card-title>
          <v-divider></v-divider>
          <v-simple-table dense>
            <thead>
              <tr>
                <th class="text-center">{{ $t('bookSource.colCover') }}</th>
                <th>{{ $t('bookSource.colName') }}</th>
                <th>{{ $t('bookSource.colAuthor') }}</th>
                <th>{{ $t('bookSource.colSource') }}</th>
                <th>{{ $t('bookSource.colLastChapter') }}</th>
                <th class="text-center">{{ $t('bookSource.colAction') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(book, i) in pagedResults" :key="book.bookUrl + '|' + book.sourceName">
                <td class="text-center">
                  <v-avatar size="32" tile>
                    <v-img v-if="book.coverUrl" :src="book.coverUrl" contain></v-img>
                    <v-icon v-else>mdi-book-outline</v-icon>
                  </v-avatar>
                </td>
                <td class="font-weight-medium">{{ book.name }}</td>
                <td>{{ book.author }}</td>
                <td><v-chip x-small color="primary" outlined>{{ book.sourceName }}</v-chip></td>
                <td class="text-truncate" style="max-width:180px">{{ book.lastChapter }}</td>
                <td class="text-center">
                  <v-btn x-small color="primary" @click="downloadBook(book)"
                    :loading="downloadingMap[book.bookUrl + '|' + book.sourceName]">
                    <v-icon x-small left>mdi-download</v-icon> {{ $t('bookSource.download') }}
                  </v-btn>
                  <v-btn x-small color="success" outlined class="ml-1" @click="generateEpub(book)"
                    :loading="generatingMap[book.bookUrl + '|' + book.sourceName]">
                    <v-icon x-small left>mdi-file-export</v-icon> {{ $t('bookSource.generate') }}
                  </v-btn>
                </td>
              </tr>
            </tbody>
          </v-simple-table>
          <div class="d-flex justify-center pt-2" v-if="pageCount > 1">
            <v-pagination v-model="pageNum" :length="pageCount" total-visible="5" dense></v-pagination>
          </div>
        </v-card>
      </transition>

      <transition name="bs-fade">
        <v-card v-if="tasks.length > 0" outlined rounded="xl" class="bs-card pa-0">
          <v-card-title class="py-2 text-subtitle-1">
            {{ $t('bookSource.taskTitle') }}
          </v-card-title>
          <v-divider></v-divider>
          <v-list dense>
            <v-list-item v-for="(task, i) in tasks" :key="i">
              <v-list-item-content>
                <v-list-item-title>
                  {{ task.name }}
                  <v-chip v-if="task.source" x-small color="primary" outlined class="ml-1">{{ task.source }}</v-chip>
                  <v-chip v-if="task.kind === 'epub'" x-small color="success" outlined class="ml-1">
                    {{ $t('bookSource.generate') }}
                  </v-chip>
                </v-list-item-title>
                <v-progress-linear :value="task.progress" height="6" rounded class="mt-1"></v-progress-linear>
              </v-list-item-content>
              <v-list-item-action class="align-center">
                <v-btn v-if="task === activeTask" x-small color="warning" text @click="cancelTask(task)"
                  :title="$t('bookSource.cancelTask')">
                  <v-icon x-small>mdi-close-circle</v-icon>
                </v-btn>
                <a v-if="task.epubUrl" :href="task.epubUrl" target="_blank"
                  class="v-btn v-btn--x-small v-btn--text success--text mx-1">
                  <v-icon x-small left>mdi-download</v-icon>{{ $t('bookSource.downloadFile') }}
                </a>
                <v-chip :color="task.status === 'done' ? 'success' : task.status === 'error' ? 'error' : 'primary'"
                  x-small>
                  {{ task.msg || task.status }}
                </v-chip>
              </v-list-item-action>
            </v-list-item>
          </v-list>
        </v-card>
      </transition>
    </template>

    <!-- ═══ 标签页：书源管理 ═══ -->
    <template v-if="currentTab === 'sources'">
      <v-row>
        <v-col cols="12" md="5">
          <v-card outlined rounded="xl" class="bs-card pa-0">
            <v-card-title class="py-2 text-subtitle-1 d-flex align-center">
              <span>{{ $t('bookSource.sourceList') }}</span>
              <v-spacer></v-spacer>
              <v-chip small>{{ sources.length }} {{ $t('bookSource.countUnit') }}</v-chip>
            </v-card-title>
            <v-divider></v-divider>
            <div class="pa-3">
              <v-text-field v-model="searchQuery" :label="$t('bookSource.filterPlaceholder')"
                dense outlined hide-details prepend-inner-icon="mdi-magnify" clearable
                class="mb-3"></v-text-field>

              <v-row dense class="mb-3">
                <v-col cols="auto">
                  <v-btn small @click="loadSources" :loading="sLoading">
                    <v-icon left small>mdi-refresh</v-icon> {{ $t('bookSource.refresh') }}
                  </v-btn>
                </v-col>
                <v-col cols="auto">
                  <v-btn small color="primary" @click="openAdd">
                    <v-icon left small>mdi-plus</v-icon> {{ $t('bookSource.add') }}
                  </v-btn>
                </v-col>
                <v-col cols="auto">
                  <v-btn small @click="$refs.zipInput.click()">
                    <v-icon left small>mdi-zip-box</v-icon> {{ $t('bookSource.importZip') }}
                  </v-btn>
                  <input type="file" ref="zipInput" accept=".zip" style="display:none" @change="importZip">
                </v-col>
                <v-col cols="auto">
                  <v-btn small @click="showImportUrl = !showImportUrl">
                    <v-icon left small>mdi-web</v-icon> {{ $t('bookSource.importUrl') }}
                  </v-btn>
                </v-col>
              </v-row>

              <v-expand-transition>
                <v-row v-if="showImportUrl" dense class="mb-3">
                  <v-col cols="9">
                    <v-text-field v-model="importUrl" dense outlined hide-details
                      :placeholder="$t('bookSource.importUrlPlaceholder')" clearable
                      @keydown.enter="doImportUrl"></v-text-field>
                  </v-col>
                  <v-col cols="3">
                    <v-btn small color="primary" block @click="doImportUrl" :loading="importingUrl">
                      {{ $t('bookSource.importBtn') }}
                    </v-btn>
                  </v-col>
                </v-row>
              </v-expand-transition>

              <v-list dense class="bs-source-list pa-0" v-if="filteredSources.length > 0">
                <v-list-item v-for="item in filteredSources" :key="item.bookSourceName"
                  class="bs-source-item" @click="openEdit(item)" dense>
                  <v-list-item-action class="mr-2 my-0">
                    <v-btn :color="item.enabled ? 'success' : 'error'"
                      x-small fab dark @click.stop="toggleSource(item)">
                      <v-icon x-small>{{ item.enabled ? 'mdi-check' : 'mdi-close' }}</v-icon>
                    </v-btn>
                  </v-list-item-action>
                  <v-list-item-content>
                    <v-list-item-title class="bs-source-name">{{ item.bookSourceName }}</v-list-item-title>
                    <v-list-item-subtitle class="bs-source-meta">
                      {{ item.bookSourceGroup || $t('bookSource.noGroup') }}
                    </v-list-item-subtitle>
                  </v-list-item-content>
                  <v-list-item-action class="my-0">
                    <v-btn icon x-small @click.stop="testSource(item)" :loading="testing === item.bookSourceName"
                      :title="$t('bookSource.testResultTitle')">
                      <v-icon x-small>mdi-connection</v-icon>
                    </v-btn>
                    <v-btn icon x-small @click.stop="openSettings(item)" :title="$t('bookSource.settings')">
                      <v-icon x-small>mdi-cog</v-icon>
                    </v-btn>
                  </v-list-item-action>
                </v-list-item>
              </v-list>
              <div v-else class="text-center py-4 grey--text">
                {{ sLoading ? $t('bookSource.loading') : $t('bookSource.noSources') }}
              </div>
            </div>
          </v-card>
        </v-col>

        <v-col cols="12" md="7">
          <v-card outlined rounded="xl" class="bs-card pa-0">
            <v-card-title class="py-2 text-subtitle-1">
              {{ $t('bookSource.sourceDetail') }}
            </v-card-title>
            <v-divider></v-divider>
            <v-card-text class="text-center grey--text py-8">
              {{ $t('bookSource.sourceDetailHint') }}
            </v-card-text>
          </v-card>
        </v-col>
      </v-row>
    </template>

    <!-- 添加/编辑对话框（JSON 粘贴） -->
    <v-dialog v-model="showEditDialog" max-width="800" scrollable>
      <v-card>
        <v-card-title class="text-subtitle-1">
          {{ editingSource ? $t('bookSource.editTitle') : $t('bookSource.addTitle') }}
        </v-card-title>
        <v-divider></v-divider>
        <v-card-text class="pt-3">
          <div class="text-subtitle-2 mb-2 grey--text">
            <v-icon left small>mdi-information</v-icon>
            {{ $t('bookSource.pasteJsonHint') }}
          </div>
          <v-textarea v-model="editJson" class="bs-mono" :rows="20"
            flat solo hide-details spellcheck="false"
            :placeholder="$t('bookSource.jsonPlaceholder')"></v-textarea>
          <v-alert v-if="jsonError" type="error" dense text class="mt-2 mb-0">{{ jsonError }}</v-alert>
        </v-card-text>
        <v-divider></v-divider>
        <v-card-actions>
          <v-spacer></v-spacer>
          <v-btn text @click="showEditDialog = false">{{ $t('bookSource.cancel') }}</v-btn>
          <v-btn color="primary" @click="saveSource" :loading="saving">
            <v-icon left small>mdi-check</v-icon> {{ $t('bookSource.save') }}
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- JSON 设置对话框 -->
    <v-dialog v-model="showSettingsDialog" max-width="700" scrollable>
      <v-card>
        <v-card-title class="text-subtitle-1">
          <v-icon left small>mdi-cog</v-icon>
          {{ $t('bookSource.settings') }}: {{ settingsTarget?.bookSourceName }}
          <v-spacer></v-spacer>
          <v-btn x-small color="error" text @click="confirmDelete(settingsTarget)" class="mr-2">
            <v-icon x-small left>mdi-delete</v-icon> {{ $t('bookSource.delete') }}
          </v-btn>
        </v-card-title>
        <v-divider></v-divider>
        <v-card-text class="pt-3">
          <div class="text-subtitle-2 mb-2">{{ $t('bookSource.jsonEditor') }}</div>
          <v-textarea v-model="settingsJson" class="bs-mono" :rows="18" flat solo hide-details spellcheck="false"></v-textarea>
          <v-alert v-if="jsonError" type="error" dense text class="mt-2 mb-0">{{ jsonError }}</v-alert>
        </v-card-text>
        <v-divider></v-divider>
        <v-card-actions>
          <v-spacer></v-spacer>
          <v-btn text @click="showSettingsDialog = false">{{ $t('bookSource.close') }}</v-btn>
          <v-btn color="primary" @click="applyJson">
            <v-icon left small>mdi-check</v-icon> {{ $t('bookSource.applyJson') }}
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- 删除确认 -->
    <v-dialog v-model="showDeleteDialog" max-width="400">
      <v-card>
        <v-card-title class="text-subtitle-1">{{ $t('bookSource.deleteTitle') }}</v-card-title>
        <v-card-text>
          {{ $t('bookSource.deleteConfirm') }}「{{ deleteTarget?.bookSourceName }}」？
        </v-card-text>
        <v-card-actions>
          <v-spacer></v-spacer>
          <v-btn text @click="showDeleteDialog = false">{{ $t('bookSource.cancel') }}</v-btn>
          <v-btn color="error" @click="doDelete">{{ $t('bookSource.delete') }}</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- 批量下载确认 -->
    <v-dialog v-model="showConfirmAll" max-width="420">
      <v-card>
        <v-card-title class="text-subtitle-1">{{ $t('bookSource.confirmDownloadAllTitle') }}</v-card-title>
        <v-card-text>
          {{ $t('bookSource.confirmDownloadAllMsg', { n: searchResults.length }) }}
        </v-card-text>
        <v-card-actions>
          <v-spacer></v-spacer>
          <v-btn text @click="showConfirmAll = false">{{ $t('bookSource.cancel') }}</v-btn>
          <v-btn color="primary" @click="downloadAll">{{ $t('bookSource.downloadAll') }}</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- 测试结果 -->
    <v-dialog v-model="showTestDialog" max-width="600">
      <v-card>
        <v-card-title class="text-subtitle-1">
          {{ $t('bookSource.testResultTitle') }}: {{ testResult?.source }}
        </v-card-title>
        <v-card-text>
          <v-alert :type="testResult?.reachable ? 'success' : 'error'" dense class="mb-3">
            {{ testResult?.reachable ? $t('bookSource.testReachable', { n: testResult.sample_count }) : $t('bookSource.testUnreachable') }}
          </v-alert>
          <v-simple-table v-if="testResult?.samples?.length" dense>
            <thead>
              <tr><th>{{ $t('bookSource.colName') }}</th><th>{{ $t('bookSource.colAuthor') }}</th></tr>
            </thead>
            <tbody>
              <tr v-for="(s, i) in testResult.samples" :key="i">
                <td>{{ s.name }}</td><td>{{ s.author }}</td>
              </tr>
            </tbody>
          </v-simple-table>
        </v-card-text>
        <v-card-actions>
          <v-spacer></v-spacer>
          <v-btn text @click="showTestDialog = false">{{ $t('bookSource.close') }}</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-snackbar v-model="showSnackbar" :timeout="3000" :color="snackbarColor">
      {{ snackbarMsg }}
    </v-snackbar>
  </v-container>
</template>

<script>
export default {
  name: 'BookSourceTool',
  data() {
    return {
      currentTab: 'search',

      keyword: '',
      searching: false,
      searchResults: [],

      tasks: [],
      downloadingAll: false,
      downloadingMap: {},
      generatingMap: {},
      pollTimer: null,
      searchTimer: null,
      activeTask: null,
      showConfirmAll: false,
      pageNum: 1,
      pageSize: 50,

      sources: [],
      sLoading: false,
      searchQuery: '',

      showEditDialog: false,
      editingSource: null,
      editJson: '',
      saving: false,

      showImportUrl: false,
      importUrl: '',
      importingUrl: false,

      showSettingsDialog: false,
      settingsTarget: null,
      settingsJson: '',
      jsonError: '',

      showDeleteDialog: false,
      deleteTarget: null,

      testing: '',
      showTestDialog: false,
      testResult: null,

      showSnackbar: false,
      snackbarMsg: '',
      snackbarColor: 'info',
    };
  },
  computed: {
    enabledSourceCount() {
      return this.sources.filter(s => s.enabled).length;
    },
    filteredSources() {
      if (!this.searchQuery) return this.sources;
      const q = this.searchQuery.toLowerCase();
      return this.sources.filter(s =>
        s.bookSourceName.toLowerCase().includes(q) ||
        (s.bookSourceUrl || '').toLowerCase().includes(q) ||
        (s.bookSourceGroup || '').toLowerCase().includes(q)
      );
    },
    pagedResults() {
      const start = (this.pageNum - 1) * this.pageSize;
      return this.searchResults.slice(start, start + this.pageSize);
    },
    pageCount() {
      return Math.max(1, Math.ceil(this.searchResults.length / this.pageSize));
    },
  },
  watch: {
    searchResults() {
      this.pageNum = 1;
    },
  },
  created() {
    this.$store.commit('navbar', true);
    this.loadSources();
  },
  beforeDestroy() {
    if (this.pollTimer) clearInterval(this.pollTimer);
    if (this.searchTimer) clearInterval(this.searchTimer);
  },
  methods: {
    async loadSources() {
      this.sLoading = true;
      try {
        const rsp = await this.$backend('/toolbox/book_source/list');
        this.sources = (rsp.data || []).map(s => ({ ...s }));
      } catch {
        this.sources = [];
      }
      this.sLoading = false;
    },

    openAdd() {
      this.editingSource = null;
      this.editJson = '';
      this.jsonError = '';
      this.showEditDialog = true;
    },

    openEdit(item) {
      this.editingSource = item;
      this.editJson = JSON.stringify(this.sourceToJsonObj(item), null, 2);
      this.jsonError = '';
      this.showEditDialog = true;
    },

    async saveSource() {
      this.saving = true;
      this.jsonError = '';
      const raw = this.editJson.trim();
      if (!raw) {
        this.jsonError = this.$t('bookSource.jsonFormatError') + ': empty';
        this.saving = false;
        return;
      }
      let obj;
      try { obj = JSON.parse(raw); }
      catch (e) {
        this.jsonError = this.$t('bookSource.jsonFormatError') + ': ' + e.message;
        this.saving = false;
        return;
      }
      if (!obj.bookSourceName || !obj.bookSourceUrl) {
        this.jsonError = this.$t('bookSource.jsonFormatError') + ': ' + this.$t('bookSource.fieldName') + ' / bookSourceUrl';
        this.saving = false;
        return;
      }
      obj.enabled = this.editingSource ? this.editingSource.enabled : true;
      obj.bookSourceUrl = obj.bookSourceUrl.replace(/\/+$/, '');
      try {
        const rsp = await this.$backend('/toolbox/book_source/save', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ raw: obj }),
        });
        if (rsp.err === 'ok') {
          this.showMsg(this.$t('bookSource.saveSuccess'), 'success');
          this.showEditDialog = false;
          this.loadSources();
        } else {
          this.showMsg(rsp.msg || this.$t('bookSource.saveFailed'), 'error');
        }
      } catch (e) {
        this.showMsg(this.$t('bookSource.saveFailed') + ': ' + String(e), 'error');
      }
      this.saving = false;
    },

    async toggleSource(item) {
      const was = item.enabled;
      item.enabled = !item.enabled;
      try {
        const rsp = await this.$backend('/toolbox/book_source/toggle', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: item.bookSourceName }),
        });
        if (rsp.err !== 'ok') {
          item.enabled = was;
          this.showMsg(rsp.msg || 'toggle failed', 'error');
        }
      } catch {
        item.enabled = was;
      }
    },

    openSettings(item) {
      this.settingsTarget = item;
      this.settingsJson = JSON.stringify(this.sourceToJsonObj(item), null, 2);
      this.jsonError = '';
      this.showSettingsDialog = true;
    },

    sourceToJsonObj(item) {
      const obj = {
        bookSourceName: item.bookSourceName,
        bookSourceUrl: item.bookSourceUrl,
        bookSourceGroup: item.bookSourceGroup,
        bookSourceType: item.bookSourceType ?? 0,
        searchUrl: item.searchUrl || '',
        header: item.header || {},
        jsLib: item.jsLib || '',
        ruleSearch: item.ruleSearch || {},
        ruleBookInfo: item.ruleBookInfo || {},
        ruleToc: item.ruleToc || {},
        ruleContent: item.ruleContent || {},
      };
      if (!obj.ruleContent.replaceRegex) obj.ruleContent.replaceRegex = [];
      return obj;
    },

    applyJson() {
      this.jsonError = '';
      try {
        const obj = JSON.parse(this.settingsJson);
        if (!obj.bookSourceName) {
          this.jsonError = this.$t('bookSource.jsonFormatError') + ': ' + this.$t('bookSource.fieldName');
          return;
        }
        Object.assign(this.settingsTarget, obj);
        this.showMsg(this.$t('bookSource.jsonApplied'), 'success');
        this.showSettingsDialog = false;
        this.saveSettingsSource(this.settingsTarget);
      } catch (e) {
        this.jsonError = this.$t('bookSource.jsonFormatError') + ': ' + e.message;
      }
    },

    async saveSettingsSource(item) {
      try {
        const form = { ...item };
        if (typeof form.header === 'object') form.header = JSON.stringify(form.header);
        if (form.ruleContent?.replaceRegex) {
          form.replaceRegexStr = form.ruleContent.replaceRegex
            .map(r => `${r.pattern}##${r.replacement}`).join('\n');
        }
        await this.$backend('/toolbox/book_source/save', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ raw: form }),
        });
        this.loadSources();
      } catch { /* snackbar already shown */ }
    },

    confirmDelete(item) {
      this.deleteTarget = item;
      this.showDeleteDialog = true;
    },

    async doDelete() {
      try {
        const rsp = await this.$backend('/toolbox/book_source/delete', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: this.deleteTarget.bookSourceName }),
        });
        if (rsp.err === 'ok') {
          this.showDeleteDialog = false;
          this.showSettingsDialog = false;
          this.showMsg(this.$t('bookSource.deleteSuccess'), 'success');
          this.loadSources();
        } else {
          this.showMsg(rsp.msg || this.$t('bookSource.deleteFailed'), 'error');
        }
      } catch (e) {
        this.showMsg(this.$t('bookSource.deleteFailed') + ': ' + String(e), 'error');
      }
    },

    async testSource(item) {
      this.testing = item.bookSourceName;
      try {
        const rsp = await this.$backend('/toolbox/book_source/test?source=' + encodeURIComponent(item.bookSourceName));
        if (rsp.err === 'ok') {
          this.testResult = rsp.data;
          this.showTestDialog = true;
        } else {
          this.showMsg(rsp.msg || this.$t('bookSource.testFailed'), 'error');
        }
      } catch (e) {
        this.showMsg(this.$t('bookSource.testFailed') + ': ' + String(e), 'error');
      }
      this.testing = '';
    },

    async doSearch() {
      if (!this.keyword) return;
      this.searching = true;
      this.searchResults = [];
      const enabled = this.sources.filter(s => s.enabled);
      if (enabled.length === 0) {
        this.showMsg(this.$t('bookSource.noEnabledSources'), 'error');
        this.searching = false;
        return;
      }
      try {
        const rsp = await this.$backend('/toolbox/book_source/search_async', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ keyword: this.keyword }),
        });
        if (rsp.err === 'ok' && rsp.data && rsp.data.task_id) {
          this.pollSearch(rsp.data.task_id);
        } else {
          this.showMsg(rsp.msg || this.$t('bookSource.searchFailed'), 'error');
          this.searching = false;
        }
      } catch (e) {
        this.showMsg(this.$t('bookSource.searchFailed') + ': ' + String(e), 'error');
        this.searching = false;
      }
    },

    async pollSearch(taskId) {
      if (this.searchTimer) clearInterval(this.searchTimer);
      this.searchTimer = setInterval(async () => {
        try {
          const rsp = await this.$backend(
            '/toolbox/book_source/search_status?task_id=' + encodeURIComponent(taskId)
          );
          if (rsp.err !== 'ok' || !rsp.data) {
            this.stopSearchPoll();
            return;
          }
          const d = rsp.data;
          const seen = new Set(this.searchResults.map(b => b.bookUrl + '|' + b.sourceName));
          (d.results || []).forEach(r => {
            (r.books || []).forEach(b => {
              const key = b.bookUrl + '|' + r.source_name;
              if (!seen.has(key)) {
                seen.add(key);
                this.searchResults.push({ ...b, sourceName: r.source_name });
              }
            });
          });
          if (d.finished) this.stopSearchPoll();
        } catch { /* 轮询错误继续 */ }
      }, 1500);
    },

    stopSearchPoll() {
      if (this.searchTimer) {
        clearInterval(this.searchTimer);
        this.searchTimer = null;
      }
      this.searching = false;
    },

    async downloadBook(book) {
      if (this.activeTask) {
        this.showMsg(this.$t('bookSource.downloadBusy'), 'error');
        return false;
      }
      const taskKey = book.bookUrl + '|' + book.sourceName;
      if (this.downloadingMap[taskKey]) return false;
      const task = { name: book.name, source: book.sourceName, progress: 0, status: 'started', msg: this.$t('bookSource.taskStarting') };
      this.tasks.push(task);
      this.$set(this.downloadingMap, taskKey, true);
      try {
        const rsp = await this.$backend('/toolbox/book_source/download', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            source: book.sourceName,
            bookUrl: book.bookUrl,
            bookTitle: book.name,
            maxChapters: 9999,
          }),
        });
        if (rsp.err === 'ok') {
          this.activeTask = task;
          this.startPoll(task);
          return true;
        }
        task.status = 'error';
        task.msg = rsp.msg || this.$t('bookSource.downloadFailed');
        return false;
      } catch (e) {
        task.status = 'error';
        task.msg = String(e);
        return false;
      } finally {
        this.$delete(this.downloadingMap, taskKey);
      }
    },

    async downloadAndWait(book) {
      const ok = await this.downloadBook(book);
      if (!ok) return;
      await this.waitActiveTask();
    },

    waitActiveTask() {
      return new Promise(resolve => {
        const check = () => {
          if (!this.activeTask) resolve();
          else setTimeout(check, 2000);
        };
        check();
      });
    },

    async downloadAll() {
      this.showConfirmAll = false;
      this.downloadingAll = true;
      for (const book of this.searchResults) {
        await this.downloadAndWait(book);
      }
      this.downloadingAll = false;
    },

    async generateEpub(book) {
      if (this.activeTask) {
        this.showMsg(this.$t('bookSource.downloadBusy'), 'error');
        return;
      }
      const taskKey = book.bookUrl + '|' + book.sourceName;
      if (this.generatingMap[taskKey]) return;
      const task = {
        name: book.name,
        source: book.sourceName,
        progress: 0,
        status: 'started',
        msg: this.$t('bookSource.taskStarting'),
        kind: 'epub',
        taskKey,
      };
      this.tasks.push(task);
      this.$set(this.generatingMap, taskKey, true);
      try {
        const rsp = await this.$backend('/toolbox/book_source/generate_epub', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            source: book.sourceName,
            bookUrl: book.bookUrl,
            bookTitle: book.name,
            maxChapters: 9999,
          }),
        });
        if (rsp.err === 'ok') {
          this.activeTask = task;
          this.startPoll(task);
        } else {
          task.status = 'error';
          task.msg = rsp.msg || this.$t('bookSource.downloadFailed');
          this.$delete(this.generatingMap, taskKey);
        }
      } catch (e) {
        task.status = 'error';
        task.msg = String(e);
        this.$delete(this.generatingMap, taskKey);
      }
    },

    async cancelTask(task) {
      if (!task.taskId) return;
      try {
        await this.$backend('/toolbox/book_source/cancel', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ task_id: task.taskId }),
        });
      } catch { /* 取消失败由后端任务自然结束 */ }
    },

    startPoll(task) {
      if (this.pollTimer) clearInterval(this.pollTimer);
      this.pollTimer = setInterval(async () => {
        try {
          const rsp = await this.$backend('/toolbox/book_source/progress');
          if (rsp.err === 'ok' && rsp.data) {
            task.progress = rsp.data.progress || 0;
            task.taskId = rsp.data.task_id || task.taskId;
            const pd = rsp.data.progress_data;
            task.msg = (pd && pd.status) || '';
            if (rsp.data.status === 'completed') {
              this.stopPoll();
              task.status = 'done';
              task.progress = 100;
              task.msg = task.kind === 'epub'
                ? this.$t('bookSource.generateDone')
                : this.$t('bookSource.taskDone');
              if (task.kind === 'epub') {
                task.epubUrl = '/api/toolbox/book_source/download_epub';
                this.$delete(this.generatingMap, task.taskKey || '');
              }
            } else if (rsp.data.status === 'failed') {
              this.stopPoll();
              task.status = 'error';
              task.msg = rsp.msg || this.$t('bookSource.taskFailed');
              if (task.kind === 'epub') this.$delete(this.generatingMap, task.taskKey || '');
            }
          } else if (rsp.err === 'task.not_found') {
            if (task.status === 'started') {
              task.status = 'done';
              task.progress = 100;
              task.msg = this.$t('bookSource.taskDone');
            }
            this.stopPoll();
            if (task.kind === 'epub') this.$delete(this.generatingMap, task.taskKey || '');
          }
        } catch { /* polling error, continue */ }
      }, 2000);
    },

    stopPoll() {
      if (this.pollTimer) {
        clearInterval(this.pollTimer);
        this.pollTimer = null;
      }
      this.activeTask = null;
    },

    async importZip(e) {
      const file = e.target.files[0];
      if (!file) return;
      const formData = new FormData();
      formData.append('file', file);
      try {
        const rsp = await this.$backend('/toolbox/book_source/import_zip', {
          method: 'POST',
          body: formData,
        });
        if (rsp.err === 'ok') {
          this.showMsg(this.$t('bookSource.importSuccess'), 'success');
          this.loadSources();
        } else {
          this.showMsg(rsp.msg || this.$t('bookSource.importFailed'), 'error');
        }
      } catch (e) {
        this.showMsg(this.$t('bookSource.importFailed') + ': ' + String(e), 'error');
      }
      e.target.value = '';
    },

    async doImportUrl() {
      const url = this.importUrl.trim();
      if (!url) { this.showMsg(this.$t('bookSource.importUrlEmpty'), 'error'); return; }
      this.importingUrl = true;
      try {
        const rsp = await this.$backend('/toolbox/book_source/import_url', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ url }),
        });
        if (rsp.err === 'ok') {
          this.showMsg(rsp.msg || this.$t('bookSource.importSuccess'), 'success');
          this.showImportUrl = false;
          this.importUrl = '';
          this.loadSources();
        } else {
          this.showMsg(rsp.msg || this.$t('bookSource.importFailed'), 'error');
        }
      } catch (e) {
        this.showMsg(this.$t('bookSource.importFailed') + ': ' + String(e), 'error');
      }
      this.importingUrl = false;
    },

    showMsg(msg, type) {
      this.snackbarMsg = msg;
      this.snackbarColor = type;
      this.showSnackbar = true;
    },
  },
};
</script>

<style scoped>
.bs-card {
  border: 1px solid rgba(144, 202, 249, 0.3);
}

.bs-source-list {
  max-height: 420px;
  overflow-y: auto;
  background: transparent !important;
}

.bs-source-item {
  border-radius: 8px !important;
  margin-bottom: 2px;
  cursor: pointer;
  transition: background 0.15s;
}

.bs-source-item:hover {
  background: rgba(144, 202, 249, 0.1) !important;
}

.bs-source-name {
  font-size: 13px !important;
  font-weight: 500;
}

.bs-source-meta {
  font-size: 11px !important;
}

.bs-mono {
  font-family: 'Cascadia Code', 'Fira Code', Consolas, monospace !important;
  font-size: 13px;
  line-height: 1.5;
}

.bs-fade-enter-active,
.bs-fade-leave-active {
  transition: opacity 0.3s, transform 0.25s;
}
.bs-fade-enter,
.bs-fade-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
</style>
