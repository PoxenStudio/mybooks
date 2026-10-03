<template>
  <v-container fluid class="pa-4">
    <!-- Page header -->
    <v-row class="mb-3" align="center">
      <v-col class="text-center">
        <span class="text-h5 font-weight-bold">{{ $t('chineseConverter.title') }}</span>
      </v-col>
      <v-col cols="auto">
        <v-btn small color="error" @click="$router.go(-1)">
          <v-icon small left>mdi-close</v-icon>{{ $t('chineseConverter.close') }}
        </v-btn>
      </v-col>
    </v-row>

    <!-- Main card -->
    <v-row justify="center">
      <v-col cols="12" md="8" lg="6">
        <v-card rounded="xl" outlined class="cc-card pa-6">
          <!-- Hint -->
          <v-alert type="info" dense text rounded="lg" class="mb-5">
            {{ $t('chineseConverter.hint') }}
          </v-alert>

          <!-- Search field -->
          <v-text-field
            v-model="query"
            :label="$t('chineseConverter.selectBook')"
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
          <div class="cc-book-list mb-4">
            <div v-if="searching" class="text-center py-6">
              <v-progress-circular indeterminate color="primary" size="32" />
            </div>
            <div v-else-if="books.length === 0 && searched" class="text-center py-4 grey--text">
              {{ $t('chineseConverter.noResults') }}
            </div>
            <v-list v-else-if="books.length > 0" dense class="cc-list pa-0">
              <v-list-item
                v-for="book in books"
                :key="book.id"
                :class="['cc-book-item', { 'cc-book-selected': selected && selected.id === book.id }]"
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
                  <v-list-item-title class="cc-book-title">{{ book.title }}</v-list-item-title>
                  <v-list-item-subtitle class="cc-book-author">{{ (book.authors || []).join(', ') }}</v-list-item-subtitle>
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

            <!-- Direction -->
            <v-select
              v-model="direction"
              :label="$t('chineseConverter.direction')"
              :items="directionOptions"
              item-text="label"
              item-value="value"
              outlined
              dense
              hide-details
              class="mb-4"
              prepend-inner-icon="mdi-swap-horizontal"
              @change="onDirectionChange"
            />

            <!-- Options -->
            <v-switch
              v-model="useA5"
              :label="$t('chineseConverter.useA5')"
              :disabled="!a5Enabled"
              :hint="a5Enabled ? $t('chineseConverter.useA5Hint') : $t('chineseConverter.useA5DisabledHint')"
              persistent-hint
              color="primary"
              class="mt-0"
            />

            <v-switch
              v-model="convertTitle"
              :label="$t('chineseConverter.convertTitle')"
              :hint="$t('chineseConverter.convertTitleHint')"
              persistent-hint
              color="primary"
              class="mt-0"
            />

            <!-- Output mode -->
            <v-radio-group v-model="mode" dense row class="mt-1 mb-1">
              <v-radio :label="$t('chineseConverter.modeBook')" value="book" />
              <v-radio :label="$t('chineseConverter.modeReplace')" value="replace" />
            </v-radio-group>

            <v-switch
              v-if="mode === 'replace'"
              v-model="backup"
              :label="$t('chineseConverter.backup')"
              :hint="$t('chineseConverter.backupHint')"
              persistent-hint
              color="primary"
              class="mt-0"
            />

            <!-- Start button -->
            <v-btn
              block
              large
              color="primary"
              class="mt-2"
              :loading="processing"
              :disabled="!canConvert"
              @click="startConvert"
            >
              <v-icon left>mdi-translate</v-icon>{{ $t('chineseConverter.startBtn') }}
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

    direction: 't2s',
    useA5: true,
    convertTitle: true,
    mode: 'book',
    backup: false,

    processing: false,
    progress: 0,
    progressMsg: '',
    resultMsg: '',
    resultType: 'success',
    pollTimer: null,
    // 轮询护栏：连续未取到状态次数（not_found / 网络异常共享计数）与启动时刻
    pollRetries: 0,
    pollStartedAt: 0,
  }),
  computed: {
    directionOptions() {
      return [
        { value: 't2s', label: this.$t('chineseConverter.dirT2S') },
        { value: 'tw2s', label: this.$t('chineseConverter.dirTW2S') },
        { value: 'tw2sp', label: this.$t('chineseConverter.dirTW2SP') },
        { value: 's2t', label: this.$t('chineseConverter.dirS2T') },
        { value: 's2tw', label: this.$t('chineseConverter.dirS2TW') },
        { value: 's2twp', label: this.$t('chineseConverter.dirS2TWP') },
        { value: 't2tw', label: this.$t('chineseConverter.dirT2TW') },
        { value: 'tw2t', label: this.$t('chineseConverter.dirTW2T') },
      ];
    },
    canConvert() {
      return (
        this.selected &&
        (this.selected.files || []).some((f) => ['EPUB', 'TXT'].indexOf(f.format) >= 0)
      );
    },
    // 增强词表仅对繁体→简体方向生效
    a5Enabled() {
      return ['t2s', 'tw2s'].indexOf(this.direction) >= 0;
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
      this.resultMsg = '';
    },
    onDirectionChange() {
      this.resultMsg = '';
    },
    startPolling() {
      this.stopPolling();
      this.pollRetries = 0;
      this.pollStartedAt = Date.now();
      this.pollTimer = setInterval(this.pollProgress, 2000);
    },
    // 护栏终止：结束轮询并给出提示，避免永远不动的进度条。
    // 任务本身仍在后台线程执行，完成后会有右上角消息通知。
    stopPollingWithError(msgKey) {
      this.stopPolling();
      this.processing = false;
      this.resultMsg = this.$t(msgKey);
      this.resultType = 'error';
    },
    stopPolling() {
      if (this.pollTimer) {
        clearInterval(this.pollTimer);
        this.pollTimer = null;
      }
    },
    stageText(stage) {
      const map = {
        reading: this.$t('chineseConverter.progressReading'),
        converting: this.$t('chineseConverter.progressConverting'),
        saving: this.$t('chineseConverter.progressSaving'),
        packing: this.$t('chineseConverter.progressSaving'),
      };
      return map[stage] || '';
    },
    async pollProgress() {
      // 总时长兜底（约 60 分钟）：防止任务异常时前端无限轮询
      if (Date.now() - this.pollStartedAt > 60 * 60 * 1000) {
        this.stopPollingWithError('chineseConverter.pollTimeout');
        return;
      }
      try {
        const rsp = await this.$backend('/toolbox/chinese_converter/progress');
        if (rsp.err === 'task.not_found') {
          // 任务尚未创建，短时等待；未取到状态累计约 30s 视为任务丢失
          this.pollRetries += 1;
          if (this.pollRetries > 15) {
            this.stopPollingWithError('chineseConverter.pollLost');
          }
          return;
        }
        this.pollRetries = 0;
        const data = rsp.data || {};
        this.progress = data.progress || 0;
        this.progressMsg = this.stageText(data.stage);

        if (rsp.err === 'task.failed') {
          this.stopPolling();
          this.processing = false;
          this.resultMsg = rsp.msg || this.$t('chineseConverter.convertFailed');
          this.resultType = 'error';
          return;
        }
        if (data.status === 'completed') {
          this.stopPolling();
          this.processing = false;
          this.progress = 100;
          this.progressMsg = this.$t('chineseConverter.stageCompleted');
          this.resultMsg = this.$t('chineseConverter.convertCompleted');
          this.resultType = 'success';
        }
      } catch (e) {
        // 网络抖动时忽略，继续轮询；连续多次失败（约 1 分钟）才终止
        this.pollRetries += 1;
        if (this.pollRetries > 30) {
          this.stopPollingWithError('chineseConverter.pollTimeout');
        }
      }
    },
    async startConvert() {
      if (!this.canConvert || this.processing) return;
      this.resultMsg = '';
      this.processing = true;
      this.progress = 0;
      this.progressMsg = '';
      try {
        const rsp = await this.$backend('/toolbox/chinese_converter/convert', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            book_id: this.selected.id,
            direction: this.direction,
            mode: this.mode,
            use_a5: this.useA5,
            convert_title: this.convertTitle,
            backup: this.backup,
          }),
        });
        if (rsp.err === 'ok') {
          this.resultMsg = rsp.msg || this.$t('chineseConverter.convertStarted');
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
