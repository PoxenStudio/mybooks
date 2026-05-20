<template>
  <div class="wap-book-cards">
    <div v-for="(book, idx) in books" :key="'book-' + book.id" class="wap-book-card">
      <div class="wap-book-cover">
        <img :src="book.thumb || book.img" alt="cover" width="80" />
      </div>
      <div class="wap-book-info">
        <h4 class="wap-book-title">{{ book.title }}</h4>
        <p class="wap-book-author">{{ book.author }}</p>
        <div v-if="book.category" class="wap-book-category">
          <span class="category-badge">{{ book.category }}</span>
        </div>
        <div v-if="book.files && book.files.length > 0" class="wap-book-download">
          <a
            v-for="(file, idx2) in book.files"
            :key="'file-' + idx2"
            :href="'/api/book/' + book.id + '.' + file.format"
            target="_blank"
            class="download-link"
          >{{ file.format }}</a>
        </div>
      </div>
      <div style="clear:both;"></div>
    </div>
  </div>
</template>

<script>
export default {
  name: 'WapBookCards',
  props: {
    books: {
      type: Array,
      default: () => []
    }
  }
};
</script>

<style scoped>
.wap-book-cards {
  width: 100%;
}
.wap-book-card {
  border: 1px solid #ddd;
  border-radius: 4px;
  padding: 8px;
  margin-bottom: 10px;
  overflow: hidden;
}
.wap-book-cover {
  float: left;
  margin-right: 10px;
}
.wap-book-cover img {
  display: block;
  width: 80px;
  height: 107px;
  object-fit: cover;
}
.wap-book-info {
  overflow: hidden;
}
.wap-book-title {
  margin: 0 0 4px 0;
  font-size: 15px;
}
.wap-book-author {
  font-size: 13px;
  color: #666;
  margin: 0 0 4px 0;
}
.category-badge {
  background-color: #2196F3;
  color: white;
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 12px;
}
.wap-book-download {
  margin-top: 6px;
}
.download-link {
  display: inline-block;
  margin: 2px 6px 2px 0;
  padding: 2px 8px;
  background-color: #eee;
  text-decoration: none;
  color: #333;
  border-radius: 4px;
  font-size: 13px;
}
</style>
