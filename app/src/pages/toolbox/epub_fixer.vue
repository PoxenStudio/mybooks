<template>
  <v-container fluid class="pa-4">
    <!-- Page header -->
    <v-row class="mb-3" align="center">
      <v-col class="text-center">
        <span class="text-h5 font-weight-bold">{{ $t('epubFixer.title') }}</span>
      </v-col>
      <v-col cols="auto">
        <v-btn small color="error" @click="$router.go(-1)">
          <v-icon small left>mdi-close</v-icon>{{ $t('epubFixer.close') }}
        </v-btn>
      </v-col>
    </v-row>

    <v-row justify="center">
      <v-col cols="12" md="10" lg="9" xl="7">
        <v-card rounded="xl" outlined class="ef-card pa-6">
          <!-- Hint -->
          <v-alert type="info" dense text rounded="lg" class="mb-5">
            {{ $t('epubFixer.hint') }}
          </v-alert>

          <!-- Search field -->
          <v-text-field
            v-model="query"
            :label="$t('epubFixer.searchPlaceholder')"
            :loading="searching"
            outlined
            dense
            clearable
            hide-details
            class="mb-3"
            prepend-inner-icon="mdi-magnify"
            @keyup.enter="search"
            @click:clear="clearSearch"
          />

          <!-- Book list -->
          <div class="ef-book-list mb-2">
            <div v-if="searching" class="text-center py-6">
              <v-progress-circular indeterminate color="primary" size="32" />
            </div>
            <div v-else-if="books.length === 0 && searched" class="text-center py-4 grey--text">
              {{ $t('epubFixer.noResults') }}
            </div>
            <v-list v-else-if="books.length > 0" dense class="ef-list pa-0">
              <v-list-item
                v-for="book in books"
                :key="book.id"
                :class="['ef-book-item', { 'ef-book-selected': isPicked(book) }]"
                @click="toggleBook(book)"
              >
                <v-list-item-avatar tile size="44" class="mr-3">
                  <v-img :src="book.thumb" :alt="book.title">
                    <template #error>
                      <v-icon color="grey lighten-1">mdi-book-outline</v-icon>
                    </template>
                  </v-img>
                </v-list-item-avatar>
                <v-list-item-content>
                  <v-list-item-title class="ef-book-title">{{ book.title }}</v-list-item-title>
                  <v-list-item-subtitle class="ef-book-author">{{ (book.authors || []).join(', ') }}</v-list-item-subtitle>
                  <div class="mt-1">
                    <v-chip
                      v-for="file in (book.files || [])"
                      :key="file.format"
                      x-small
                      :color="file.format === 'EPUB' ? 'primary' : 'default'"
                      outlined
                      class="mr-1"
                    >{{ file.format }}</v-chip>
                  </div>
                </v-list-item-content>
                <v-list-item-action v-if="isPicked(book)">
                  <v-icon color="primary">mdi-check-circle</v-icon>
                </v-list-item-action>
              </v-list-item>
            </v-list>
          </div>
          <div v-if="pickedCount" class="mb-4 grey--text text--darken-1 ef-picked-hint">
            {{ $t('epubFixer.pickedCount', { n: pickedEpubCount, total: pickedCount }) }}
          </div>

          <!-- Detect button -->
          <div class="d-flex align-center mb-3">
            <v-btn
              small
              outlined
              color="primary"
              :loading="analyzing"
              :disabled="running || analyzing || pickedEpubCount === 0"
              @click="analyze"
            >
              <v-icon small left>mdi-stethoscope</v-icon>
              {{ $t('epubFixer.detectBtn') }}
            </v-btn>
            <span v-if="analyzed && !analyzing" class="ml-3 ef-detect-hint">
              {{ detectSummary }}
            </span>
          </div>

          <!-- Detect result per book -->
          <div v-if="analyzed" class="ef-findings mb-4">
            <div v-for="r in analyzeResults" :key="r.book_id" class="ef-finding-row">
              <v-icon small :color="r.error ? 'error' : (r.drm ? 'warning' : 'success')" class="mr-1">
                {{ r.error ? 'mdi-alert-circle' : (r.drm ? 'mdi-lock' : 'mdi-check-circle-outline') }}
              </v-icon>
              <span class="ef-finding-title">{{ r.title || ('ID ' + r.book_id) }}</span>
              <span v-if="r.error" class="error--text ef-finding-detail">{{ r.error }}</span>
              <span v-else-if="r.drm" class="warning--text ef-finding-detail">{{ $t('epubFixer.findingsDrm') }}</span>
              <span v-else-if="totalFindings(r) === 0" class="grey--text ef-finding-detail">{{ $t('epubFixer.findingsNone') }}</span>
              <span v-else class="ef-finding-detail">
                <v-tooltip bottom max-width="420">
                  <template #activator="{ on, attrs }">
                    <span v-bind="attrs" v-on="on" class="primary--text">
                      {{ $t('epubFixer.findingsCount', { n: totalFindings(r) }) }}
                    </span>
                  </template>
                  <div v-for="f in findingLines(r)" :key="f.label" class="mb-1">
                    <b>{{ f.label }}</b> ×{{ f.count }}
                    <div v-if="f.samples.length" class="ef-sample">{{ f.samples.join('；') }}</div>
                  </div>
                </v-tooltip>
              </span>
            </div>
          </div>

          <!-- Repair ops checkboxes -->
          <div class="ef-ops mb-4">
            <div class="d-flex align-center mb-1">
              <span class="subtitle-2 font-weight-bold">{{ $t('epubFixer.opsTitle') }}</span>
              <v-spacer />
              <v-btn x-small text color="primary" class="mr-1" @click="setAllOps(true)">
                {{ $t('epubFixer.opsSelectAll') }}
              </v-btn>
              <v-btn x-small text color="primary" @click="setAllOps(false)">
                {{ $t('epubFixer.opsSelectNone') }}
              </v-btn>
            </div>
            <v-row dense>
              <v-col v-for="key in opKeys" :key="key" cols="12" sm="6" md="4">
                <v-checkbox
                  v-model="opChecked[key]"
                  dense
                  hide-details
                  class="mt-0"
                  :disabled="running"
                >
                  <template #label>
                    <span :class="{ 'warning--text text--darken-2': key === 'remove_unmanifested' }">
                      {{ $t('epubFixer.op.' + key) }}
                    </span>
                  </template>
                </v-checkbox>
              </v-col>
            </v-row>
            <div class="ef-op-warn">{{ $t('epubFixer.op.unmanifestedWarn') }}</div>
          </div>

          <!-- Pipeline options -->
          <div class="ef-options mb-4">
            <v-checkbox
              v-model="reconvert"
              dense
              hide-details
              class="mt-0"
              :disabled="running"
            >
              <template #label>
                <span>{{ $t('epubFixer.reconvertLabel') }}
                  <span class="grey--text ef-option-hint">{{ $t('epubFixer.reconvertHint') }}</span>
                </span>
              </template>
            </v-checkbox>
            <v-radio-group
              v-model="writeMode"
              row
              dense
              hide-details
              class="mt-2"
              :disabled="running"
            >
              <v-radio value="overwrite" :label="$t('epubFixer.writeOverwrite')" />
              <v-radio value="new_book" :label="$t('epubFixer.writeNewBook')" />
            </v-radio-group>
            <v-text-field
              v-if="writeMode === 'new_book'"
              v-model="suffix"
              :label="$t('epubFixer.suffixLabel')"
              outlined
              dense
              counter="30"
              class="mb-2"
              hide-details
            />
            <v-checkbox
              v-if="writeMode === 'overwrite'"
              v-model="backup"
              :label="$t('epubFixer.backupLabel')"
              dense
              hide-details
              class="mt-1"
              :disabled="running"
            />
          </div>

          <!-- Progress -->
          <div v-if="running || progress" class="mb-4">
            <div class="d-flex align-center mb-1">
              <span class="subtitle-2">{{ $t('epubFixer.progressBook', { i: progress.book_index, n: progress.book_total }) }}</span>
              <span class="ml-2 grey--text ef-stage-text">{{ stageText }}</span>
              <span class="ml-2 grey--text ef-stage-text">{{ progress.current_title }}</span>
            </div>
            <v-progress-linear :value="progress.progress || 0" rounded height="8" />
            <div v-for="(r, i) in (progress.results || [])" :key="i" class="ef-result-row">
              <v-icon x-small :color="r.ok ? 'success' : 'error'" class="mr-1">
                {{ r.ok ? 'mdi-check' : 'mdi-close' }}
              </v-icon>
              <span class="ef-result-title">{{ r.title }}</span>
              <span v-if="!r.ok" class="error--text ef-result-detail">{{ r.error }}</span>
              <span v-else class="grey--text ef-result-detail">
                {{ resultSummary(r) }}
              </span>
            </div>
          </div>

          <!-- Result message -->
          <transition name="ef-fade">
            <v-alert
              v-if="resultMsg"
              :type="resultType"
              dense
              text
              rounded="lg"
              class="mb-4"
            >{{ resultMsg }}</v-alert>
          </transition>

          <!-- Start button -->
          <div class="d-flex justify-center">
            <v-btn
              color="primary"
              class="ef-start-btn"
              :loading="starting"
              :disabled="running || starting || analyzing || pickedEpubCount === 0"
              @click="startRepair"
            >
              <v-icon left>mdi-wrench</v-icon>
              {{ $t('epubFixer.startBtn') }}
            </v-btn>
          </div>
        </v-card>
      </v-col>
    </v-row>
  </v-container>
