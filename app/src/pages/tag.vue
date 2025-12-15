<template>
  <div>
    <!-- Detail Mode: Books for specific tag -->
    <div v-if="currentTag">
      <v-row>
        <v-col cols="12">
          <h2>{{ $t('listBook.tagBooks', { name: currentTag }) }}</h2>
        </v-col>

        <!-- Batch Set Category Card -->
        <v-col cols="12">
          <v-card outlined class="mb-4">
            <v-card-title class="py-2" @click="showBatch = !showBatch">
              <span class="text-subtitle-1 font-weight-bold">{{ $t('listBook.batchSetCategory') }}</span>
              <v-spacer></v-spacer>
              <v-btn icon @click="showBatch = !showBatch">
                <v-icon>{{ showBatch ? 'mdi-chevron-up' : 'mdi-chevron-down' }}</v-icon>
              </v-btn>
            </v-card-title>

            <v-expand-transition>
              <div v-show="showBatch">
                <v-card-text>
                  <v-row align="center">
                    <v-col cols="12" sm="6">
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
                  <div class="caption text-grey mt-2">
                    {{ $t('listBook.setCategoryForTagBooks', { category: targetCategory || '...', tag: currentTag }) }}
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

    <!-- List Mode: All Tags -->
    <div v-else>
       <v-row>
        <v-col>
          <v-chip
            small
            class="ma-1"
            v-for="item in visibleMetaItems"
            :key="item.name"
            outlined
            color="primary"
            @click="selectTag(item.name)"
            style="cursor: pointer"
          >
            {{ item.name }}
            <span v-if="item.count">&nbsp;({{ item.count }})</span>
          </v-chip>
           <v-btn v-if="items.length > 50 && !show_all" @click="expandList()" color="primary" rounded small>
             {{ $t('listMeta.showAll') || 'Show All' }}
           </v-btn>
        </v-col>
      </v-row>
    </div>

    <!-- Confirmation Dialog -->
    <v-dialog v-model="dialog" max-width="400">
      <v-card>
        <v-card-title class="headline">{{ $t('listBook.confirmBatchUpdate') }}</v-card-title>
        <v-card-text v-html="$t('listBook.confirmBatchUpdateContent', { category: targetCategory, tag: currentTag, total: total })"></v-card-text>
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
    show_all: false,

    // Detail State
    currentTag: null,
    books: [],
    page: 1,
    page_size: 60,
    total: 0,
    page_cnt: 0,

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
    }
  },
  head() {
    if (this.currentTag) {
        return { title: this.$t('listBook.tagBooks', { name: this.currentTag }) };
    }
    return { title: this.$t('listMeta.allTags') };
  },
  async asyncData({ app, route, res }) {
    if (res !== undefined) {
        res.setHeader('Cache-Control', 'no-cache');
    }
    // Pre-load tag list if no specific tag selected
    let name = route.query.name || route.params.name;
    if (name) {
        name = decodeURIComponent(name);
    }
    if (!name) {
        let rsp = await app.$backend("/tag");
        return { items: rsp.items || [], total: rsp.total };
    }
    return {};
  },
  created() {
    this.init();
    let name = this.$route.query.name || this.$route.params.name;
    if (name) {
        name = decodeURIComponent(name);
        this.selectTag(name);
    }
  },
  watch: {
    '$route.query.name'(newName) {
       if (newName) {
         newName = decodeURIComponent(newName);
         this.selectTag(newName);
       } else {
         let paramsName = this.$route.params.name;
         if (paramsName) {
           paramsName = decodeURIComponent(paramsName);
           this.selectTag(paramsName);
         } else {
           this.clearTag();
         }
       }
    },
    '$route.params.name'(newName) {
       if (newName) {
         newName = decodeURIComponent(newName);
         this.selectTag(newName);
       } else {
         let queryName = this.$route.query.name;
         if (queryName) {
           queryName = decodeURIComponent(queryName);
           this.selectTag(queryName);
         } else {
           this.clearTag();
         }
       }
    }
  },
  methods: {
    async init() {
        this.$store.commit('navbar', true);
        if (this.items.length === 0 && !this.currentTag) {
            let rsp = await this.$backend("/tag" + (this.show_all ? "?show=all" : ""));
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
        let rsp = await this.$backend("/tag?show=all");
        this.items = rsp.items;
    },
    selectTag(name) {
        this.currentTag = name;
        this.page = 1;
        // 如果当前路由有params.name，说明是通过/tag/:name访问的，需要转换为query参数并清除params
        if (this.$route.params.name || this.$route.query.name !== name) {
            // 只使用query参数，不保留params，这样URL会更简洁
            // 对name参数进行encodeURIComponent处理，确保中文标签在URL中正确显示
            this.$router.push({ path: '/tag', query: { ...this.$route.query, name: encodeURIComponent(name) } });
        }
        this.fetchBooks();
    },
    clearTag() {
        this.currentTag = null;
        this.books = [];
        this.$router.push({ query: { ...this.$route.query, name: undefined } });
        // Ensure list is loaded
        if (this.items.length === 0) {
            this.init();
        }
    },
    async fetchBooks() {
        if (!this.currentTag) return;
        const start = (this.page - 1) * this.page_size;
        // Search by tag
        const query = `tags:="${this.currentTag}"`;
        try {
            const rsp = await this.$backend(`/search?name=${encodeURIComponent(query)}&start=${start}&size=${this.page_size}`);
            if (rsp.err === 'ok') {
                this.books = rsp.books;
                this.total = rsp.total;
                this.page_cnt = Math.max(1, Math.ceil(this.total / this.page_size));
            }
        } catch (e) {
            this.$alert("error", "Failed to load books");
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
                    tag: this.currentTag,
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
    }
  }
}
</script>
