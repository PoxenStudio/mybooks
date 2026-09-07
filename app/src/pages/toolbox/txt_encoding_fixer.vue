<template>
  <v-container fluid class="pa-4">
    <!-- Page header -->
    <v-row class="mb-3" align="center">
      <v-col class="text-center">
        <span class="text-h5 font-weight-bold">{{ $t('txtEncodingFixer.title') }}</span>
      </v-col>
      <v-col cols="auto">
        <v-btn small color="error" @click="$router.go(-1)">
          <v-icon small left>mdi-close</v-icon>{{ $t('txtEncodingFixer.close') }}
        </v-btn>
      </v-col>
    </v-row>

    <!-- Main card -->
    <v-row justify="center">
      <v-col cols="12" md="8" lg="6">
        <v-card rounded="xl" outlined class="tef-card pa-6">
          <!-- Hint -->
          <v-alert type="info" dense text rounded="lg" class="mb-5">
            {{ $t('txtEncodingFixer.hint') }}
          </v-alert>

          <!-- Search field -->
          <v-text-field
            v-model="query"
            :label="$t('txtEncodingFixer.selectBook')"
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
          <div class="tef-book-list mb-4">
            <div v-if="searching" class="text-center py-6">
              <v-progress-circular indeterminate color="primary" size="32" />
            </div>
            <div v-else-if="books.length === 0 && searched" class="text-center py-4 grey--text">
              {{ $t('txtEncodingFixer.noResults') }}
            </div>
            <v-list v-else-if="books.length > 0" dense class="tef-list pa-0">
              <v-list-item
                v-for="book in books"
                :key="book.id"
                :class="['tef-book-item', { 'tef-book-selected': selected && selected.id === book.id }]"
                @click="selectBook(book)"
              >
                <v-list-item-avatar tile size="44" class="mr-3">
                  <v-img :src="book.thumb" :alt="book.title">
                    <template #error>
                      <v-icon color="grey lighten-1">mdi-book-outline</v-icon>
                    </template>
                  </v-img>
                </v-list-item-avatar>
                <v-list-item-content>
                  <v-list-item-title class="tef-book-title">{{ book.title }}</v-list-item-title>
                  <v-list-item-subtitle class="tef-book-author">{{ (book.authors || []).join(', ') }}</v-list-item-subtitle>
                  <div class="mt-1">
                    <v-chip
                      v-for="file in (book.files || [])"
                      :key="file.format"
                      x-small
                      :color="file.format === 'TXT' ? 'primary' : 'default'"
                      outlined
                      class="mr-1"
                    >{{ file.format }}</v-chip>
                  </div>
                </v-list-item-content>
                <v-list-item-action v-if="selected && selected.id === book.id">
                  <v-icon color="primary">mdi-check-circle</v-icon>
                </v-list-item-action>
              </v-list-item>
            </v-list>
          </div>

          <template v-if="selected">
            <v-divider class="mb-4" />

            <!-- Analyze -->
            <v-btn
              block
              outlined
              color="info"
              class="mb-3"
              :loading="analyzing"
              :disabled="!canAnalyze || processing"
              @click="startAnalyze"
            >
              <v-icon left>mdi-text-recognition</v-icon>{{ $t('txtEncodingFixer.analyzeBtn') }}
            </v-btn>

            <!-- Report -->
            <template v-if="report">
              <v-card outlined rounded="lg" class="tef-report mb-4">
                <v-card-title class="py-2 text-subtitle-1">
                  <v-icon small left color="primary">mdi-file-document-outline</v-icon>
                  {{ $t('txtEncodingFixer.reportTitle') }}
                </v-card-title>
                <v-card-text class="pt-0">
                  <div class="d-flex flex-wrap mb-2">
                    <v-chip small outlined class="mr-2 mb-1">
                      <v-icon small left>mdi-file-code-outline</v-icon>{{ report.encoding }}
                    </v-chip>
                    <v-chip small outlined class="mr-2 mb-1">
                      <v-icon small left>mdi-percent-outline</v-icon>{{ $t('txtEncodingFixer.confidence') }}：{{ Math.round(report.confidence * 100) }}%
                    </v-chip>
                    <v-chip
                      small
                      :color="report.mojibake ? 'warning' : 'success'"
                      outlined
                      class="mr-2 mb-1"
                    >
                      <v-icon small left>{{ report.mojibake ? 'mdi-alert-circle-outline' : 'mdi-check-circle-outline' }}</v-icon>
                      {{ report.mojibake ? $t('txtEncodingFixer.mojibakeYes') : $t('txtEncodingFixer.mojibakeNo') }}
                    </v-chip>
                  </div>

                  <v-alert
                    v-if="report.garbage"
                    type="error"
                    dense
                    text
                    rounded="lg"
                    class="mb-3"
                  >{{ $t('txtEncodingFixer.garbageAlert') }}</v-alert>

                  <div v-if="report.reasons && report.reasons.length" class="mb-3">
                    <div class="caption grey--text mb-1">{{ $t('txtEncodingFixer.reasons') }}</div>
                    <div
                      v-for="(reason, i) in report.reasons"
                      :key="i"
                      class="caption"
                    >• {{ reason }}</div>
                  </div>

                  <div class="text-subtitle-2 mb-1">{{ $t('txtEncodingFixer.previewTitle') }}</div>
                  <v-sheet outlined rounded="lg" class="tef-preview pa-3">
                    <div class="tef-preview-text">{{ report.preview || $t('txtEncodingFixer.previewEmpty') }}</div>
                  </v-sheet>
                </v-card-text>
              </v-card>
            </template>

            <!-- Fix -->
            <v-btn
              block
              large
              color="primary"
              class="mt-2"
              :loading="processing"
              :disabled="!canFix || analyzing"
              @click="startFix"
            >
              <v-icon left>mdi-cog-refresh</v-icon>{{ $t('txtEncodingFixer.fixBtn') }}
            </v-btn>

            <!-- Progress -->
            <div v-if="processing" class="mt-4">
              <v-progress-linear
                :value="progress"
                color="primary"
                height="10"
                rounded
                class="mb-2"
              />
              <div class="text-center caption grey--text">
                {{ progressMsg }}
              </div>
            </div>

            <!-- Result -->
            <v-alert
              v-if="resultMsg"
              :type="resultType === 'success' ? 'success' : 'error'"
              dense
              text
              rounded="lg"
              class="mt-4"
            >{{ resultMsg }}</v-alert>
          </template>
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
    selected: null,

    analyzing: false,
    report: null,
    reportErr: '',

    processing: false,
    progress: 0,
    progressMsg: '',
    resultMsg: '',
    resultType: 'success',
    pollTimer: null,
  }),
  computed: {
    canAnalyze() {
      return this.selected && (this.selected.files || []).some((f) => f.format === 'TXT');
    },
    canFix() {
      return this.selected && (this.selected.files || []).some((f) => f.format === 'TXT');
    },
  },
  created() {
    this.$store.commit('navbar', true);
  },
  beforeDestroy() {
    this.stopPolling();
  },
  methods: {
    searchDebounce: null,
    async search() {
      // 防抖：连按回车/快速输入时只发最后一个请求
      clearTimeout(this.searchDebounce);
      this.searchDebounce = setTimeout(() => {
        this.doSearch();
      }, 300);
    },
    async doSearch() {
      const q = (this.query || '').trim();
      if (!q) return;
      this.searching = true;
      this.searched = false;
      this.selected = null;
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
      this.selected = null;
      this.searched = false;
      this.report = null;
    },
    selectBook(book) {
      this.selected = this.selected && this.selected.id === book.id ? null : book;
      this.report = null;
      this.resultMsg = '';
      this.reportErr = '';
    },
    stageText(stage) {
      const map = {
        reading: this.$t('txtEncodingFixer.progressReading'),
        detecting: this.$t('txtEncodingFixer.progressDetecting'),
        saving: this.$t('txtEncodingFixer.progressSaving'),
        completed: this.$t('txtEncodingFixer.progressCompleted'),
      };
      return map[stage] || '';
    },
    startPolling() {
      this.stopPolling();
      this.pollTimer = setInterval(this.pollProgress, 2000);
    },
    stopPolling() {
      if (this.pollTimer) {
        clearInterval(this.pollTimer);
        this.pollTimer = null;
      }
    },
    async pollProgress() {
      try {
        const rsp = await this.$backend('/toolbox/txt_encoding_fixer/progress');
        if (rsp.err === 'task.not_found') {
          return;
        }
        const data = rsp.data || {};
        this.progress = data.progress || 0;
        this.progressMsg = this.stageText(data.stage);

        if (rsp.err === 'task.failed') {
          this.stopPolling();
          this.processing = false;
          this.resultMsg = rsp.msg || this.$t('txtEncodingFixer.fixFailed');
          this.resultType = 'error';
          return;
        }
        if (data.status === 'completed') {
          this.stopPolling();
          this.processing = false;
          this.progress = 100;
          this.progressMsg = this.$t('txtEncodingFixer.progressCompleted');
          this.resultMsg = this.$t('txtEncodingFixer.fixCompleted');
          this.resultType = 'success';
        }
      } catch (e) {
        // 网络抖动时忽略，继续轮询
      }
    },
    async startAnalyze() {
      if (!this.canAnalyze || this.processing) return;
      this.analyzing = true;
      this.report = null;
      this.reportErr = '';
      this.resultMsg = '';
      try {
        const rsp = await this.$backend('/toolbox/txt_encoding_fixer/analyze', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ book_id: this.selected.id }),
        });
        if (rsp.err === 'ok') {
          this.report = rsp.data || {};
        } else {
          this.reportErr = rsp.msg || rsp.err;
          this.resultMsg = this.reportErr;
          this.resultType = 'error';
        }
      } catch (e) {
        this.reportErr = String(e);
        this.resultMsg = this.reportErr;
        this.resultType = 'error';
      } finally {
        this.analyzing = false;
      }
    },
    async startFix() {
      if (!this.canFix || this.processing) return;
      this.resultMsg = '';
      this.processing = true;
      this.progress = 0;
      this.progressMsg = '';
      try {
        const rsp = await this.$backend('/toolbox/txt_encoding_fixer/fix', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ book_id: this.selected.id }),
        });
        if (rsp.err === 'ok') {
          this.resultMsg = rsp.msg || this.$t('txtEncodingFixer.fixStarted');
          this.resultType = 'success';
          this.startPolling();
        } else {
          this.processing = false;
          this.resultMsg = rsp.msg || rsp.err;
          this.resultType = 'error';
        }
      } catch (e) {
        this.processing = false;
        this.resultMsg = String(e);
        this.resultType = 'error';
      }
    },
  },
};
</script>
