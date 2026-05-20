<template>
  <div class="wap-page">
    <wap-header />
    <main class="wap-main">

      <div class="wap-search">
        <select v-model="searchCategory" class="search-category">
          <option v-for="cat in searchCategories" :value="cat.value" :key="cat.value">{{ $t(cat.label) }}</option>
        </select>
        <input
          type="text"
          v-model="searchQuery"
          :placeholder="$t('appHeader.search')"
          class="search-input"
          @keyup.enter="doSearch"
        />
        <button @click="doSearch" class="search-btn">{{ $t('appHeader.search') }}</button>
      </div>
      <div class="wap-nav-links">
        <a href="/wap/categories">{{ $t('nav.categories') }}</a>
        <a href="/wap/languages">{{ $t('nav.languages') }}</a>
        <a href="/wap/authors">{{ $t('nav.authors') }}</a>
      </div>
      <div v-if="isLoggedIn" class="wap-user-links">
        <a href="/wap/reading">{{ $t('nav.reading') }}</a>
        <a href="/wap/favorites">{{ $t('nav.favorites') }}</a>
        <a href="/wap/wants">{{ $t('nav.wants') }}</a>
      </div>
      <div v-if="searchResults.length > 0" class="wap-results">
        <wap-book-cards :books="searchResults" />
        <div v-if="hasMore" class="wap-pagination">
          <button @click="loadMore" class="load-more-btn">{{ $t('common.loadMore') }}</button>
        </div>
      </div>
    </main>
    <wap-footer />
  </div>
</template>

<script>
import WapHeader from '~/components/WapHeader.vue';
import WapFooter from '~/components/WapFooter.vue';
import WapBookCards from '~/components/WapBookCards.vue';

export default {
  layout: 'wap',
  components: {
    WapHeader,
    WapFooter,
    WapBookCards
  },
  data() {
    return {
      searchQuery: '',
      searchCategory: 'all',
      searchResults: [],
      searchCategories: [
        { value: 'all', label: 'appHeader.searchAll' },
        { value: 'title', label: 'appHeader.searchTitle' },
        { value: 'author', label: 'appHeader.searchAuthor' },
        { value: 'isbn', label: 'appHeader.searchISBN' },
        { value: 'comments', label: 'appHeader.searchComments' },
        { value: 'category', label: 'appHeader.searchCategory' }
      ],
      currentPage: 1,
      hasMore: false,
      loading: false
    };
  },
  computed: {
    isLoggedIn() {
      return this.$store.state.user && this.$store.state.user.is_login;
    },
    sys() {
      return this.$store.state.sys || {};
    }
  },
  mounted() {
    if (process.client && localStorage.getItem('searchCategory')) {
      this.searchCategory = localStorage.getItem('searchCategory');
    }
    // 初始化用户信息
    this.initUserInfo();
    // Load recent books as default results
    this.loadRecentBooks();
  },
  methods: {
    async initUserInfo() {
      try {
        const rsp = await this.$backend('/user/info');
        if (rsp.err === 'ok') {
          this.$store.commit('login', rsp);
        }
      } catch (e) {
        console.error(e);
      }
    },
    loadRecentBooks() {
      this.$backend('/index').then(rsp => {
        if (rsp.err === 'ok') {
          this.searchResults = rsp.new_books || [];
          this.currentPage = 1;
          this.hasMore = false;
        }
      });
    },
    doSearch() {
      let query = this.searchQuery.trim();
      if (!query) return;

      // Remove existing prefixes
      query = query.replace(/^(title:|author:|isbn:|comments:|#)/i, '').trim();

      // Add prefix
      if (this.searchCategory !== 'all') {
        if (this.searchCategory === 'category') {
          query = '#' + query;
        } else {
          query = this.searchCategory + ':' + query;
        }
      }

      // Save category
      if (process.client) {
        localStorage.setItem('searchCategory', this.searchCategory);
      }

      // Execute search
      this.$backend('/search', {
        method: 'POST',
        body: JSON.stringify({ name: query, page: 1 })
      }).then(rsp => {
        if (rsp.err === 'ok') {
          this.searchResults = rsp.books || [];
          this.currentPage = 1;
          this.hasMore = rsp.total > this.searchResults.length;
        }
      });
    },
    loadMore() {
      this.$backend('/search', {
        method: 'POST',
        body: JSON.stringify({ name: this.searchQuery, page: this.currentPage + 1 })
      }).then(rsp => {
        if (rsp.err === 'ok') {
          this.searchResults = this.searchResults.concat(rsp.books || []);
          this.currentPage++;
          this.hasMore = rsp.total > this.searchResults.length;
        }
      });
    }
  }
};
</script>

<style scoped>
.wap-page {
  max-width: 1200px;
  margin: 0 auto;
  padding: 16px;
}
.wap-site-title {
  text-align: center;
  margin: 16px 0;
}
.wap-search {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
  align-items: center;
  justify-content: center;
}
.search-category {
  padding: 8px;
  border: 1px solid #ccc;
  border-radius: 4px;
}
.search-input {
  padding: 8px;
  flex: 1;
  max-width: 500px;
  border: 1px solid #ccc;
  border-radius: 4px;
}
.search-btn {
  padding: 8px 16px;
  background-color: #2196F3;
  color: white;
  border: none;
  border-radius: 4px;
}
.wap-nav-links, .wap-user-links {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  justify-content: center;
  margin-bottom: 16px;
}
.wap-nav-links a, .wap-user-links a {
  text-decoration: none;
  color: #2196F3;
}
.load-more-btn {
  display: block;
  margin: 16px auto;
  padding: 8px 24px;
  background-color: #4CAF50;
  color: white;
  border: none;
  border-radius: 4px;
}
</style>
