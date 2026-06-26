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
                      <v-btn
                        color="error"
                        class="ml-2"
                        @click="confirmUpdateTags"
                        :loading="updateLoading"
                      >
                        {{ $t('listBook.updateTags') }}
                      </v-btn>
                    </v-col>
                  </v-row>
                  <div class="caption text-grey mt-2" v-if="targetCategory">
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
          <!-- Pinned Tags -->
          <div v-if="pins && pins.length > 0" class="mb-2">
            <v-chip
              class="ma-1"
              v-for="pin in pins"
              :key="'pin-' + pin.name"
              color="#01847F"
              @click="selectTag(pin.name)"
              style="cursor: pointer; color: white;"
            >
              {{ pin.name }}
              <v-icon
                v-if="isLoggedIn"
                small
                right
                @click.stop="unpinTag(pin.name)"
                class="ml-1"
              >
                mdi-pin-off-outline
              </v-icon>
            </v-chip>
          </div>

          <!-- Regular Tags -->
          <v-chip
            class="ma-1"
            v-for="item in visibleMetaItems"
            :key="item.name"
            color="primary"
            @click="selectTag(item.name)"
            style="cursor: pointer;"
          >
            {{ item.name }}
            <span v-if="item.count">&nbsp;({{ item.count }})</span>
            <v-icon
              v-if="isLoggedIn"
              small
              right
              @click.stop="pinTag(item.name)"
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
        <v-card-text v-html="$t('listBook.confirmBatchUpdateContent', { category: targetCategory, tag: currentTag, total: total })"></v-card-text>
        <v-card-actions>
          <v-spacer></v-spacer>
          <v-btn color="grey darken-1" text @click="dialog = false">{{ $t('common.cancel') }}</v-btn>
          <v-btn color="primary" text @click="doBatchSet">{{ $t('common.ok') }}</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- Update Tags Confirmation Dialog -->
    <v-dialog v-model="updateDialog" max-width="500">
      <v-card>
        <v-card-title class="headline">{{ $t('listBook.confirmUpdateTags') }}</v-card-title>
        <v-card-text>
          <div v-html="$t('listBook.confirmUpdateTagsContent', { tag: currentTag })"></div>
          <div class="mt-2" v-html="$t('listBook.confirmUpdateTagsCount', { total: total })"></div>
          <div class="mt-2 error--text" v-if="total > 300">
            <v-icon color="error" small>mdi-alert</v-icon>
            {{ $t('listBook.confirmUpdateTagsLimit') }}
          </div>
          <div class="mt-2 warning--text">
            <v-icon color="warning" small>mdi-clock-alert</v-icon>
            {{ $t('listBook.confirmUpdateTagsWarning') }}
          </div>
        </v-card-text>
        <v-card-actions>
          <v-spacer></v-spacer>
          <v-btn color="grey darken-1" text @click="updateDialog = false">{{ $t('common.cancel') }}</v-btn>
          <v-btn color="error" text @click="doUpdateTags">{{ $t('listBook.confirmUpdateTagsButton') }}</v-btn>
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
    currentTag: null,
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
    updateLoading: false,
    updateDialog: false,
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
        return { items: rsp.items || [], pins: rsp.pins || [], total: rsp.total };
    }
    return {};
  },
  created() {
    this.init();
    // Watch will handle the initial name param, no need to call selectTag here
  },
  watch: {
    '$route.query.name': {
      handler(newName) {
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
      immediate: true
    },
    '$route.params.name': {
      handler(newName) {
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
      },
      immediate: true
    }
  },
  methods: {
    async init() {
        this.$store.commit('navbar', true);
        if (this.items.length === 0 && !this.currentTag) {
            let rsp = await this.$backend("/tag" + (this.show_all ? "?show=all" : ""));
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
        let rsp = await this.$backend("/tag?show=all");
        this.items = rsp.items;
        this.pins = rsp.pins || [];
    },
    selectTag(name) {
        // Avoid duplicate calls if already showing this tag and fetching or has data
        if (this.currentTag === name && (this.isFetching || this.books.length > 0)) {
            return;
        }
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
        if (this.isFetching) {
            return;
        }
        this.isFetching = true;
        const start = (this.page - 1) * this.page_size;
        // Search by tag
        const query = `tags:"=${this.currentTag}"`;
        try {
            const rsp = await this.$backend(`/search?name=${encodeURIComponent(query)}&start=${start}&size=${this.page_size}`);
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
    },
    confirmUpdateTags() {
        this.updateDialog = true;
    },
    async doUpdateTags() {
        this.updateDialog = false;
        this.updateLoading = true;
        try {
            const rsp = await this.$backend(`/book/update_tags?tag=${encodeURIComponent(this.currentTag)}`, {
                method: "POST",
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
            this.$alert("error", this.$t('listBook.updateTagsFailed'));
        } finally {
            this.updateLoading = false;
        }
    },
    async pinTag(tagName) {
        if (!this.isLoggedIn) {
            this.$alert("warning", this.$t('common.loginRequired') || 'Please login first');
            return;
        }
        try {
            const rsp = await this.$backend("/user/pin", {
                method: "POST",
                body: JSON.stringify({
                    item_type: 1,  // 1: Tag
                    value: tagName
                }),
                headers: {
                    'Content-Type': 'application/json'
                }
            });
            if (rsp.err === 'ok') {
                // Refresh the list
                let listRsp = await this.$backend("/tag" + (this.show_all ? "?show=all" : ""));
                this.items = listRsp.items;
                this.pins = listRsp.pins || [];
            } else {
                this.$alert("error", rsp.msg);
            }
        } catch (e) {
            console.error('Pin tag failed:', e);
            this.$alert("error", this.$t('common.operationFailed') || 'Operation failed');
        }
    },
    async unpinTag(tagName) {
        if (!this.isLoggedIn) {
            this.$alert("warning", this.$t('common.loginRequired') || 'Please login first');
            return;
        }
        try {
            const rsp = await this.$backend("/user/unpin", {
                method: "POST",
                body: JSON.stringify({
                    item_type: 1,  // 1: Tag
                    value: tagName
                }),
                headers: {
                    'Content-Type': 'application/json'
                }
            });
            if (rsp.err === 'ok') {
                // Refresh the list
                let listRsp = await this.$backend("/tag" + (this.show_all ? "?show=all" : ""));
                this.items = listRsp.items;
                this.pins = listRsp.pins || [];
            } else {
                this.$alert("error", rsp.msg);
            }
        } catch (e) {
            console.error('Unpin tag failed:', e);
            this.$alert("error", this.$t('common.operationFailed') || 'Operation failed');
        }
    }
  }
}
</script>
