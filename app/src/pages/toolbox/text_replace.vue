<template>
  <v-container fluid class="pa-4">
    <!-- Page header -->
    <v-row class="mb-3" align="center">
      <v-col class="text-center">
        <span class="text-h5 font-weight-bold">{{ $t('textReplace.title') }}</span>
      </v-col>
      <v-col cols="auto">
        <v-btn small color="error" @click="$router.go(-1)">
          <v-icon small left>mdi-close</v-icon>{{ $t('textReplace.close') }}
        </v-btn>
      </v-col>
    </v-row>

    <!-- Main card -->
    <v-row justify="center">
      <v-col cols="12" md="8" lg="6">
        <v-card rounded="xl" outlined class="tr-card pa-6">
          <!-- Hint -->
          <v-alert type="info" dense text rounded="lg" class="mb-5">
            {{ $t('textReplace.hint') }}
          </v-alert>

          <!-- Search field -->
          <v-text-field
            v-model="query"
            :label="$t('textReplace.selectBook')"
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
          <div class="tr-book-list mb-4">
            <div v-if="searching" class="text-center py-6">
              <v-progress-circular indeterminate color="primary" size="32" />
            </div>
            <div v-else-if="books.length === 0 && searched" class="text-center py-4 grey--text">
              {{ $t('textReplace.noResults') }}
            </div>
            <v-list v-else-if="books.length > 0" dense class="tr-list pa-0">
              <v-list-item
                v-for="book in books"
                :key="book.id"
                :class="['tr-book-item', { 'tr-book-selected': selected && selected.id === book.id }]"
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
                  <v-list-item-title class="tr-book-title">{{ book.title }}</v-list-item-title>
                  <v-list-item-subtitle class="tr-book-author">{{ (book.authors || []).join(', ') }}</v-list-item-subtitle>
                  <div class="mt-1">
                    <v-chip
                      v-for="file in (book.files || [])"
                      :key="file.format"
                      x-small
                      :color="['EPUB', 'TXT'].indexOf(file.format) >= 0 ? 'primary' : 'default'"
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

            <!-- Format selection (only when both TXT and EPUB exist) -->
            <div v-if="bookFormats.length > 1" class="mb-3">
              <div class="caption font-weight-medium mb-1">{{ $t('textReplace.formatLabel') }}</div>
              <v-radio-group v-model="selectedFormat" dense row class="mt-0">
                <v-radio
                  v-for="f in bookFormats"
                  :key="f"
                  :label="f"
                  :value="f"
                  color="primary"
                />
              </v-radio-group>
            </div>
            <div v-else-if="bookFormats.length === 1" class="caption grey--text mb-3">
              {{ $t('textReplace.formatOnly', { format: bookFormats[0] }) }}
            </div>

            <!-- Mode switch -->
            <v-radio-group v-model="useRegex" dense row class="mt-1 mb-3">
              <v-radio :label="$t('textReplace.modePlain')" :value="false" />
              <v-radio :label="$t('textReplace.modeRegex')" :value="true" />
            </v-radio-group>

            <!-- Cheat sheet -->
            <v-alert
              v-if="useRegex"
              color="secondary"
              dense
              text
              rounded="lg"
              class="mb-3 tr-cheat"
            >
              <div class="caption font-weight-medium mb-1">{{ $t('textReplace.cheatTitle') }}</div>
              <div class="caption">{{ $t('textReplace.cheatBody') }}</div>
            </v-alert>

            <!-- Pattern & replacement -->
            <v-textarea
              v-model="pattern"
              :label="$t('textReplace.pattern')"
              :placeholder="$t('textReplace.patternPlaceholder')"
              outlined
              dense
              rows="2"
              auto-grow
              hide-details
              class="mb-3"
              prepend-inner-icon="mdi-magnify"
            />

            <v-textarea
              v-model="replacement"
              :label="$t('textReplace.replacement')"
              :placeholder="$t('textReplace.replacementPlaceholder')"
              outlined
              dense
              rows="2"
              auto-grow
              hide-details
              class="mb-3"
              prepend-inner-icon="mdi-pencil-outline"
            />

            <v-text-field
              v-model="suffix"
              :label="$t('textReplace.suffix')"
              outlined
              dense
              hide-details
              class="mb-4"
              prepend-inner-icon="mdi-format-title"
            />

            <!-- Preview -->
            <v-btn
              block
              outlined
              color="info"
              class="mb-2"
              :loading="previewing"
              :disabled="!pattern || processing"
              @click="startPreview"
            >
              <v-icon left>mdi-eye-outline</v-icon>{{ $t('textReplace.previewBtn') }}
            </v-btn>

            <!-- Preview result -->
            <template v-if="previewResult !== null">
              <v-alert
                v-if="previewError"
                type="error"
                dense
                text
                rounded="lg"
                class="mt-3"
              >{{ previewError }}</v-alert>
              <v-card v-else outlined rounded="lg" class="tr-preview mt-3 mb-2">
                <v-card-title class="py-2 text-subtitle-1">
                  <v-icon small left color="primary">mdi-format-list-bulleted</v-icon>
                  {{ $t('textReplace.previewTitle', { format: previewResult.format, count: previewResult.matches }) }}
                </v-card-title>
                <v-card-text class="pt-0">
                  <v-alert
                    v-if="previewResult.truncated"
                    type="warning"
                    dense
                    text
                    rounded="lg"
                    class="mb-3"
                  >{{ $t('textReplace.previewTruncated') }}</v-alert>
                  <div v-if="previewResult.matches === 0" class="caption grey--text">
                    {{ $t('textReplace.previewZero') }}
                  </div>
                  <div
                    v-for="(sample, i) in previewResult.samples"
                    :key="i"
                    class="tr-sample mb-2"
                  >
                    <div class="caption grey--text mb-1">{{ $t('textReplace.sampleIndex', { index: sample.index }) }}</div>
                    <v-sheet outlined rounded="lg" class="pa-2 tr-sample-text">
                      <span>{{ sample.pre }}</span>
                      <mark class="tr-mark">{{ sample.match }}</mark>
                      <span>{{ sample.post }}</span>
                    </v-sheet>
                  </div>
                </v-card-text>
              </v-card>
            </template>

            <!-- Run -->
            <v-btn
              block
              large
              color="primary"
              class="mt-3"
              :loading="processing"
              :disabled="!pattern || previewing"
              @click="startRun"
            >
              <v-icon left>mdi-play</v-icon>{{ $t('textReplace.runBtn') }}
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
    selectedFormat: '',

    useRegex: false,
    pattern: '',
    replacement: '',
    suffix: '',

    previewing: false,
    previewResult: null,
    previewError: '',

    processing: false,
    progress: 0,
    progressMsg: '',
    resultMsg: '',
    resultType: 'success',
    pollTimer: null,
  }),
  computed: {
    bookFormats() {
      if (!this.selected || !this.selected.files) return [];
      const fmts = [];
      for (const f of this.selected.files) {
        const fmt = (f.format || '').toUpperCase();
        if ((fmt === 'TXT' || fmt === 'EPUB') && !fmts.includes(fmt)) {
          fmts.push(fmt);
        }
      }
      return fmts;
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
    },
    selectBook(book) {
      this.selected = this.selected && this.selected.id === book.id ? null : book;
      const fmts = book.files
        ? book.files.map(f => (f.format || '').toUpperCase()).filter(f => f === 'TXT' || f === 'EPUB')
        : [];
      this.selectedFormat = fmts.includes('EPUB') ? 'EPUB' : (fmts.includes('TXT') ? 'TXT' : '');
      this.previewResult = null;
      this.previewError = '';
      this.resultMsg = '';
    },
    stageText(stage) {
      const map = {
        reading: this.$t('textReplace.progressReading'),
        processing: this.$t('textReplace.progressProcessing'),
        saving: this.$t('textReplace.progressSaving'),
        completed: this.$t('textReplace.progressCompleted'),
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
        const rsp = await this.$backend('/toolbox/text_replace/progress');
        if (rsp.err === 'task.not_found') {
          // 任务已不在（如服务重启后内存任务丢失）：停止轮询，避免每 2s 空转
          this.stopPolling();
          this.processing = false;
          this.resultMsg = this.$t('textReplace.taskLost');
          this.resultType = 'error';
          return;
        }
        const data = rsp.data || {};
        this.progress = data.progress || 0;
        this.progressMsg = this.stageText(data.stage);

        if (rsp.err === 'task.failed') {
          this.stopPolling();
          this.processing = false;
          this.resultMsg = rsp.msg || this.$t('textReplace.runFailed');
          this.resultType = 'error';
          return;
        }
        if (data.status === 'completed') {
          this.stopPolling();
          this.processing = false;
          this.progress = 100;
          this.progressMsg = this.$t('textReplace.progressCompleted');
          this.resultMsg = this.$t('textReplace.runCompleted');
          this.resultType = 'success';
        }
      } catch (e) {
        // 网络抖动时忽略，继续轮询
      }
    },
    async startPreview() {
      if (!this.pattern || this.processing) return;
      this.previewing = true;
      this.previewResult = null;
      this.previewError = '';
      this.resultMsg = '';
      try {
        const rsp = await this.$backend('/toolbox/text_replace/preview', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            book_id: this.selected.id,
            pattern: this.pattern,
            replacement: this.replacement,
            use_regex: this.useRegex,
            format: this.selectedFormat,
          }),
        });
        if (rsp.err === 'ok') {
          this.previewResult = rsp.data || {};
          this.previewError = rsp.data && rsp.data.regex_error ? rsp.data.regex_error : '';
        } else {
          this.previewError = rsp.msg || rsp.err;
        }
      } catch (e) {
        this.previewError = String(e);
      } finally {
        this.previewing = false;
      }
    },
    async startRun() {
      if (!this.pattern || this.processing) return;
      this.resultMsg = '';
      this.processing = true;
      this.progress = 0;
      this.progressMsg = '';
      try {
        const rsp = await this.$backend('/toolbox/text_replace/run', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            book_id: this.selected.id,
            pattern: this.pattern,
            replacement: this.replacement,
            use_regex: this.useRegex,
            suffix: this.suffix || this.$t('textReplace.defaultSuffix'),
            format: this.selectedFormat,
          }),
        });
        if (rsp.err === 'ok') {
          this.resultMsg = rsp.msg || this.$t('textReplace.runStarted');
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
