<template>
  <div>
    <v-row>
      <v-col cols=12 class="d-flex align-center">
        <h2>{{ pageDisplayTitle }}</h2>
        <template v-if="isSelectablePage">
          <v-btn icon :color="multiSelectMode ? 'primary' : undefined" class="ml-2"
                 :title="multiSelectMode ? $t('listBook.exitMultiSelect') : $t('listBook.multiSelect')"
                 @click="toggleMultiSelectMode">
            <v-icon>mdi-checkbox-multiple-marked-outline</v-icon>
          </v-btn>
          <v-btn v-if="multiSelectMode && selectedIds.length > 0" icon dark color="red" class="ml-1"
                 :title="$t('listBook.deleteSelected', { count: selectedIds.length })"
                 @click="confirmDialog = true">
            <v-icon>mdi-delete</v-icon>
          </v-btn>
        </template>
        <v-btn v-if="isVisitsPage && books.length > 0" icon class="ml-2"
               :title="$t('listBook.clearVisits')" @click="clearDialog = true">
          <v-icon>mdi-delete-sweep-outline</v-icon>
        </v-btn>
        <v-divider class="mt-3 mb-0"></v-divider>
      </v-col>

      <v-col>
        <book-cards :books="books" :isAudioPage="isAudioPage" :selectable="multiSelectMode"
                    :selectedIds="selectedIds" @toggle-select="toggleSelect">
          <template v-if="isVisitsPage" v-slot:introduce="{ book }">
            <div v-if="book.visit_time" class="caption grey--text">
              <v-icon x-small>mdi-clock-outline</v-icon> {{ formatVisitTime(book.visit_time) }}
            </div>
          </template>
        </book-cards>
      </v-col>

      <v-col cols=12>
        <v-container class="max-width">
          <v-pagination v-if="page_cnt > 0" v-model="page" :length="page_cnt" circle
                        @input="change_page"></v-pagination>
        </v-container>
        <div class="text-xs-center book-pager">
        </div>
      </v-col>
    </v-row>

    <AppDialog
      v-model="confirmDialog"
      :persistent="false"
      type="confirm"
      :title="$t('listBook.confirmRemoveTitle')"
      color="deep-orange"
      confirm-dark
      max-width="420"
      :dismiss-label="$t('listBook.cancel')"
      :confirm-text="$t('listBook.confirm')"
      :confirm-loading="removing"
      @confirm="removeSelected"
    >
      {{ confirmRemoveContent }}
    </AppDialog>

    <AppDialog
      v-model="clearDialog"
      :persistent="false"
      type="confirm"
      :title="$t('listBook.clearVisitsTitle')"
      color="deep-orange"
      confirm-dark
      max-width="420"
      :confirm-text="$t('listBook.confirm')"
      :confirm-loading="clearing"
      @confirm="clearVisits"
    >
      {{ $t('listBook.clearVisitsContent') }}
    </AppDialog>
  </div>
</template>

<script>
import BookCards from "../components/BookCards.vue";

const SELECTABLE_ACTIONS = {
  '/favorites': 'favorite',
  '/wants': 'wants',
  '/reading': 'reading',
  '/read-done': 'read-done',
};

