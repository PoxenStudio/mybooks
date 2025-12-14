<template>
  <div>
    <v-tabs v-model="activeTab" show-arrows>
      <v-tab v-for="category in categories" :key="category.name">
        {{ category.name }} ({{ category.count }})
      </v-tab>
    </v-tabs>

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
          this.categories = response.categories;
          if (this.categories.length > 0) {
            this.fetchBooks();
          }
        } else {
          this.$alert("error", response.msg || "获取分类失败");
        }
      } catch (error) {
        console.error("Failed to fetch categories:", error);
        this.$alert("error", "网络错误");
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
          this.books = response.books;
          this.total = response.total;
          this.page_cnt = Math.max(1, Math.ceil(this.total / this.page_size));
        } else {
          this.$alert("error", response.msg || "获取图书失败");
        }
      } catch (error) {
        console.error("Failed to fetch books:", error);
        this.$alert("error", "网络错误");
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
</style>
