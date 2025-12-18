<template>
    <v-row>
        <v-col cols=12 xs=12 sm=6 md=4 lg=3 v-for="(book,idx) in render_books" :key="idx+'-books-'+book.id" class="book-list-card">
            <v-card :to="book.href" >
                <v-row>
                    <v-col cols=3 class='col-book-img'>
                        <div class="book-img-container">
                            <v-img :src="book.img" :aspect-ratio="11/15" style="border-radius: 12px;" class="book-img-hover"></v-img>
                            <!-- 实体书角标 -->
                            <div v-if="book.book_type === 1" class="physical-book-badge">
                                <v-icon small color="white">mdi-bookshelf</v-icon>
                            </div>
                            <!-- 音频书角标 -->
                            <div v-if="isAudioPage" class="audio-book-badge">
                                <v-icon small color="white">mdi-headphones</v-icon>
                            </div>
                        </div>
                    </v-col>
                    <v-col cols=9 class='col-book-info'>
                        <v-card-text class="pb-0" align-left>
                            <div class="book-title">{{book.title}}</div>
                            <slot name="introduce" :book="book"></slot>
                            <div class="book-comments">
                                <p v-if="book.comments" v-html="book.comments"></p>
                                <p v-else>{{ $t('bookCards.browseDetails') }}</p>
                            </div>
                        </v-card-text>
                    </v-col>
                </v-row>
                <slot name="actions" :book="book"></slot>
            </v-card>
        </v-col>
    </v-row>
</template>

<script>
export default {
    props: {
        books: Array,
        isAudioPage: {
            type: Boolean,
            default: false
        }
    },
    components: {
    },
    computed: {
        render_books: function() {
            return (this.books || []).map( b => {
                // 确保b是一个对象
                if (!b) return {};
                
                if ( b['href'] == undefined ) {
                    if (this.isAudioPage) {
                        b['href'] = "/audio/" + (b.id || '');
                    } else {
                        b['href'] = "/book/" + (b.id || '');
                    }
                }
                return b;
            }).filter(Boolean); // 过滤掉空对象
        },
    },
    data: () => {
        return {
        }
    },
}
</script>

<style scoped>
.book-title {
    display: block;
    /*height: 1em;*/
    overflow-y: hidden;
    display: -webkit-box;
    -webkit-line-clamp: 1;
    line-clamp: 1;
    -webkit-box-orient: vertical;
    text-overflow: clip;
    text-align: left;
    font-weight: bold;
}
.book-comments {
    overflow: hidden;
    display: -webkit-box;
    -webkit-line-clamp: 3;
    line-clamp: 3;
    -webkit-box-orient: vertical;
    text-overflow: clip;
    margin-top: 6px;
    text-align: left;
}
.book-comments p {
    font-size: small;
    margin-bottom: 0px;
}
.book-list-card .row {
    margin-bottom: 0px;
}
.page-title {
    font-weight: bold;
    text-align: left;
}
.new-legend {
    margin-top: 30px;
    margin-bottom: 20px;
}
.col-book-img {
    padding: 0 0 0 12px;
}
.book-img-container {
    position: relative;
    display: inline-block;
    width: 100%;
}
.physical-book-badge {
    position: absolute;
    top: 6px;
    left: 6px;
    background-color: #2196F3;
    border-radius: 50%;
    width: 24px;
    height: 24px;
    display: flex;
    align-items: center;
    justify-content: center;
    box-shadow: 0 2px 8px rgba(33, 150, 243, 0.4);
    z-index: 3;
}
.audio-book-badge {
    position: absolute;
    top: 6px;
    right: 6px;
    background-color: #9C27B0;
    border-radius: 50%;
    width: 24px;
    height: 24px;
    display: flex;
    align-items: center;
    justify-content: center;
    box-shadow: 0 2px 8px rgba(156, 39, 176, 0.4);
    z-index: 3;
}
.col-book-info {
    padding: 0;
    margin-left: -6px;
    margin-top: -6px;
}
.book-img-hover {
    transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}
.book-img-hover:hover {
    overflow-clip-margin: content-box;
    overflow: clip;
    transform: scale(1.06);
    z-index: 2;
    box-shadow: 0 8px 24px rgba(0,0,0,0.18);
}
</style>
