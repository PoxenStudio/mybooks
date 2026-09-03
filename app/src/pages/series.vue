<template>
  <div>
    <!-- Detail Mode: Books for specific series -->
    <div v-if="currentSeries">
      <v-row>
        <v-col cols="12">
          <h2>{{ $t('listBook.seriesBooks', { name: currentSeries }) }}</h2>
        </v-col>

        <!-- Batch Set Category Card -->
        <v-col cols="12">
          <v-card outlined class="mb-4">
            <v-card-title class="py-2" @click="showBatch = !showBatch">
              <v-btn icon>
                <v-icon>{{ showBatch ? 'mdi-chevron-up' : 'mdi-chevron-down' }}</v-icon>
              </v-btn>
              <span class="text-subtitle-1 font-weight-bold">{{ $t('listBook.batchSetCategory') }}</span>
            </v-card-title>

            <v-expand-transition>
              <div v-show="showBatch">
                <v-card-text>
                  <v-row align="center">
                    <v-col cols="12" sm="4">
                      <v-select
                        v-model="targetCategory"
                        :items="categories"
                        item-text="name"
                        item-value="name"
                        :label="$t('listBook.selectCategory')"
                        outlined
                        dense
                        hide-details
                      ></v-select>
                    </v-col>
                    <v-col cols="12" sm="6">
                      <v-btn
                        color="primary"
                        :disabled="!targetCategory"
                        @click="confirmBatchSet"
                        :loading="batchLoading"
                      >
                        {{ $t('listBook.batchSet') }}
                      </v-btn>
                    </v-col>
                  </v-row>
                  <div class="caption text-grey mt-2" v-if="targetCategory">
                    {{ $t('listBook.setCategoryForSeriesBooks', { category: targetCategory || '...', series: currentSeries }) }}
                  </div>
                </v-card-text>
              </div>
            </v-expand-transition>
          </v-card>
        </v-col>

        <!-- Book Cards -->
        <v-col cols="12">
          <book-cards :books="books"></book-cards>
        </v-col>

        <!-- Pagination -->
        <v-col cols="12">
           <v-container class="max-width">
            <v-pagination v-if="page_cnt > 0" v-model="page" :length="page_cnt" circle @input="change_page"></v-pagination>
          </v-container>
        </v-col>
      </v-row>
    </div>

    <!-- List Mode: All Series -->
    <div v-else>
       <v-row>
        <v-col>
          <v-chip
            class="ma-1"
            v-for="item in visibleMetaItems"
            :key="item.name"
            color="primary"
            @click="selectSeries(item.name)"
            style="cursor: pointer;"
          >
            {{ item.name }}
            <span v-if="item.count">&nbsp;({{ item.count }})</span>
          </v-chip>
           <v-btn v-if="items.length > 50 && !show_all" @click="expandList()" color="primary" rounded>
             {{ $t('listMeta.showAll') || 'Show All' }}
           </v-btn>
        </v-col>
      </v-row>
    </div>

    <!-- Confirmation Dialog -->
    <AppDialog
      v-model="dialog"
      :persistent="false"
      type="confirm"
      :title="$t('listBook.confirmBatchUpdate')"
      max-width="400"
      :confirm-text="$t('common.ok')"
      @confirm="doBatchSet"
    >
      <div v-html="$t('listBook.confirmBatchUpdateContentSeries', { category: targetCategory, series: currentSeries, total: total })"></div>
    </AppDialog>
  </div>
</template>

<script>
import BookCards from "../components/BookCards.vue";

