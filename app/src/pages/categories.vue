<template>
  <div>
    <div class="folder-tabs-wrapper">
      <div class="folder-tabs">
        <div
          v-for="(category, index) in categories"
          :key="category.name"
          :class="['folder-tab', { 'active': activeTab === index }]"
          @click="activeTab = index"
        >
          <span class="tab-name">{{ category.name }}</span>
          <span class="tab-count">({{ category.count }})</span>
        </div>
      </div>
    </div>

    <v-divider></v-divider>

    <div class="mt-4">
      <book-cards :books="books"></book-cards>
    </div>

    <v-container class="max-width">
      <v-pagination v-if="page_cnt > 0" v-model="page" :length="page_cnt" circle @input="change_page"></v-pagination>
    </v-container>
  </div>
</template>

<script>
import BookCards from "../components/BookCards.vue";

export default {
  components: {
    BookCards,
  },
  data: () => ({
    activeTab: 0,
    categories: [],
    books: [],
    page: 1,
    page_size: 60,
    total: 0,
    page_cnt: 0,
    loading: false,
  }),
  async created() {
    await this.fetchCategories();
  },
  watch: {
    activeTab() {
      this.page = 1;
      this.fetchBooks();
    },
  },
  methods: {
    async fetchCategories() {
      try {
        const response = await this.$backend("/categories");
        if (response.err === "ok") {
          this.categories = response.categories || [];
          if (this.categories.length > 0) {
            this.fetchBooks();
          }
        } else {
          // 使用store.commit直接提交alert，避免$alert可能不存在的问题
          if (this.$store) {
            this.$store.commit('alert', {
              type: 'error',
              msg: response.msg || "获取分类失败",
              to: ''
            });
          }
        }
      } catch (error) {
        console.error("Failed to fetch categories:", error);
        // 使用store.commit直接提交alert，避免$alert可能不存在的问题
        if (this.$store) {
          this.$store.commit('alert', {
            type: 'error',
            msg: "网络错误",
            to: ''
          });
        }
      }
    },
    async fetchBooks() {
      if (this.categories.length === 0) return;

      this.loading = true;
      const category = this.categories[this.activeTab].name;
      const start = (this.page - 1) * this.page_size;

      try {
        // Construct search query for custom column
        // Assuming custom column search syntax is #category:value
        // Need to verify if this syntax works with the existing search API
        // The search API uses calibre_db.search which supports standard Calibre search syntax
        const query = `#category:=${category}`;
        const response = await this.$backend(`/search?name=${encodeURIComponent(query)}&start=${start}&size=${this.page_size}`);

        if (response.err === "ok") {
          this.books = response.books || [];
          this.total = response.total || 0;
          this.page_cnt = Math.max(1, Math.ceil(this.total / this.page_size));
        } else {
          // 使用store.commit直接提交alert，避免$alert可能不存在的问题
          if (this.$store) {
            this.$store.commit('alert', {
              type: 'error',
              msg: response.msg || "获取图书失败",
              to: ''
            });
          }
        }
      } catch (error) {
        console.error("Failed to fetch books:", error);
        // 使用store.commit直接提交alert，避免$alert可能不存在的问题
        if (this.$store) {
          this.$store.commit('alert', {
            type: 'error',
            msg: "网络错误",
            to: ''
          });
        }
      } finally {
        this.loading = false;
      }
    },
    change_page() {
      this.fetchBooks();
      this.$vuetify.goTo(0);
    },
  },
};
</script>

<style scoped>
.folder-tabs-wrapper {
  padding: 16px;
}

.folder-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.folder-tab {
  display: inline-flex;
  align-items: center;
  padding: 8px 16px;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.3s ease;
  user-select: none;
  position: relative;
  overflow: hidden;
}

.folder-tab::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 4px;
  background: transparent;
  border-radius: 2px;
  transition: all 0.3s ease;
}

.folder-tab .tab-name {
  font-weight: 500;
  font-size: 14px;
}

.folder-tab .tab-count {
  margin-left: 4px;
  font-size: 12px;
  opacity: 0.7;
}

.folder-tab:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
}

.folder-tab.active {
  transform: translateY(-4px);
  box-shadow: 0 6px 16px rgba(0, 0, 0, 0.2);
}

.folder-tab.active::before {
  background: currentColor;
}

.folder-tab.active .tab-count {
  opacity: 1;
  font-weight: 600;
}

.folder-tab.active .tab-name {
  font-weight: 600;
}

.theme--light .folder-tab {
  background-color: #f5f5f5;
  color: #424242;
  border: 1px solid #e0e0e0;
}

.theme--light .folder-tab:hover {
  background-color: #eeeeee;
}

.theme--light .folder-tab.active {
  background-color: #1976d2;
  color: white;
  border-color: #1976d2;
}

.theme--dark .folder-tab {
  background-color: #2d2d2d;
  color: #e0e0e0;
  border: 1px solid #424242;
}

.theme--dark .folder-tab:hover {
  background-color: #3d3d3d;
}

.theme--dark .folder-tab.active {
  background-color: #1976d2;
  color: white;
  border-color: #1976d2;
}

@media (max-width: 600px) {
  .folder-tabs {
    gap: 6px;
  }

  .folder-tab {
    padding: 6px 12px;
    font-size: 13px;
  }

  .folder-tab .tab-name {
    font-size: 13px;
  }

  .folder-tab .tab-count {
    font-size: 11px;
  }
}
</style>
