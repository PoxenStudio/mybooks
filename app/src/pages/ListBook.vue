<template>
  <div>
    <v-row>
      <v-col cols=12>
        <h2>{{ pageDisplayTitle }}</h2>
        <v-divider class="mt-3 mb-0"></v-divider>
      </v-col>

      <v-col>
        <book-cards :books="books"></book-cards>
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
  computed: {},
  data: () => ({
    title: "",
    pageDisplayTitle: "", // 用于页面显示的标题
    page: 1,
    books: [],
    total: 0,
    page_size: 60,
    page_cnt: 0,
    inited: false,
  }),
  async asyncData({route, app, res}) {
    if (res !== undefined) {
      res.setHeader('Cache-Control', 'no-cache');
    }
    return app.$backend(route.fullPath);
  },
  head() {
    let displayTitle = "";

    switch (this.$route.path) {
      case "/hot":
        displayTitle = this.$t('listBook.hotBooks');
        break;

      case "/search":
        displayTitle = this.$t('listBook.search');
        break;

      case "/recent":
        displayTitle = this.$t('listBook.recentUpdates');
        break;

      case "/favorites":
        displayTitle = this.$t('listBook.favoritesBooks');
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

    // 设置页面显示的标题
    this.pageDisplayTitle = displayTitle;

    return {
      title: displayTitle,
    }
  },
  created() {
    if (this.$route.query.start != undefined) {
      this.page = 1 + parseInt(this.$route.query.start / this.page_size)
    }
    if (!this.inited) {

    }
    this.page_cnt = Math.max(1, Math.ceil(this.total / this.page_size))

  },

  beforeRouteUpdate(to, from, next) {
    this.init(to, next);
  },
  methods: {
    init(route, next) {
      this.inited = true;
      this.$store.commit('navbar', true);
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
