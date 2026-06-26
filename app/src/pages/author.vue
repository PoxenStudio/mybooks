<template>
  <div>
    <!-- Detail Mode: Books for specific author -->
    <div v-if="currentAuthor">
      <v-row>
        <v-col cols="12">
          <h2>{{ $t('listBook.authorBooks', { name: currentAuthor }) }}</h2>
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
                    {{ $t('listBook.setCategoryForAuthorBooks', { category: targetCategory || '...', author: currentAuthor }) }}
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

    <!-- List Mode: All Authors -->
    <div v-else>
       <v-row>
        <v-col>
          <!-- Pinned Authors -->
          <div v-if="pins && pins.length > 0" class="mb-2">
            <v-chip
              class="ma-1"
              v-for="pin in pins"
              :key="'pin-' + pin.name"
              color="#01847F"
              @click="selectAuthor(pin.name)"
              style="cursor: pointer; color: white;"
            >
              {{ pin.name }}
              <span>&nbsp;({{ pin.count }})</span>
              <v-icon
                v-if="isLoggedIn"
                right
                @click.stop="unpinAuthor(pin.name)"
                class="ml-1"
              >
                mdi-pin-off-outline
              </v-icon>
            </v-chip>
          </div>

          <!-- Regular Authors -->
          <v-chip
            class="ma-1"
            v-for="item in visibleMetaItems"
            :key="item.name"
            color="primary"
            @click="selectAuthor(item.name)"
            style="cursor: pointer"
          >
            {{ item.name }}
            <span v-if="item.count">&nbsp;({{ item.count }})</span>
            <v-icon
              v-if="isLoggedIn"
              right
              @click.stop="pinAuthor(item.name)"
              class="ml-1"
            >
              mdi-pin-outline
            </v-icon>
          </v-chip>
           <v-btn v-if="items.length > 50 && !show_all" @click="expandList()" color="primary" rounded>
             {{ $t('listMeta.showAll') || 'Show All' }}
           </v-btn>
        </v-col>
      </v-row>
    </div>

    <!-- Confirmation Dialog -->
    <v-dialog v-model="dialog" max-width="400">
      <v-card>
        <v-card-title class="headline">{{ $t('listBook.confirmBatchUpdate') }}</v-card-title>
        <v-card-text v-html="$t('listBook.confirmBatchUpdateContentAuthor', { category: targetCategory, author: currentAuthor, total: total })"></v-card-text>
        <v-card-actions>
          <v-spacer></v-spacer>
          <v-btn color="grey darken-1" text @click="dialog = false">{{ $t('common.cancel') }}</v-btn>
          <v-btn color="primary" text @click="doBatchSet">{{ $t('common.ok') }}</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
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
    pins: [],
    show_all: false,

    // Detail State
    currentAuthor: null,
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
    if (this.currentAuthor) {
        return { title: this.$t('listBook.authorBooks', { name: this.currentAuthor }) };
    }
    return { title: this.$t('listMeta.allAuthors') };
  },
  async asyncData({ app, route, res }) {
    if (res !== undefined) {
        res.setHeader('Cache-Control', 'no-cache');
    }
    // Pre-load author list if no specific author selected
    let name = route.query.name;
    if (!name) {
        let rsp = await app.$backend("/author");
        return { items: rsp.items || [], pins: rsp.pins || [], total: rsp.total };
    }
    return {};
  },
  created() {
    console.log('[author.vue] created, route.query.name:', this.$route.query.name);
    this.init();
    // Watch will handle the initial name param, no need to call selectAuthor here
  },
  watch: {
    '$route.query.name': {
      handler(newName) {
        console.log('[author.vue] watch $route.query.name triggered, newName:', newName, ', currentAuthor:', this.currentAuthor);
        if (newName) {
          this.selectAuthor(newName);
        } else {
          this.clearAuthor();
        }
      },
      immediate: true  // Handle initial route query on mount
    }
  },
  methods: {
    async init() {
        console.log('[author.vue] init, currentAuthor:', this.currentAuthor, ', items.length:', this.items.length);
        this.$store.commit('navbar', true);
        if (this.items.length === 0 && !this.currentAuthor) {
            let rsp = await this.$backend("/author" + (this.show_all ? "?show=all" : ""));
            this.items = rsp.items;
            this.pins = rsp.pins || [];
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
        let rsp = await this.$backend("/author?show=all");
        this.items = rsp.items;
        this.pins = rsp.pins || [];
    },
    selectAuthor(name) {
        console.log('[author.vue] selectAuthor called, name:', name, ', currentAuthor:', this.currentAuthor, ', books.length:', this.books.length, ', isFetching:', this.isFetching);
        // Avoid duplicate calls if already showing this author and fetching or has data
        if (this.currentAuthor === name && (this.isFetching || this.books.length > 0)) {
            console.log('[author.vue] selectAuthor - skipping duplicate call');
            return;
        }
        this.currentAuthor = name;
        this.page = 1;
        // Update URL without navigation if needed, but better to use router push
        if (this.$route.query.name !== name) {
            console.log('[author.vue] selectAuthor - pushing route with name:', name);
            this.$router.push({ query: { ...this.$route.query, name: name } });
        }
        this.fetchBooks();
    },
    clearAuthor() {
        this.currentAuthor = null;
        this.books = [];
        this.$router.push({ query: { ...this.$route.query, name: undefined } });
        // Ensure list is loaded
        if (this.items.length === 0) {
            this.init();
        }
    },
    async fetchBooks() {
        if (!this.currentAuthor) return;
        if (this.isFetching) {
            console.log('[author.vue] fetchBooks - already fetching, skipping');
            return;
        }
        console.log('[author.vue] fetchBooks called, currentAuthor:', this.currentAuthor, ', page:', this.page);
        this.isFetching = true;
        const start = (this.page - 1) * this.page_size;
        // Use search API for author books
        // Need to construct search query similar to ListBook logic
        // For authors, we can use the 'author' parameter if search supports it,
        // or authors:"=Name"
        const query = `authors:"=${this.currentAuthor}"`;
        console.log('[author.vue] fetchBooks - calling /search with query:', query);
        try {
            const rsp = await this.$backend(`/search?name=${encodeURIComponent(query)}&start=${start}&size=${this.page_size}&order=title`);
            console.log('[author.vue] fetchBooks - response received, books count:', rsp.books?.length);
            if (rsp.err === 'ok') {
                this.books = rsp.books;
                this.total = rsp.total;
                this.page_cnt = Math.max(1, Math.ceil(this.total / this.page_size));
            }
        } catch (e) {
            console.error('[author.vue] fetchBooks - error:', e);
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
                    author: this.currentAuthor,
                    category: this.targetCategory
                }),
                headers: {
                    'Content-Type': 'application/json'
                }
            });
            if (rsp.err === 'ok') {
                this.$alert("success", rsp.msg);
                // Refresh to show updates? Categories usually don't show on cards unless configured.
                // But good to refresh.
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
    async pinAuthor(authorName) {
        if (!this.isLoggedIn) {
            this.$alert("warning", this.$t('common.loginRequired') || 'Please login first');
            return;
        }
        try {
            const rsp = await this.$backend("/user/pin", {
                method: "POST",
                body: JSON.stringify({
                    item_type: 0,  // 0: 作者
                    value: authorName
                }),
                headers: {
                    'Content-Type': 'application/json'
                }
            });
            if (rsp.err === 'ok') {
                // Refresh the list
                let listRsp = await this.$backend("/author" + (this.show_all ? "?show=all" : ""));
                this.items = listRsp.items;
                this.pins = listRsp.pins || [];
            } else {
                this.$alert("error", rsp.msg);
            }
        } catch (e) {
            console.error('Pin author failed:', e);
            this.$alert("error", this.$t('common.operationFailed') || 'Operation failed');
        }
    },
    async unpinAuthor(authorName) {
        if (!this.isLoggedIn) {
            this.$alert("warning", this.$t('common.loginRequired') || 'Please login first');
            return;
        }
        try {
            const rsp = await this.$backend("/user/unpin", {
                method: "POST",
                body: JSON.stringify({
                    item_type: 0,  // 0: 作者
                    value: authorName
                }),
                headers: {
                    'Content-Type': 'application/json'
                }
            });
            if (rsp.err === 'ok') {
                // Refresh the list
                let listRsp = await this.$backend("/author" + (this.show_all ? "?show=all" : ""));
                this.items = listRsp.items;
                this.pins = listRsp.pins || [];
            } else {
                this.$alert("error", rsp.msg);
            }
        } catch (e) {
            console.error('Unpin author failed:', e);
            this.$alert("error", this.$t('common.operationFailed') || 'Operation failed');
        }
    }
  }
}
</script>
