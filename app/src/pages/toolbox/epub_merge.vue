<template>
  <!-- EPUB合集：库内多选 + 拖动排序 + 合集元数据确认 + 合并入库 -->
  <!-- 风格拼装：选书行=merge_formats_tool.vue，卡片/结果=epub_split.vue，
       combobox=book/_bid/edit.vue，拖拽=index.vue + HomeSectionCard.vue -->
  <v-container fluid class="pa-4">
    <!-- Page header -->
    <v-row class="mb-3" align="center">
      <v-col class="text-center">
        <span class="text-h5 font-weight-bold">{{ $t('epubMerge.title') }}</span>
      </v-col>
      <v-col cols="auto">
        <v-btn small color="error" @click="$router.go(-1)">
          <v-icon small left>mdi-close</v-icon>{{ $t('epubMerge.close') }}
        </v-btn>
      </v-col>
    </v-row>

    <v-row justify="center">
      <v-col cols="12" md="10" lg="8">
        <v-card rounded="xl" outlined class="pa-6" style="border: 2px solid #90CAF9;">
          <v-alert type="info" dense text rounded="lg" class="mb-5">
            {{ $t('epubMerge.hint') }}
          </v-alert>

          <!-- Search -->
          <v-text-field
            v-model="query"
            :label="$t('epubMerge.searchPlaceholder')"
            :loading="searching"
            outlined
            dense
            clearable
            hide-details
            class="mb-3"
            prepend-inner-icon="mdi-magnify"
            @keydown.enter.prevent="onEnterSearch"
            @click:clear="clearSearch"
          />
          <div class="em-book-list mb-4">
            <div v-if="searching" class="text-center py-6">
              <v-progress-circular indeterminate color="primary" size="32" />
            </div>
            <div v-else-if="books.length === 0 && searched" class="text-center py-4 grey--text">
              {{ $t('epubMerge.noResults') }}
            </div>
            <v-list v-else-if="books.length > 0" dense class="pa-0" style="background: transparent;">
              <v-list-item
                v-for="book in books"
                :key="book.id"
                class="em-book-item"
              >
                <v-list-item-avatar tile size="44" class="mr-3">
                  <v-img :src="book.thumb" :alt="book.title">
                    <template #error>
                      <v-icon color="grey lighten-1">mdi-book-outline</v-icon>
                    </template>
                  </v-img>
                </v-list-item-avatar>
                <v-list-item-content>
                  <v-list-item-title class="em-book-title">{{ book.title }}</v-list-item-title>
                  <v-list-item-subtitle class="em-book-author">{{ (book.authors || []).join(', ') }}</v-list-item-subtitle>
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
                <v-list-item-action>
                  <v-btn
                    x-small
                    color="primary"
                    :disabled="isSelected(book.id) || !hasEpub(book)"
                    @click="addBook(book)"
                  >
                    <v-icon x-small left>mdi-plus</v-icon>{{ $t('epubMerge.addBtn') }}
                  </v-btn>
                </v-list-item-action>
              </v-list-item>
            </v-list>
          </div>

          <!-- Selected (sortable) -->
          <template v-if="selected.length > 0">
            <div class="mb-1 d-flex justify-space-between align-center">
              <span class="text-subtitle-2 font-weight-bold">
                {{ $t('epubMerge.selectedTitle') }} ({{ selected.length }})
              </span>
              <v-btn x-small text color="primary" @click="clearSelected">
                <v-icon x-small left>mdi-broom</v-icon>{{ $t('epubMerge.clearSelection') }}
              </v-btn>
            </div>
            <div class="em-selected-list mb-4">
              <div
                v-for="(book, index) in selected"
                :key="book.id"
                draggable="true"
                :class="['em-selected-item', { 'em-drag-over': dragOverId === book.id }]"
                @dragstart="onDragStart(book, $event)"
                @dragover.prevent="onDragOver(book)"
                @dragleave="onDragLeave(book)"
                @drop.prevent="onDrop(book)"
                @dragend="onDragEnd"
              >
                <v-icon class="mr-2 em-drag-handle" :title="$t('epubMerge.orderHint')">mdi-drag</v-icon>
                <span class="em-order-num mr-2">{{ index + 1 }}</span>
                <v-list-item-avatar tile size="36" class="mr-2">
                  <v-img :src="book.thumb" :alt="book.title">
                    <template #error>
                      <v-icon color="grey lighten-1">mdi-book-outline</v-icon>
                    </template>
                  </v-img>
                </v-list-item-avatar>
                <div class="em-selected-title">{{ book.title }}</div>
                <v-spacer />
                <v-btn icon x-small :disabled="index === 0" :title="$t('epubMerge.moveTop')" @click="moveTop(index)">
                  <v-icon x-small>mdi-chevron-double-up</v-icon>
                </v-btn>
                <v-btn icon x-small :disabled="index === 0" :title="$t('epubMerge.moveUp')" @click="moveUp(index)">
                  <v-icon x-small>mdi-chevron-up</v-icon>
                </v-btn>
                <v-btn icon x-small :disabled="index === selected.length - 1" :title="$t('epubMerge.moveDown')" @click="moveDown(index)">
                  <v-icon x-small>mdi-chevron-down</v-icon>
                </v-btn>
                <v-btn icon x-small :disabled="index === selected.length - 1" :title="$t('epubMerge.moveBottom')" @click="moveBottom(index)">
                  <v-icon x-small>mdi-chevron-double-down</v-icon>
                </v-btn>
                <v-btn icon x-small :title="$t('epubMerge.remove')" @click="removeBook(index)">
                  <v-icon x-small>mdi-close</v-icon>
                </v-btn>
              </div>
            </div>
          </template>

          <!-- Preview / config -->
          <template v-if="selected.length >= 2">
            <div v-if="previewLoading" class="text-center py-6">
              <v-progress-circular indeterminate color="primary" size="32" />
              <div class="mt-2 grey--text text-caption">{{ $t('epubMerge.previewLoading') }}</div>
            </div>
            <template v-else-if="preview">
              <v-alert
                v-if="errorBooks.length > 0"
                type="error"
                dense
                text
                rounded="lg"
                class="mb-4"
              >
                <div v-for="b in errorBooks" :key="b.book_id">{{ b.title || ('ID:' + b.book_id) }}：{{ b.error }}</div>
              </v-alert>
              <v-alert
                v-if="allWarnings.length > 0"
                type="warning"
                dense
                text
                rounded="lg"
                class="mb-4"
              >
                <div v-for="(w, i) in allWarnings" :key="i">{{ w }}</div>
              </v-alert>

              <v-text-field
                v-model="form.title"
                :label="$t('epubMerge.titleLabel')"
                outlined
                dense
                maxlength="100"
                counter="100"
                class="mb-1"
                @input="dirty.title = true"
              />
              <div class="mb-3">
                <div class="text-caption grey--text mb-1">{{ $t('epubMerge.authorsLabel') }}</div>
                <v-chip v-for="a in form.authors" :key="a" small label class="mr-1 mb-1">{{ a }}</v-chip>
              </div>

              <v-combobox
                v-model="form.isbns"
                :label="$t('epubMerge.isbnsLabel')"
                :hint="$t('epubMerge.isbnsHint')"
                persistent-hint
                hide-selected
                multiple
                small-chips
                outlined
                dense
                class="mb-1"
                @input="dirty.isbns = true"
              >
                <template v-slot:selection="{ attrs, item, parent, selected }">
                  <v-chip v-bind="attrs" :input-value="selected" label small>
                    <span class="pr-2">{{ item }}</span>
                    <v-icon small @click="parent.selectItem(item)">mdi-close</v-icon>
                  </v-chip>
                </template>
              </v-combobox>

              <v-combobox
                v-model="form.tags"
                :items="tagNames"
                :label="$t('epubMerge.tagsLabel')"
                :search-input.sync="tagInput"
                :loading="tagsLoading"
                :filter="tagFilter"
                hide-selected
                multiple
                small-chips
                outlined
                dense
                class="mb-1"
                @input="dirty.tags = true"
              >
                <template v-slot:no-data>
                  <v-list-item v-if="tagInput">
                    <span class="subheading mr-2">{{ $t('epubMerge.addNew') }}</span>
                    <v-chip color="green lighten-3" label small rounded>{{ tagInput }}</v-chip>
                  </v-list-item>
                </template>
                <template v-slot:selection="{ attrs, item, parent, selected }">
                  <v-chip v-bind="attrs" color="green lighten-3" :input-value="selected" label small>
                    <span class="pr-2">{{ item }}</span>
                    <v-icon small @click="parent.selectItem(item)">mdi-close</v-icon>
                  </v-chip>
                </template>
              </v-combobox>

              <v-row dense>
                <v-col cols="12" sm="6">
                  <v-combobox
                    v-model="form.publisher"
                    :items="publisherNames"
                    :label="$t('epubMerge.publisherLabel')"
                    :search-input.sync="publisherInput"
                    :loading="publishersLoading"
                    :filter="tagFilter"
                    clearable
                    hide-no-data
                    outlined
                    dense
                    @input="dirty.publisher = true"
                  />
                </v-col>
                <v-col cols="12" sm="6">
                  <v-select
                    v-model="form.language"
                    :items="languageOptions"
                    item-text="name"
                    item-value="code"
                    :label="$t('epubMerge.languageLabel')"
                    :menu-props="{ maxHeight: '300px' }"
                    clearable
                    outlined
                    dense
                    @change="dirty.language = true"
                  />
                </v-col>
              </v-row>

              <div class="text-caption grey--text mb-1">{{ $t('epubMerge.coverLabel') }}</div>
              <v-radio-group v-model="coverType" dense class="mt-0 mb-1">
                <v-radio value="first" :label="$t('epubMerge.coverFirst')" />
                <v-radio
                  v-for="book in selected"
                  :key="book.id"
                  :value="'book:' + book.id"
                  :label="book.title"
                />
                <!-- value 带 token：与 coverType 精确匹配才能显示选中态 -->
                <v-radio
                  :value="'upload:' + coverToken"
                  :label="$t('epubMerge.coverUpload')"
                  :disabled="!coverToken"
                />
              </v-radio-group>
              <v-row dense align="center" class="mb-3">
                <v-col cols="12" sm="8">
                  <v-file-input
                    v-model="coverFile"
                    accept="image/jpeg,image/png,image/webp"
                    :label="$t('epubMerge.coverUpload')"
                    outlined
                    dense
                    hide-details
                    prepend-icon=""
                    prepend-inner-icon="mdi-image"
                  />
                </v-col>
                <v-col cols="12" sm="4">
                  <v-btn small color="primary" :loading="coverUploading" :disabled="!coverFile" block @click="uploadCover">
                    {{ $t('epubMerge.coverUploadBtn') }}
                  </v-btn>
                </v-col>
              </v-row>
              <div v-if="coverPreviewUrl" class="mb-3 text-center">
                <img :src="coverPreviewUrl" alt="cover" style="max-height: 160px; border-radius: 8px;" />
                <div class="text-caption grey--text">{{ $t('epubMerge.coverUploaded') }}</div>
              </div>

              <v-row dense class="mb-1">
                <v-col cols="12" sm="6">
                  <v-checkbox
                    v-model="form.divider"
                    :label="$t('epubMerge.dividerLabel')"
                    dense
                    hide-details
                  />
                </v-col>
                <v-col cols="12" sm="6">
                  <v-checkbox
                    v-model="form.deleteSource"
                    :label="$t('epubMerge.deleteSourceLabel')"
                    :hint="$t('epubMerge.deleteSourceHint')"
                    persistent-hint
                    dense
                  />
                </v-col>
              </v-row>

              <v-textarea
                v-model="form.description"
                :label="$t('epubMerge.descriptionLabel')"
                outlined
                dense
                rows="8"
                counter="50000"
                class="mt-2 mb-1"
                @input="dirty.description = true"
              />
              <v-alert
                v-if="preview && preview.truncated"
                type="warning"
                dense
                text
                rounded="lg"
                class="mb-2"
              >
                {{ $t('epubMerge.descTruncated') }}
              </v-alert>
              <div class="d-flex justify-end mb-4">
                <v-btn x-small text color="primary" @click="restoreDescription">
                  <v-icon x-small left>mdi-restore</v-icon>{{ $t('epubMerge.restoreDefault') }}
                </v-btn>
              </div>

              <transition name="em-fade">
                <v-alert v-if="errorMsg" type="error" dense text rounded="lg" class="mb-4">{{ errorMsg }}</v-alert>
              </transition>

              <div v-if="merging" class="mb-4">
                <div class="mb-1 d-flex justify-space-between text-caption">
                  <span>{{ mergeStage ? stageText(mergeStage) : $t('epubMerge.merging') }}</span>
                  <span>{{ progress }}%</span>
                </div>
                <v-progress-linear v-model="progress" height="10" rounded />
              </div>

              <v-btn
                block
                large
                color="primary"
                :loading="merging"
                :disabled="!canMerge || merging"
                @click="startMerge"
              >
                <v-icon left>mdi-book-plus-multiple</v-icon>
                {{ $t('epubMerge.mergeBtn') }}
              </v-btn>

              <transition name="em-fade">
                <div v-if="resultBook" class="text-center mt-4">
                  <v-alert type="success" dense text rounded="lg">
                    {{ $t('epubMerge.mergeSuccess') }}
                    <a :href="'/book/' + resultBook.book_id" target="_blank" class="font-weight-bold">{{ resultBook.title }}</a>
                  </v-alert>
                </div>
              </transition>
            </template>
            <v-alert
              v-else-if="previewError"
              type="error"
              dense
              text
              rounded="lg"
              class="mb-4"
            >{{ previewError }}</v-alert>
          </template>
          <div v-else-if="selected.length === 1" class="text-center py-4 grey--text text-caption">
            {{ $t('epubMerge.needTwoBooks') }}
          </div>
        </v-card>
      </v-col>
    </v-row>
  </v-container>