export default {
  components: {
    BookCards,
  },
  computed: {
    page_size() {
      if (process.client) {
        const stored = localStorage.getItem('defaultPageSize');
        if (stored) {
          return parseInt(stored);
        }
      }
      return this.$store?.state?.default_page_size || 60;
    },
    pageDisplayTitle() {
      return this.getPageTitle();
    },
    isVisitsPage() {
      return this.$route.path === '/visits';
    },
    isSelectablePage() {
      return Object.prototype.hasOwnProperty.call(SELECTABLE_ACTIONS, this.$route.path);
    },
    confirmRemoveContent() {
      const action = SELECTABLE_ACTIONS[this.$route.path];
      const keys = {
        favorite: 'listBook.confirmRemoveContentFavorites',
        wants: 'listBook.confirmRemoveContentWants',
        reading: 'listBook.confirmRemoveContentReading',
        'read-done': 'listBook.confirmRemoveContentReadDone',
      };
      return this.$t(keys[action] || 'listBook.confirmRemoveContentFavorites', { count: this.selectedIds.length });
    },
  },
  data: () => ({
    title: "",
    page: 1,
    books: [],
    total: 0,
    page_cnt: 0,
    inited: false,
    isAudioPage: false,
    multiSelectMode: false,
    selectedIds: [],
    confirmDialog: false,
    removing: false,
    clearDialog: false,
    clearing: false,
  }),
  async asyncData({route, app, res}) {
    if (res !== undefined) {
      res.setHeader('Cache-Control', 'no-cache');
    }
    return app.$backend(route.fullPath);
  },
  head() {
    return {
      title: this.getPageTitle(),
    }
  },
  created() {
    if (this.$route.query.start != undefined) {
      this.page = 1 + parseInt(this.$route.query.start / this.page_size)
    }
    this.page_cnt = Math.max(1, Math.ceil(this.total / this.page_size))

    this.checkIfAudioPage();
  },

  beforeRouteUpdate(to, from, next) {
    this.init(to, next);
  },
  methods: {
    getPageTitle() {
      let displayTitle = "";

      switch (this.$route.path) {
        case "/hot":
          displayTitle = this.$t('listBook.hotBooks');
          break;

        case "/search":
          displayTitle = this.$t('listBook.search');
          break;

        case "/all":
          displayTitle = this.$t('listBook.allBooks');
          break;

        case "/favorites":
          displayTitle = this.$t('listBook.favoritesBooks');
          break;

        case "/visits":
          displayTitle = this.$t('listBook.visitsBooks');
          break;

        case "/wants":
          displayTitle = this.$t('listBook.wantsBooks');
          break;

        case "/reading":
          displayTitle = this.$t('listBook.readingBooks');
          break;

        case "/read-done":
          displayTitle = this.$t('listBook.readDoneBooks');
          break;

        case "/printbooks":
          displayTitle = this.$t('listBook.physicalBooks');
          break;

        case "/audiobooks":
          displayTitle = this.$t('listBook.audioBooks');
          break;

        case "/soledbooks":
          displayTitle = this.$t('listBook.soledBooks');
          break;

        default:
          if (this.$route.params.meta !== undefined) {
            var name = decodeURIComponent(this.$route.params.name);
            var titles = {
              tag: this.$t('listBook.tagBooks', { name }),
              series: this.$t('listBook.seriesBooks', { name }),
              rating: this.$t('listBook.ratingBooks', { name }),
              author: this.$t('listBook.authorBooks', { name }),
              publisher: this.$t('listBook.publisherBooks', { name }),
              favorites: this.$t('listBook.favoritesBooks', { name }),
              wants: this.$t('listBook.wantsBooks', { name }),
              reading: this.$t('listBook.readingBooks', { name }),
              readDone: this.$t('listBook.readDoneBooks', { name }),
            }
            var meta = this.$route.path.split("/")[1];
            if (titles[meta] !== undefined) {
              displayTitle = titles[meta];
            }
          }

          if (!displayTitle) {
            displayTitle = this.title;
          }
          break;
      }

      return displayTitle;
    },
    checkIfAudioPage() {
      this.isAudioPage = this.$route.path === '/audiobooks';
    },
    init(route, next) {
      this.inited = true;
      this.$store.commit('navbar', true);

      this.isAudioPage = route.path === '/audiobooks';

      this.$backend(route.fullPath)
        .then(rsp => {
          if (rsp.err != 'ok') {
            this.alert("error", rsp.msg);
            return;
          }
          this.title = rsp.title;
          this.books = rsp.books;
          this.total = rsp.total
          this.page_cnt = Math.max(1, Math.ceil(this.total / this.page_size));
        })
      if (next) next();
    },
    change_page() {
      var r = Object.assign({}, this.$route.query);
      if (this.page < 1) {
        this.page = 1
      }
      r.start = (this.page - 1) * this.page_size;
      r.size = this.page_size;
      this.$router.push({query: r});
    },
    toggleMultiSelectMode() {
      this.multiSelectMode = !this.multiSelectMode;
      if (!this.multiSelectMode) {
        this.selectedIds = [];
      }
    },
    toggleSelect(bookId) {
      const idx = this.selectedIds.indexOf(bookId);
      if (idx === -1) {
        this.selectedIds = [...this.selectedIds, bookId];
      } else {
        this.selectedIds = this.selectedIds.filter((id) => id !== bookId);
      }
    },
    formatVisitTime(value) {
      const date = new Date(value);
      return Number.isNaN(date.getTime()) ? '' : date.toLocaleString();
    },
    async clearVisits() {
      if (this.clearing) return;
      this.clearing = true;
      try {
        const rsp = await this.$backend('/visits/clear', { method: 'POST' });
        if (rsp.err === 'ok') {
          this.books = [];
          this.total = 0;
          this.page_cnt = 1;
          this.clearDialog = false;
          this.$alert('success', this.$t('listBook.clearVisitsSuccess'));
        } else {
          this.$alert('error', rsp.msg || this.$t('listBook.removeFailed'));
        }
      } catch (e) {
        this.$alert('error', this.$t('listBook.removeFailed'));
      } finally {
        this.clearing = false;
      }
    },
    async removeSelected() {
      if (this.removing || this.selectedIds.length === 0) return;
      const action = SELECTABLE_ACTIONS[this.$route.path];
      if (!action) return;
      this.removing = true;
      try {
        const rsp = await this.$backend('/books/batch-remove-state', {
          method: 'POST',
          body: JSON.stringify({ book_ids: this.selectedIds, action }),
        });
        if (rsp.err === 'ok') {
          const removedIds = new Set(this.selectedIds);
          this.books = this.books.filter((b) => !removedIds.has(b.id));
          this.total = Math.max(0, this.total - removedIds.size);
          this.page_cnt = Math.max(1, Math.ceil(this.total / this.page_size));
          this.$alert('success', this.$t('listBook.removeSuccess', { count: removedIds.size }));
          this.selectedIds = [];
          this.confirmDialog = false;
          this.multiSelectMode = false;
        } else {
          this.$alert('error', rsp.msg || this.$t('listBook.removeFailed'));
        }
      } catch (e) {
        this.$alert('error', this.$t('listBook.removeFailed'));
      } finally {
        this.removing = false;
      }
    },
  },
}
</script>

<style scoped>
.book-list-legend {
  margin-top: 6px;
  margin-bottom: 16px;
}

.book-pager {
  margin-top: 30px;
}
</style>
