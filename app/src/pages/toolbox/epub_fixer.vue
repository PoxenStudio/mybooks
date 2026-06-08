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

    <!-- Main card -->
    <v-row justify="center">
      <v-col cols="12" md="8" lg="6">
        <v-card rounded="xl" outlined class="ef-card pa-6">
          <!-- Hint -->
          <v-alert type="warning" dense text rounded="lg" class="mb-5">
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
          <div class="ef-book-list mb-4">
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
                :class="['ef-book-item', { 'ef-book-selected': selected && selected.id === book.id }]"
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
                <v-list-item-action v-if="selected && selected.id === book.id">
                  <v-icon color="primary">mdi-check-circle</v-icon>
                </v-list-item-action>
              </v-list-item>
            </v-list>
          </div>

          <!-- Backup option -->
          <v-checkbox
            v-model="backup"
            :label="$t('epubFixer.backupLabel')"
            dense
            hide-details
            class="mt-0 mb-5"
          />

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
              :loading="processing"
              :disabled="processing || !canFix"
              @click="startFix"
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
    selected: null,

    backup: false,
    processing: false,
    resultMsg: '',
    resultType: 'success',
  }),
  computed: {
    canFix() {
      return (
        this.selected &&
        (this.selected.files || []).some((f) => f.format === 'EPUB')
      );
    },
  },
  created() {
    this.$store.commit('navbar', true);
  },
  methods: {
    async search() {
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
    async startFix() {
      if (!this.canFix) return;
      this.resultMsg = '';
      this.processing = true;
      try {
        const rsp = await this.$backend('/toolbox/epub_fixer/fix', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ book_id: this.selected.id, backup: this.backup }),
        });
        if (rsp.err === 'ok') {
          this.resultMsg = rsp.msg || this.$t('epubFixer.fixSuccess');
          this.resultType = 'success';
        } else {
          this.resultMsg = rsp.msg || rsp.err;
          this.resultType = 'error';
        }
      } catch (e) {
        this.resultMsg = String(e);
        this.resultType = 'error';
      } finally {
        this.processing = false;
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
