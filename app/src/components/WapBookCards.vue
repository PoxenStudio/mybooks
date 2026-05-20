<template>
  <div class="wap-book-cards">
    <div v-for="(book, idx) in books" :key="'book-' + book.id" class="wap-book-card">
      <div class="wap-book-cover">
        <img :src="book.thumb || book.img" alt="cover" />
      </div>
      <div class="wap-book-info">
        <h4 class="wap-book-title">{{ book.title }}</h4>
        <p class="wap-book-author">{{ book.author }}</p>
        <div v-if="book.category" class="wap-book-category">
          <span class="category-badge">{{ book.category }}</span>
        </div>
        <div v-if="book.comments" class="wap-book-comments" v-html="book.comments"></div>
        <div class="wap-book-download">
          <div v-if="book.files.length > 0" class="download-list">
            <template v-for="(file, idx2) in book.files" :key="'file-' + idx2">
              <a :href="'/api/book/' + book.id + '.' + file.format" target="_blank" class="download-link">
                {{ file.format }}
              </a>
            </template>
          </div>
        </div>
      </div>
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
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 16px;
}
.wap-book-card {
  border: 1px solid #ddd;
  border-radius: 4px;
  padding: 8px;
  display: flex;
  gap: 12px;
}
.wap-book-cover img {
  width: 100px;
  height: auto;
  aspect-ratio: 3/4;
}
.wap-book-info {
  flex: 1;
}
.wap-book-title {
  margin: 0;
  font-size: 16px;
}
.wap-book-author {
  font-size: 14px;
  color: #666;
  margin: 4px 0;
}
.category-badge {
  background-color: #2196F3;
  color: white;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 12px;
}
.wap-book-comments {
  font-size: 14px;
  margin: 8px 0;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
}
.download-link {
  display: inline-block;
  margin: 4px 8px 4px 0;
  padding: 2px 8px;
  background-color: #eee;
  text-decoration: none;
  color: #333;
  border-radius: 4px;
  font-size: 13px;
}
@media (max-width: 600px) {
  .wap-book-cards {
    grid-template-columns: 1fr;
  }
}
</style>