export default {
  components: {
    BookCards,
  },
  data: () => ({
    // Shared / List State
    items: [],
    show_all: false,

    // Detail State
    currentSeries: null,
    books: [],
    page: 1,
    page_size: 60,
    total: 0,
    page_cnt: 0,
    isFetching: false,  // Prevent duplicate fetching

    // Batch Ops
    showBatch: false,
    categories: [],
    targetCategory: "",
    batchLoading: false,
    dialog: false,
  }),
  computed: {
    visibleMetaItems() {
      if (this.show_all) return this.items;
      return this.items.slice(0, 100); // Limit initial view
    },
    isLoggedIn() {
      return this.$store.state.user?.is_login === true;
    }
  },
  head() {
    if (this.currentSeries) {
        return { title: this.$t('listBook.seriesBooks', { name: this.currentSeries }) };
    }
    return { title: this.$t('listMeta.allSeries') };
  },
  async asyncData({ app, route, res }) {
    if (res !== undefined) {
        res.setHeader('Cache-Control', 'no-cache');
    }
    // Pre-load series list if no specific series selected
    let name = route.query.name || route.params.name;
    if (name) {
        name = decodeURIComponent(name);
    }
    if (!name) {
        let rsp = await app.$backend("/series");
        return { items: rsp.items || [], total: rsp.total };
    }
    return {};
  },
  created() {
    this.init();
    // Watch will handle the initial name param, no need to call selectSeries here
  },
  watch: {
    '$route.query.name': {
      handler(newName) {
        if (newName) {
          newName = decodeURIComponent(newName);
          this.selectSeries(newName);
        } else {
          let paramsName = this.$route.params.name;
          if (paramsName) {
            paramsName = decodeURIComponent(paramsName);
            this.selectSeries(paramsName);
          } else {
            this.clearSeries();
          }
        }
      },
      immediate: true
    },
    '$route.params.name': {
      handler(newName) {
        if (newName) {
          newName = decodeURIComponent(newName);
          this.selectSeries(newName);
        } else {
          let queryName = this.$route.query.name;
          if (queryName) {
            queryName = decodeURIComponent(queryName);
            this.selectSeries(queryName);
          } else {
            this.clearSeries();
          }
        }
      },
      immediate: true
    }
  },
  methods: {
    async init() {
        this.$store.commit('navbar', true);
        if (this.items.length === 0 && !this.currentSeries) {
            let rsp = await this.$backend("/series" + (this.show_all ? "?show=all" : ""));
            this.items = rsp.items;
        }
        this.loadCategories();
    },
    async loadCategories() {
        if (this.$store.state.user?.is_login !== true) {
            this.categories = [];
            return;
        }
        try {
            const response = await this.$backend('/admin/settings');
            if (response.err === 'ok' && response.settings) {
                if (response.settings.BOOK_NAV) {
                    this.categories = response.settings.BOOK_NAV.split('\n').map(line => {
                        const parts = line.split('=');
                        return parts[0].trim();
                    }).filter(c => c);
                }
            }
        } catch (error) {
            console.error('Failed to get settings:', error);
        }
    },
    async expandList() {
        this.show_all = true;
        let rsp = await this.$backend("/series?show=all");
        this.items = rsp.items;
    },
    selectSeries(name) {
        // Avoid duplicate calls if already showing this series and fetching or has data
        if (this.currentSeries === name && (this.isFetching || this.books.length > 0)) {
            return;
        }
        this.currentSeries = name;
        this.page = 1;
        // 如果当前路由有params.name，说明是通过/series/:name访问的，需要转换为query参数并清除params
        if (this.$route.params.name || this.$route.query.name !== name) {
            // 只使用query参数，不保留params，这样URL会更简洁
            // 对name参数进行encodeURIComponent处理，确保中文丛书名在URL中正确显示
            this.$router.push({ path: '/series', query: { ...this.$route.query, name: encodeURIComponent(name) } });
        }
        this.fetchBooks();
    },
    clearSeries() {
        this.currentSeries = null;
        this.books = [];
        this.$router.push({ query: { ...this.$route.query, name: undefined } });
        // Ensure list is loaded
        if (this.items.length === 0) {
            this.init();
        }
    },
    async fetchBooks() {
        if (!this.currentSeries) return;
        if (this.isFetching) {
            return;
        }
        this.isFetching = true;
        const start = (this.page - 1) * this.page_size;
        try {
            const rsp = await this.$backend(`/series/${encodeURIComponent(this.currentSeries)}?start=${start}&size=${this.page_size}`);
            if (rsp.err === 'ok') {
                this.books = rsp.books;
                this.total = rsp.total;
                this.page_cnt = Math.max(1, Math.ceil(this.total / this.page_size));
            }
        } catch (e) {
            this.$alert("error", "Failed to load books");
        } finally {
            this.isFetching = false;
        }
    },
    change_page() {
        this.fetchBooks();
        this.$vuetify.goTo(0);
    },
    confirmBatchSet() {
        this.dialog = true;
    },
    async doBatchSet() {
        this.dialog = false;
        this.batchLoading = true;
        try {
            const rsp = await this.$backend("/book/category", {
                method: "POST",
                body: JSON.stringify({
                    series: this.currentSeries,
                    category: this.targetCategory
                }),
                headers: {
                    'Content-Type': 'application/json'
                }
            });
            if (rsp.err === 'ok') {
                this.$alert("success", rsp.msg);
                this.fetchBooks();
            } else {
                this.$alert("error", rsp.msg);
            }
        } catch (e) {
            this.$alert("error", "Batch update failed");
        } finally {
            this.batchLoading = false;
        }
    },
  }
}
</script>