</template>

<script>
import { languageOptions } from '~/utils/languageCodes';

export default {
  data: () => ({
    query: '',
    books: [],
    searching: false,
    searched: false,
    selected: [],

    dragId: null,
    dragOverId: null,

    preview: null,
    previewLoading: false,
    previewError: '',
    previewSeq: 0,
    previewTimer: null,
    // 选书顺序变化后、新预览返回前为 true：期间禁止合并，避免用旧顺序的
    // 默认标题/简介按新顺序入库（防抖窗口内 previewLoading 仍为 false）
    previewPending: false,

    form: {
      title: '',
      authors: [],
      isbns: [],
      tags: [],
      publisher: '',
      language: '',
      divider: true,
      deleteSource: false,
      description: '',
    },
    dirty: {
      title: false, isbns: false, tags: false,
      publisher: false, language: false, description: false,
    },

    tagInput: null,
    tagsList: [],
    tagsLoading: false,
    publisherInput: null,
    publishers: [],
    publishersLoading: false,
    languageOptions,

    coverType: 'first',
    coverFile: null,
    coverToken: '',
    coverPreviewUrl: '',
    coverUploading: false,

    merging: false,
    progress: 0,
    mergeStage: '',
    errorMsg: '',
    resultBook: null,
    pollInterval: null,
  }),
  computed: {
    errorBooks() {
      if (!this.preview) return [];
      return (this.preview.books || []).filter((b) => b.error);
    },
    allWarnings() {
      if (!this.preview) return [];
      const out = [];
      (this.preview.books || []).forEach((b) => {
        (b.warnings || []).forEach((w) => out.push(`${b.title || ''}：${w}`));
      });
      return out;
    },
    tagNames() {
      return this.tagsList.map((t) => t.name);
    },
    publisherNames() {
      return this.publishers.map((p) => p.name);
    },
    canMerge() {
      // authors 为空时服务端兜底「佚名」，前端不再拦截造成无法合并的死局；
      // previewPending 覆盖防抖窗口、previewLoading 覆盖请求窗口，
      // 两者为真时 preview 与当前顺序不一致，禁止提交
      return this.preview
        && !this.previewPending
        && !this.previewLoading
        && this.errorBooks.length === 0
        && this.form.title.trim() !== '';
    },
  },
  created() {
    this.$store.commit('navbar', true);
    this.loadCandidates();
  },
  beforeDestroy() {
    if (this.pollInterval) { clearInterval(this.pollInterval); this.pollInterval = null; }
    if (this.previewTimer) { clearTimeout(this.previewTimer); this.previewTimer = null; }
    if (this.coverPreviewUrl) { URL.revokeObjectURL(this.coverPreviewUrl); this.coverPreviewUrl = ''; }
  },
  watch: {
    selected: {
      deep: true,
      handler() {
        this.resultBook = null;
        this.errorMsg = '';
        if (this.previewTimer) { clearTimeout(this.previewTimer); this.previewTimer = null; }
        if (this.selected.length >= 2 && this.selected.length <= 20) {
          // 拖动排序会连续触发 deep watch，防抖到拖完再请求；
          // 防抖期间即置 pending，合并按钮立刻禁用
          this.previewPending = true;
          this.previewTimer = setTimeout(() => {
            this.previewTimer = null;
            this.loadPreview();
          }, 250);
        } else {
          this.preview = null;
          this.previewPending = false;
        }
      },
    },
  },
  methods: {
    onEnterSearch(e) {
      if (e && e.isComposing) return;
      this.search();
    },
    async search() {
      const q = (this.query || '').trim();
      if (!q) return;
      this.searching = true;
      this.searched = false;
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
      this.searched = false;
    },
    hasEpub(book) {
      return (book.files || []).some((f) => f.format === 'EPUB');
    },
    isSelected(id) {
      return this.selected.some((b) => b.id === id);
    },
    addBook(book) {
      if (this.isSelected(book.id) || !this.hasEpub(book) || this.selected.length >= 20) return;
      this.selected.push(book);
    },
    removeBook(index) {
      this.selected.splice(index, 1);
    },
    clearSelected() {
      this.selected = [];
      this.resetForm();
    },
    resetForm() {
      this.preview = null;
      this.previewError = '';
      this.previewPending = false;
      this.form = {
        title: '', authors: [], isbns: [], tags: [], publisher: '',
        language: '', divider: true, deleteSource: false, description: '',
      };
      this.dirty = { title: false, isbns: false, tags: false, publisher: false, language: false, description: false };
    },
    // 拖拽排序（抄首页 index.vue 模式：dragId/dragOverId + splice）
    onDragStart(book, event) {
      this.dragId = book.id;
      if (event && event.dataTransfer) {
        event.dataTransfer.effectAllowed = 'move';
        event.dataTransfer.setData('text/plain', String(book.id));
      }
    },
    onDragOver(book) {
      if (this.dragId && this.dragId !== book.id) {
        this.dragOverId = book.id;
      }
    },
    onDragLeave(book) {
      if (this.dragOverId === book.id) {
        this.dragOverId = null;
      }
    },
    onDrop(book) {
      const from = this.selected.findIndex((b) => b.id === this.dragId);
      const to = this.selected.findIndex((b) => b.id === book.id);
      if (from === -1 || to === -1 || from === to) {
        this.onDragEnd();
        return;
      }
      const order = this.selected.slice();
      const [moved] = order.splice(from, 1);
      order.splice(to, 0, moved);
      this.selected = order;
      this.onDragEnd();
    },
    onDragEnd() {
      this.dragId = null;
      this.dragOverId = null;
    },
    moveUp(index) {
      if (index <= 0) return;
      const order = this.selected.slice();
      [order[index - 1], order[index]] = [order[index], order[index - 1]];
      this.selected = order;
    },
    moveDown(index) {
      if (index >= this.selected.length - 1) return;
      const order = this.selected.slice();
      [order[index + 1], order[index]] = [order[index], order[index + 1]];
      this.selected = order;
    },
    moveTop(index) {
      const order = this.selected.slice();
      const [moved] = order.splice(index, 1);
      order.unshift(moved);
      this.selected = order;
    },
    moveBottom(index) {
      const order = this.selected.slice();
      const [moved] = order.splice(index, 1);
      order.push(moved);
      this.selected = order;
    },
    async loadCandidates() {
      this.tagsLoading = true;
      this.publishersLoading = true;
      try {
        const [tagRsp, pubRsp] = await Promise.all([
          this.$backend('/tag'),
          this.$backend('/publisher'),
        ]);
        if (tagRsp && tagRsp.items) this.tagsList = tagRsp.items.slice(0, 100);
        if (pubRsp && pubRsp.items) this.publishers = pubRsp.items.slice(0, 100);
      } catch (_e) {
        // ignore
      } finally {
        this.tagsLoading = false;
        this.publishersLoading = false;
      }
    },
    tagFilter(item, queryText) {
      return item.toLowerCase().includes(queryText.toLowerCase());
    },
    applyPreview(data) {
      this.preview = data;
      if (!this.dirty.title) this.form.title = data.default_title || '';
      this.form.authors = data.authors_union || [];
      if (!this.dirty.isbns) this.form.isbns = data.isbns_union || [];
      if (!this.dirty.tags) this.form.tags = data.tags_union || [];
      if (!this.dirty.publisher) this.form.publisher = data.publisher_default || '';
      if (!this.dirty.language) this.form.language = data.language_default || '';
      if (!this.dirty.description) this.form.description = data.description_default || '';
      if ((data.books || []).some((b) => !b.error) && this.coverType.startsWith('book:')) {
        const id = parseInt(this.coverType.split(':')[1], 10);
        if (!this.selected.some((b) => b.id === id)) this.coverType = 'first';
      }
    },
    async loadPreview() {
      // 递增序号丢弃过期响应：快速连续操作时后到的旧数据不得覆盖新数据
      const seq = ++this.previewSeq;
      this.previewLoading = true;
      this.previewError = '';
      try {
        const rsp = await this.$backend('/toolbox/epub_merge/preview', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ book_ids: this.selected.map((b) => b.id) }),
        });
        if (seq !== this.previewSeq) return;
        if (rsp.err === 'ok') {
          this.applyPreview(rsp.data);
        } else {
          this.preview = null;
          this.previewError = rsp.msg || rsp.err;
        }
      } catch (e) {
        if (seq !== this.previewSeq) return;
        this.preview = null;
        this.previewError = String(e);
      } finally {
        if (seq === this.previewSeq) {
          this.previewLoading = false;
          this.previewPending = false;
        }
      }
    },
    stageText(stage) {
      const map = {
        starting: this.$t('epubMerge.stageStarting'),
        loading: this.$t('epubMerge.stageLoading'),
        cover: this.$t('epubMerge.stageCover'),
        merging: this.$t('epubMerge.stageMerging'),
        validating: this.$t('epubMerge.stageValidating'),
        saving: this.$t('epubMerge.stageSaving'),
      };
      return map[stage] || this.$t('epubMerge.merging');
    },
    restoreDescription() {
      if (this.preview) {
        this.form.description = this.preview.description_default || '';
        this.dirty.description = false;
      }
    },
    async uploadCover() {
      if (!this.coverFile) return;
      this.coverUploading = true;
      try {
        const formData = new FormData();
        formData.append('file', this.coverFile);
        const response = await fetch('/api/toolbox/epub_merge/cover_upload', {
          method: 'POST',
          body: formData,
        });
        const rsp = await response.json();
        if (rsp.err === 'ok') {
          this.coverToken = rsp.data.token;
          this.coverType = `upload:${rsp.data.token}`;
          if (this.coverPreviewUrl) URL.revokeObjectURL(this.coverPreviewUrl);
          this.coverPreviewUrl = URL.createObjectURL(this.coverFile);
        } else {
          this.errorMsg = rsp.msg || rsp.err;
        }
      } catch (e) {
        this.errorMsg = String(e);
      } finally {
        this.coverUploading = false;
      }
    },
    async startMerge() {
      if (!this.canMerge) return;
      this.errorMsg = '';
      this.resultBook = null;
      this.merging = true;
      this.progress = 0;
      this.mergeStage = '';
      let cover = { type: 'first' };
      if (this.coverType.startsWith('upload:')) {
        cover = { type: this.coverType };
      } else if (this.coverType.startsWith('book:')) {
        cover = { type: this.coverType };
      }
      try {
        const rsp = await this.$backend('/toolbox/epub_merge/merge', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            book_ids: this.selected.map((b) => b.id),
            title: this.form.title.trim(),
            authors: this.form.authors,
            description: this.form.description,
            isbns: this.form.isbns,
            tags: this.form.tags,
            publisher: this.form.publisher,
            language: this.form.language,
            divider: this.form.divider,
            delete_source: this.form.deleteSource,
            cover,
          }),
        });
        if (rsp.err === 'ok') {
          this.pollProgress();
        } else {
          this.errorMsg = rsp.msg || rsp.err;
          this.merging = false;
        }
      } catch (e) {
        this.errorMsg = String(e);
        this.merging = false;
      }
    },
    pollProgress() {
      if (this.pollInterval) clearInterval(this.pollInterval);
      this.pollInterval = setInterval(async () => {
        try {
          const rsp = await this.$backend('/toolbox/epub_merge/progress');
          if (rsp.err === 'ok' && rsp.data) {
            this.progress = rsp.data.progress || 0;
            this.mergeStage = rsp.data.stage || '';
            if (rsp.data.status === 'completed') {
              clearInterval(this.pollInterval);
              this.pollInterval = null;
              this.merging = false;
              this.progress = 100;
              this.resultBook = rsp.data.new_book_id
                ? { book_id: rsp.data.new_book_id, title: this.form.title }
                : { book_id: '', title: this.form.title };
            }
          } else {
            clearInterval(this.pollInterval);
            this.pollInterval = null;
            this.merging = false;
            this.errorMsg = (rsp && (rsp.msg || rsp.err)) || 'failed';
          }
        } catch (e) {
          clearInterval(this.pollInterval);
          this.pollInterval = null;
          this.merging = false;
          this.errorMsg = String(e);
        }
      }, 2000);
    },
  },
};
</script>