</template>

<script>
export default {
  data: () => ({
    query: '',
    books: [],
    searching: false,
    searched: false,
    picked: [],

    opKeys: [
      'remove_artifacts',
      'remove_missing_manifest',
      'add_unmanifested',
      'remove_unmanifested',
      'remove_javascript',
      'remove_drm_meta_tags',
      'remove_page_maps',
      'remove_xpgt',
      'strip_kobo',
      'remove_unused_images',
      'remove_broken_cover_pages',
      'fix_broken_toc',
      'encode_utf8',
    ],
    opDefaults: [
      'remove_artifacts',
      'remove_missing_manifest',
      'add_unmanifested',
      'remove_javascript',
      'remove_drm_meta_tags',
      'remove_page_maps',
      'remove_xpgt',
      'strip_kobo',
      'remove_unused_images',
      'remove_broken_cover_pages',
      'fix_broken_toc',
      'encode_utf8',
    ],
    opChecked: {},
    reconvert: true,
    writeMode: 'overwrite',
    suffix: '',
    backup: false,

    analyzing: false,
    analyzed: false,
    analyzeResults: [],

    starting: false,
    running: false,
    progress: null,
    pollTimer: null,
    pollMode: '',
    resultMsg: '',
    resultType: 'success',
  }),
  computed: {
    pickedCount() {
      return this.picked.length;
    },
    pickedEpubCount() {
      return this.picked.filter(
        (b) => (b.files || []).some((f) => f.format === 'EPUB')
      ).length;
    },
    detectSummary() {
      const books = this.analyzeResults || [];
      const bad = books.filter((r) => !r.error && !r.drm && this.totalFindings(r) > 0).length;
      const drm = books.filter((r) => r.drm).length;
      const fail = books.filter((r) => r.error).length;
      const parts = [
        this.$t('epubFixer.detectNeeds', { n: bad }),
      ];
      if (drm) parts.push(this.$t('epubFixer.detectDrm', { n: drm }));
      if (fail) parts.push(this.$t('epubFixer.detectFail', { n: fail }));
      return parts.join('，');
    },
    stageText() {
      const s = this.progress && this.progress.stage;
      if (!s) return '';
      const key = 'epubFixer.stage.' + s;
      const t = this.$te(key) ? this.$t(key) : s;
      return this.$t('epubFixer.stagePrefix') + t;
    },
  },
  created() {
    this.$store.commit('navbar', true);
    const checked = {};
    this.opKeys.forEach((k) => {
      checked[k] = this.opDefaults.indexOf(k) >= 0;
    });
    this.opChecked = checked;
  },
  beforeDestroy() {
    this.stopPolling();
  },
  methods: {
    async search() {
      const q = (this.query || '').trim();
      if (!q) return;
      this.searching = true;
      this.searched = false;
      this.picked = [];
      try {
        const rsp = await this.$backend(`/search?title=title:${encodeURIComponent(q)}`);
        this.books = rsp.err === 'ok' ? (rsp.books || []) : [];
      } catch (_e) {
        this.books = [];
      } finally {
        this.searching = false;
        this.searched = true;
      }
    },
    clearSearch() {
      this.books = [];
      this.picked = [];
      this.searched = false;
      this.resetAnalyze();
    },
    isPicked(book) {
      return this.picked.some((b) => b.id === book.id);
    },
    toggleBook(book) {
      if (this.isPicked(book)) {
        this.picked = this.picked.filter((b) => b.id !== book.id);
      } else {
        this.picked.push(book);
      }
      this.resetAnalyze();
    },
    resetAnalyze() {
      this.analyzed = false;
      this.analyzeResults = [];
      this.resultMsg = '';
    },
    totalFindings(r) {
      const findings = r.findings || {};
      return Object.keys(findings).reduce((sum, k) => sum + (findings[k].count || 0), 0);
    },
    findingLines(r) {
      const findings = r.findings || {};
      const lines = [];
      this.opKeys.forEach((k) => {
        const f = findings[k];
        if (f && f.count > 0) {
          lines.push({ label: this.$t('epubFixer.op.' + k), count: f.count, samples: f.samples || [] });
        }
      });
      return lines;
    },
    async analyze() {
      const ids = this.picked
        .filter((b) => (b.files || []).some((f) => f.format === 'EPUB'))
        .map((b) => b.id);
      if (!ids.length) return;
      this.resultMsg = '';
      this.starting = false;
      try {
        const rsp = await this.$backend('/toolbox/epub_fixer/analyze', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ book_ids: ids }),
        });
        if (rsp.err === 'ok') {
          // 检测是后台任务：轮询 /progress，完成后取 results
          this.pollMode = 'analyze';
          this.analyzing = true;
          this.progress = { progress: 0, book_index: 0, book_total: ids.length, stage: 'analyze', results: [] };
          this.startPolling();
        } else {
          this.resultMsg = rsp.msg || rsp.err;
          this.resultType = 'error';
        }
      } catch (e) {
        this.resultMsg = String(e);
        this.resultType = 'error';
      }
    },
    applyAnalyzePrecheck() {
      // 按发现预勾选：有问题的项默认勾上；remove_unmanifested 需手动开启
      const counts = {};
      this.analyzeResults.forEach((r) => {
        Object.keys(r.findings || {}).forEach((k) => {
          counts[k] = (counts[k] || 0) + ((r.findings[k] || {}).count || 0);
        });
      });
      const checked = {};
      this.opKeys.forEach((k) => {
        checked[k] = (counts[k] || 0) > 0 && k !== 'remove_unmanifested';
      });
      this.opChecked = checked;
    },
    setAllOps(val) {
      const checked = {};
      this.opKeys.forEach((k) => {
        checked[k] = val;
      });
      this.opChecked = checked;
    },
    resultSummary(r) {
      const ops = r.ops || {};
      const total = Object.keys(ops).reduce((sum, k) => sum + (ops[k] || 0), 0);
      const parts = [this.$t('epubFixer.resultOps', { n: total })];
      if (r.reconverted) parts.push(this.$t('epubFixer.resultReconverted'));
      if (r.new_book_id) parts.push(this.$t('epubFixer.resultNewBook', { id: r.new_book_id }));
      (r.warnings || []).forEach((w) => parts.push(w));
      return parts.join('；');
    },
    async startRepair() {
      if (this.pickedEpubCount === 0) return;
      this.resultMsg = '';
      this.starting = true;
      try {
        const bookIds = this.picked
          .filter((b) => (b.files || []).some((f) => f.format === 'EPUB'))
          .map((b) => b.id);
        const payload = {
          book_ids: bookIds,
          ops: this.opKeys.filter((k) => this.opChecked[k]),
          reconvert: this.reconvert,
          write_mode: this.writeMode,
        };
        if (this.writeMode === 'new_book') payload.suffix = this.suffix;
        else payload.backup = this.backup;
        const rsp = await this.$backend('/toolbox/epub_fixer/repair', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        if (rsp.err === 'ok') {
          this.resultMsg = rsp.msg || '';
          this.resultType = 'success';
          this.running = true;
          this.pollMode = 'repair';
          this.progress = { progress: 0, book_index: 0, book_total: bookIds.length, results: [] };
          this.startPolling();
        } else {
          this.resultMsg = rsp.msg || rsp.err;
          this.resultType = 'error';
        }
      } catch (e) {
        this.resultMsg = String(e);
        this.resultType = 'error';
      } finally {
        this.starting = false;
      }
    },
    startPolling() {
      this.stopPolling();
      this.pollTimer = setInterval(this.pollProgress, 2000);
      this.pollProgress();
    },
    stopPolling() {
      if (this.pollTimer) {
        clearInterval(this.pollTimer);
        this.pollTimer = null;
      }
    },
    async pollProgress() {
      try {
        const rsp = await this.$backend('/toolbox/epub_fixer/progress');
        if (rsp.err === 'ok' && rsp.data) {
          this.progress = rsp.data;
          if (rsp.data.status === 'completed') {
            this.stopPolling();
            if (this.pollMode === 'analyze') {
              // 检测完成：取回逐本结果并按发现预勾选
              this.analyzeResults = this.progress.results || [];
              this.applyAnalyzePrecheck();
              this.analyzed = true;
              this.analyzing = false;
            } else {
              this.running = false;
              this.resultMsg = this.$t('epubFixer.fixSuccess');
              this.resultType = 'success';
            }
          }
        } else if (rsp.err === 'task.failed') {
          this.stopPolling();
          if (rsp.data) this.progress = rsp.data;
          if (this.pollMode === 'analyze') {
            this.analyzing = false;
          } else {
            this.running = false;
          }
          this.resultMsg = rsp.msg || this.$t('epubFixer.taskFailed');
          this.resultType = 'error';
        } else if (rsp.err === 'task.not_found') {
          this.stopPolling();
          this.running = false;
          this.analyzing = false;
        }
      } catch (_e) {
        // 网络抖动：保留状态，下个周期重试
      }
    },
  },
};
</script>

