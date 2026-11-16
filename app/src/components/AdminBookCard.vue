<template>
    <v-card class="admin-book-card" outlined>
        <!-- 左侧：封面与 ID -->
        <div class="admin-book-card__cover">
            <a :href="`/book/${book.id}`" target="_blank" class="admin-book-card__cover-link">
                <v-img
                    :src="book.thumb || book.img"
                    height="120"
                    width="90"
                    class="admin-book-card__img"
                ></v-img>
            </a>
            <a :href="`/book/${book.id}`" target="_blank" class="admin-book-card__id">{{ book.id }}</a>
        </div>

        <!-- 右侧：书籍信息 -->
        <div class="admin-book-card__info">
            <div class="admin-book-card__title">{{ book.title || '-' }}</div>
            <div class="admin-book-card__author text-truncate">{{ authorText }}</div>
            <div class="admin-book-card__category">
                <v-chip x-small label outlined color="primary">
                    {{ book.category || $t('admin.books.uncategorized') }}
                </v-chip>
            </div>
            <div class="admin-book-card__actions">
                <v-btn x-small text color="error" class="px-1" @click.stop="$emit('delete', book)">
                    <v-icon x-small left>mdi-delete</v-icon>
                    {{ $t('admin.books.deleteBook') }}
                </v-btn>
            </div>
        </div>
    </v-card>
</template>

<script>
export default {
    name: 'AdminBookCard',
    props: {
        book: { type: Object, required: true },
    },
    computed: {
        authorText() {
            const authors = this.book.authors;
            if (Array.isArray(authors) && authors.length) {
                return authors.join('/');
            }
            return authors || '-';
        },
    },
};
</script>

<style scoped>
.admin-book-card {
    display: flex;
    align-items: stretch;
    padding: 8px 10px;
    gap: 10px;
}
.admin-book-card + .admin-book-card {
    margin-top: 8px;
}
.admin-book-card__info {
    flex: 1 1 auto;
    min-width: 0;
    display: flex;
    flex-direction: column;
}
.admin-book-card__title {
    font-size: 15px;
    font-weight: 600;
    line-height: 1.3;
    overflow: hidden;
    text-overflow: ellipsis;
    display: -webkit-box;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
}
.admin-book-card__author {
    margin-top: 2px;
    font-size: 13px;
    color: var(--v-secondary-base, #757575);
}
.admin-book-card__category {
    margin-top: 6px;
}
.admin-book-card__actions {
    margin-top: auto;
    display: flex;
    justify-content: flex-end;
}
.admin-book-card__cover {
    flex: 0 0 auto;
    display: flex;
    flex-direction: column;
    align-items: center;
}
.admin-book-card__cover-link {
    display: block;
}
.admin-book-card__img {
    border-radius: 4px;
}
.admin-book-card__id {
    margin-top: 4px;
    font-size: 12px;
    color: var(--v-secondary-base, #757575);
    text-decoration: none;
}
</style>