<style scoped>
.em-book-list {
  max-height: 260px;
  overflow-y: auto;
}

.em-book-item {
  border-radius: 8px !important;
  margin-bottom: 4px;
}

.em-book-title {
  font-size: 13px !important;
  white-space: normal !important;
  line-height: 1.3;
}

.em-book-author {
  font-size: 11px !important;
}

.em-selected-list {
  max-height: 320px;
  overflow-y: auto;
  border: 1px solid rgba(0, 0, 0, 0.12);
  border-radius: 8px;
  padding: 4px;
}

.em-selected-item {
  display: flex;
  align-items: center;
  border-radius: 8px;
  padding: 6px 4px;
  transition: background 0.15s, border 0.15s;
  border: 1px solid transparent;
}

.em-selected-item:hover {
  background: rgba(144, 202, 249, 0.15);
}

.em-drag-over {
  background: rgba(144, 202, 249, 0.3) !important;
  border: 1px dashed #42a5f5;
}

.em-drag-handle {
  cursor: grab;
}

.em-order-num {
  min-width: 20px;
  text-align: center;
  font-weight: bold;
  color: #42a5f5;
}

.em-selected-title {
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.em-fade-enter-active,
.em-fade-leave-active {
  transition: opacity 0.3s, transform 0.25s;
}
.em-fade-enter,
.em-fade-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
</style>