<style scoped>
.ef-card {
  border: 2px solid #90CAF9;
}

.ef-book-list {
  max-height: 320px;
  overflow-y: auto;
}

.ef-list {
  background: transparent !important;
}

.ef-book-item {
  border-radius: 8px !important;
  margin-bottom: 4px;
  cursor: pointer;
  transition: background 0.15s;
}

.ef-book-item:hover {
  background: rgba(144, 202, 249, 0.15) !important;
}

.ef-book-selected {
  background: rgba(144, 202, 249, 0.25) !important;
  border: 1px solid #90CAF9;
}

.ef-book-title {
  font-size: 13px !important;
  white-space: normal !important;
  line-height: 1.3;
}

.ef-book-author {
  font-size: 11px !important;
}

.ef-picked-hint {
  font-size: 12px;
}

.ef-detect-hint {
  font-size: 12px;
}

.ef-findings {
  max-height: 180px;
  overflow-y: auto;
  border: 1px solid rgba(0, 0, 0, 0.08);
  border-radius: 8px;
  padding: 8px 12px;
}

.ef-finding-row {
  display: flex;
  align-items: baseline;
  font-size: 12px;
  line-height: 1.7;
}

.ef-finding-title {
  font-weight: 500;
  margin-right: 8px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 260px;
}

.ef-finding-detail {
  font-size: 12px;
}

.ef-ops {
  border: 1px solid rgba(0, 0, 0, 0.08);
  border-radius: 8px;
  padding: 10px 12px 6px;
}

.ef-op-warn {
  font-size: 11px;
  color: #b26a00;
  margin-top: 2px;
}

.ef-options {
  border: 1px solid rgba(0, 0, 0, 0.08);
  border-radius: 8px;
  padding: 10px 12px 8px;
}

.ef-option-hint {
  font-size: 11px;
}

.ef-stage-text {
  font-size: 12px;
}

.ef-result-row {
  display: flex;
  align-items: baseline;
  font-size: 12px;
  line-height: 1.7;
}

.ef-result-title {
  font-weight: 500;
  margin-right: 8px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 260px;
}

.ef-result-detail {
  font-size: 12px;
}

.ef-start-btn {
  width: 50%;
  min-width: 180px;
}

.ef-fade-enter-active,
.ef-fade-leave-active {
  transition: opacity 0.3s, transform 0.25s;
}
.ef-fade-enter,
.ef-fade-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
</style>
