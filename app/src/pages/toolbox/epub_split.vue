<template>
  <v-container fluid class="pa-4">
    <!-- Page header -->
    <v-row class="mb-3" align="center">
      <v-col class="text-center">
        <span class="text-h5 font-weight-bold">{{ $t('epubSplit.title') }}</span>
      </v-col>
      <v-col cols="auto">
        <v-btn small color="error" @click="$router.go(-1)">
          <v-icon small left>mdi-close</v-icon>{{ $t('epubSplit.close') }}
        </v-btn>
      </v-col>
    </v-row>

    <!-- Main card -->
    <v-row justify="center">
      <v-col cols="12" md="9" lg="7">
        <v-card rounded="xl" outlined class="es-card pa-6">
          <v-alert type="warning" dense text rounded="lg" class="mb-5">
            {{ $t('epubSplit.hint') }}
          </v-alert>

          <!-- Search field -->
          <v-text-field
            v-model="query"
            :label="$t('epubSplit.searchPlaceholder')"
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
          <div class="es-book-list mb-4">
            <div v-if="searching" class="text-center py-6">
              <v-progress-circular indeterminate color="primary" size="32" />
            </div>
            <div v-else-if="books.length === 0 && searched" class="text-center py-4 grey--text">
              {{ $t('epubSplit.noResults') }}
            </div>
            <v-list v-else-if="books.length > 0" dense class="es-list pa-0">
              <v-list-item
                v-for="book in books"
                :key="book.id"
                :class="['es-book-item', { 'es-book-selected': selected && selected.id === book.id }]"
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
                  <v-list-item-title class="es-book-title">{{ book.title }}</v-list-item-title>
                  <v-list-item-subtitle class="es-book-author">{{ (book.authors || []).join(', ') }}</v-list-item-subtitle>
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
                <v-list-item-action v-if="selected && selected.id === book.id">
                  <v-icon color="primary">mdi-check-circle</v-icon>
                </v-list-item-action>
              </v-list-item>
            </v-list>
          </div>

          <!-- Chapter list -->
          <template v-if="selected">
            <div v-if="chaptersLoading" class="text-center py-6">
              <v-progress-circular indeterminate color="primary" size="32" />
            </div>
            <template v-else-if="chapters.length > 0">
              <v-row align="center" class="mb-1" no-gutters>
                <v-col>
                  <span class="text-subtitle-2 font-weight-bold">
                    {{ $t('epubSplit.chaptersTitle') }} ({{ selectedChapters.length }}/{{ chapters.length }})
                  </span>
                </v-col>
                <v-col cols="auto">
                  <v-btn x-small text color="primary" :disabled="selectedChapters.length === 0" @click="clearChapterSelection">
                    <v-icon x-small left>mdi-broom</v-icon>{{ $t('epubSplit.clearSelection') }}
                  </v-btn>
                </v-col>
              </v-row>
              <div class="es-chapter-list mb-4">
                <v-checkbox
                  v-for="chapter in chapters"
                  :key="chapter.num"
                  v-model="selectedChapters"
                  :value="chapter.num"
                  :label="chapter.title"
                  :title="chapter.preview"
                  dense
                  hide-details
                  class="es-chapter-item"
                />
              </div>
            </template>
            <div v-else-if="chaptersErrorMsg" class="text-center py-4">
              <v-alert type="error" dense text rounded="lg">{{ chaptersErrorMsg }}</v-alert>
            </div>
          </template>

          <!-- Cover option -->
          <v-checkbox
            v-if="chapters.length > 0"
            v-model="useFirstChapterCover"
            :label="$t('epubSplit.useFirstChapterCoverLabel')"
            dense
            hide-details
            class="mt-0 mb-2"
          />

          <!-- Result message -->
          <transition name="es-fade">
            <v-alert v-if="errorMsg" type="error" dense text rounded="lg" class="mb-4">{{ errorMsg }}</v-alert>
          </transition>

          <!-- Generate button -->
          <div v-if="chapters.length > 0" class="d-flex justify-center">
            <v-btn
              color="primary"
              class="es-start-btn"
              :loading="processing"
              :disabled="processing || selectedChapters.length === 0"
              @click="generateBook"
            >
              <v-icon left>mdi-content-cut</v-icon>
              {{ $t('epubSplit.generateBtn') }}
            </v-btn>
          </div>

          <!-- Result -->
          <transition name="es-fade">
            <div v-if="resultBook" class="text-center mt-4">
              <v-alert type="success" dense text rounded="lg">
                {{ $t('epubSplit.generateSuccess') }}
                <a :href="'/book/' + resultBook.book_id" target="_blank" class="font-weight-bold">{{ resultBook.title }}</a>
              </v-alert>
            </div>
          </transition>
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

    chaptersLoading: false,
    chapters: [],
    selectedChapters: [],
    chaptersErrorMsg: '',

    useFirstChapterCover: false,
    processing: false,
    errorMsg: '',
    resultBook: null,
  }),
  created() {
    this.$store.commit('navbar', true);
  },
  methods: {
    async search() {
      const q = (this.query || '').trim();
      if (!q) return;
      this.searching = true;
      this.searched = false;
      this.resetSelection();
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
      this.resetSelection();
    },
    resetSelection() {
      this.selected = null;
      this.chapters = [];
      this.selectedChapters = [];
      this.chaptersErrorMsg = '';
      this.errorMsg = '';
      this.resultBook = null;
      this.useFirstChapterCover = false;
    },
    async selectBook(book) {
      if (this.selected && this.selected.id === book.id) {
        this.resetSelection();
        return;
      }
      this.resetSelection();
      this.selected = book;
      if (!(book.files || []).some((f) => f.format === 'EPUB')) {
        this.chaptersErrorMsg = this.$t('epubSplit.noEpub');
        return;
      }
      await this.loadChapters();
    },
    async loadChapters() {
      this.chaptersLoading = true;
      this.chaptersErrorMsg = '';
      try {
        const rsp = await this.$backend('/toolbox/epub_split/chapters', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ book_id: this.selected.id }),
        });
        if (rsp.err === 'ok') {
          this.chapters = (rsp.data && rsp.data.chapters) || [];
        } else {
          this.chaptersErrorMsg = rsp.msg || rsp.err;
        }
      } catch (e) {
        this.chaptersErrorMsg = String(e);
      } finally {
        this.chaptersLoading = false;
      }
    },
    clearChapterSelection() {
      this.selectedChapters = [];
    },
    async generateBook() {
      if (this.selectedChapters.length === 0) return;
      this.errorMsg = '';
      this.resultBook = null;
      this.processing = true;
      try {
        const rsp = await this.$backend('/toolbox/epub_split/generate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            book_id: this.selected.id,
            chapters: this.selectedChapters,
            use_first_chapter_cover: this.useFirstChapterCover,
          }),
        });
        if (rsp.err === 'ok') {
          this.resultBook = rsp.data;
        } else {
          this.errorMsg = rsp.msg || rsp.err;
        }
      } catch (e) {
        this.errorMsg = String(e);
      } finally {
        this.processing = false;
      }
    },
  },
};
</script>

<style scoped>
.es-card {
  border: 2px solid #90CAF9;
}

.es-book-list {
  max-height: 280px;
  overflow-y: auto;
}

.es-list {
  background: transparent !important;
}

.es-book-item {
  border-radius: 8px !important;
  margin-bottom: 4px;
  cursor: pointer;
  transition: background 0.15s;
}

.es-book-item:hover {
  background: rgba(144, 202, 249, 0.15) !important;
}

.es-book-selected {
  background: rgba(144, 202, 249, 0.25) !important;
  border: 1px solid #90CAF9;
}

.es-book-title {
  font-size: 13px !important;
  white-space: normal !important;
  line-height: 1.3;
}

.es-book-author {
  font-size: 11px !important;
}

.es-chapter-list {
  max-height: 320px;
  overflow-y: auto;
  border: 1px solid rgba(0, 0, 0, 0.12);
  border-radius: 8px;
  padding: 8px 12px;
}

.es-chapter-item {
  cursor: help;
}

.es-start-btn {
  width: 60%;
  min-width: 200px;
}

.es-fade-enter-active,
.es-fade-leave-active {
  transition: opacity 0.3s, transform 0.25s;
}
.es-fade-enter,
.es-fade-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
</style>
