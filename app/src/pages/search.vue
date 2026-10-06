<template>
  <div>
    <v-row>
      <v-col cols=12>
        <h2>{{ pageDisplayTitle }}</h2>
        <v-divider class="mt-3 mb-0"></v-divider>
      </v-col>

      <v-col cols="12" v-if="searching">
        <v-container class="text-center py-8">
          <v-progress-circular indeterminate color="primary" size="64"></v-progress-circular>
          <p class="mt-4 grey--text">{{ searchStatus }}</p>
        </v-container>
      </v-col>

      <v-col v-else>
        <book-cards :books="books" :isAudioPage="false"></book-cards>
      </v-col>

      <v-col cols="12" v-if="extendedSearching">
        <v-container class="text-center py-4">
          <v-progress-circular indeterminate color="primary" size="32"></v-progress-circular>
          <span class="ml-3 grey--text">{{ searchStatus }}</span>
        </v-container>
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
  </div>
</template>

<script>
import BookCards from "../components/BookCards.vue";

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
    max_search_size() {
      return 1000;
    },
    fetch_page_size() {
      return 200;
    }
  },
  data: () => ({
    title: "",
    pageDisplayTitle: "",
    page: 1,
    books: [],
    allBooks: [],
    total: 0,
    page_cnt: 0,
    inited: false,
    searching: false,
    extendedSearching: false,
    searchStatus: "",
    searchController: null,
    searchName: "", // 搜索关键词
    cachedSearchName: "", // 缓存的搜索关键词，用于判断是否需要重新查询
    resultTitle: "", // searchByTitle 返回结果中携带的标题，用于覆盖默认标题
  }),
  head() {
    let displayTitle = this.$t('listBook.search');
    if (this.searchName) {
      displayTitle = this.$t('listBook.search') + ': ' + this.searchName;
    }
    if (this.resultTitle) {
      displayTitle = this.resultTitle;
    }
    this.pageDisplayTitle = displayTitle;
    return {
      title: displayTitle,
    }
  },
  created() {
    if (this.$route.query.start != undefined) {
      this.page = 1 + parseInt(this.$route.query.start / this.page_size)
    }
  },
  mounted() {
    this.init();
  },
  beforeDestroy() {
    this.abortSearch();
  },
  beforeRouteUpdate(to, from, next) {
    // 先完成路由跳转，确保 this.$route 是最新的
    next();
    // 在下一个 tick 中执行查询，确保路由已经更新
    this.$nextTick(() => {
      this.init();
    });
  },
  methods: {
    abortSearch() {
      if (this.searchController) {
        this.searchController.abort();
        this.searchController = null;
        this.searching = false;
        this.extendedSearching = false;
      }
    },

    async init() {
      this.$store.commit('navbar', true);

      // 获取搜索关键词
      this.searchName = this.$route.query.name || "";

      if (!this.searchName) {
        this.abortSearch();
        this.books = [];
        this.allBooks = [];
        this.total = 0;
        this.page_cnt = 0;
        this.cachedSearchName = "";
        this.resultTitle = "";
        return;
      }

      // 如果搜索关键词变化了，清空缓存
      if (this.searchName !== this.cachedSearchName) {
        this.abortSearch();
        this.books = [];
        this.allBooks = [];
        this.total = 0;
        this.page_cnt = 0;
        this.cachedSearchName = this.searchName;
        this.resultTitle = "";
      }

      // 如果URL中有start参数且缓存有效，说明是翻页操作，直接从缓存的allBooks中获取数据
      const start = parseInt(this.$route.query.start || 0);
      if (start > 0 && this.allBooks.length > 0) {
        this.updateBooksFromCache(start);
        return;
      }

      // 如果缓存中已有数据且是当前搜索关键词的结果，直接使用缓存
      if (this.allBooks.length > 0 && this.searchName === this.cachedSearchName) {
        this.updateBooksFromCache(0);
        return;
      }

      // 否则进行完整的三步查询
      await this.performFullSearch();
    },

    async performFullSearch() {
      if (this.searchController) {
        this.searchController.abort();
      }
      const controller = new AbortController();
      this.searchController = controller;
      const signal = controller.signal;
      this.searching = true;
      this.books = [];
      this.allBooks = [];
      this.total = 0;
      this.page_cnt = 0;
      this.resultTitle = "";
      const seenIds = new Set();

      try {
        // 第一步：精确标题查询
        this.searchStatus = this.$t('listBook.searchingTitle');
        const titleResults = await this.searchByTitle(this.searchName, signal);
        if (signal.aborted) {
          return;
        }
        if (titleResults && titleResults.books) {
          titleResults.books.forEach(book => {
            if (!seenIds.has(book.id)) {
              this.allBooks.push(book);
              seenIds.add(book.id);
            }
          });
        }
        if (titleResults && titleResults.title) {
          this.resultTitle = titleResults.title;
        }

        // 第二步：分词查询
        this.searchStatus = this.$t('listBook.searchingSegmentation');
        const segResults = await this.searchBySegmentation(this.searchName, signal);
        if (signal.aborted) {
          return;
        }
        if (segResults && segResults.books) {
          segResults.books.forEach(book => {
            if (!seenIds.has(book.id)) {
              this.allBooks.push(book);
              seenIds.add(book.id);
            }
          });
        }

        // 标题和分词搜索完成后，立即渲染第一批结果
        this.searching = false;
        if (this.allBooks.length > 0) {
          this.updateBooksFromCache(0);
        }

        // 第三步：扩展查询（耗时较长，在后台继续执行）
        this.extendedSearching = true;
        this.searchStatus = this.$t('listBook.searchingExtended');
        const extResults = await this.searchExtended(this.searchName, signal);
        if (signal.aborted) {
          return;
        }
        if (extResults && extResults.books) {
          extResults.books.forEach(book => {
            if (!seenIds.has(book.id)) {
              this.allBooks.push(book);
              seenIds.add(book.id);
            }
          });

          // 扩展搜索完成后，再次更新显示
          this.updateBooksFromCache(0);
        }

        // 更新总数和页数
        this.total = this.allBooks.length;
        this.page_cnt = Math.max(1, Math.ceil(this.total / this.page_size));

      } catch (error) {
        console.error('Search failed:', error);
        if (this.allBooks.length === 0) {
          this.allBooks = [];
          this.total = 0;
          this.page_cnt = 0;
        }
      } finally {
        if (this.searchController === controller) {
          this.searching = false;
          this.extendedSearching = false;
          this.searchStatus = "";
        }
      }
    },

    updateBooksFromCache(start) {
      const end = start + this.page_size;
      this.books = this.allBooks.slice(start, end);
      this.total = this.allBooks.length;
      this.page_cnt = Math.max(1, Math.ceil(this.total / this.page_size));
    },

    async fetchAllPages(url, signal) {
      const pageSize = this.fetch_page_size;
      const first = await this.$backend(`${url}&start=0&size=${pageSize}`, {signal});
      if (first.err !== 'ok') {
        return first;
      }
      const books = first.books || [];
      const wanted = Math.min(first.total || books.length, this.max_search_size);
      while (books.length < wanted) {
        const rsp = await this.$backend(`${url}&start=${books.length}&size=${pageSize}`, {signal});
        if (rsp.err !== 'ok' || !rsp.books || rsp.books.length === 0) {
          break;
        }
        books.push(...rsp.books);
      }
      first.books = books;
      return first;
    },

    async searchByTitle(name, signal) {
      try {
        const url = `/search?title=${encodeURIComponent(name)}`;
        const rsp = await this.fetchAllPages(url, signal);
        if (rsp.err === 'ok') {
          return rsp;
        }
      } catch (error) {
        console.error('Title search failed:', error);
      }
      return null;
    },

    async searchBySegmentation(name, signal) {
      try {
        const url = `/search?seg=1&title=${encodeURIComponent(name)}`;
        const rsp = await this.fetchAllPages(url, signal);
        if (rsp.err === 'ok') {
          return rsp;
        }
      } catch (error) {
        console.error('Segmentation search failed:', error);
      }
      return null;
    },

    async searchExtended(name, signal) {
      try {
        const url = `/search?name=${encodeURIComponent(name)}`;
        const rsp = await this.fetchAllPages(url, signal);
        if (rsp.err === 'ok') {
          return rsp;
        }
      } catch (error) {
        console.error('Extended search failed:', error);
      }
      return null;
    },

    change_page() {
      if (this.page < 1) {
        this.page = 1;
      }
      const start = (this.page - 1) * this.page_size;

      // 从缓存中获取数据
      this.updateBooksFromCache(start);

      // 更新URL
      const query = Object.assign({}, this.$route.query);
      query.start = start;
      query.size = this.page_size;
      this.$router.push({query: query});
    }
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
