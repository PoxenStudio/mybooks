<template>
    <div>
        <!-- 阅读统计卡片 -->
        <v-row v-if="readingStats">
            <v-col cols=12>
                <legend>{{ $t('history.readingStats') }}</legend>
                <v-divider class="mb-4"></v-divider>
            </v-col>
            <v-col cols=6 sm=3>
                <v-card class="pa-4 text-center stats-card">
                    <v-card-title class="justify-center">
                        <span class="display-1 primary--text">{{ readingStats.total_reading }}</span>
                    </v-card-title>
                    <v-card-subtitle>{{ $t('history.totalReading') }}</v-card-subtitle>
                </v-card>
            </v-col>
            <v-col cols=6 sm=3>
                <v-card class="pa-4 text-center stats-card">
                    <v-card-title class="justify-center">
                        <span class="display-1 success--text">{{ readingStats.total_read_done }}</span>
                    </v-card-title>
                    <v-card-subtitle>{{ $t('history.totalReadDone') }}</v-card-subtitle>
                </v-card>
            </v-col>
            <v-col cols=6 sm=3>
                <v-card class="pa-4 text-center stats-card">
                    <v-card-title class="justify-center">
                        <span class="display-1 info--text">{{ readingStats.month_reading }}</span>
                    </v-card-title>
                    <v-card-subtitle>{{ $t('history.monthReading') }}</v-card-subtitle>
                </v-card>
            </v-col>
            <v-col cols=6 sm=3>
                <v-card class="pa-4 text-center stats-card">
                    <v-card-title class="justify-center">
                        <span class="display-1 orange--text">{{ readingStats.month_read_done }}</span>
                    </v-card-title>
                    <v-card-subtitle>{{ $t('history.monthReadDone') }}</v-card-subtitle>
                </v-card>
            </v-col>
        </v-row>

        <!-- 当前在读书籍 -->
        <v-row v-if="currentReadingBooks && currentReadingBooks.length > 0">
            <v-col cols=12>
                <legend>{{ $t('history.currentReadingBooks') }}</legend>
                <v-divider></v-divider>
            </v-col>
            <v-col cols=4 sm=2 v-for="book in currentReadingBooks" :key="'reading-' + book.id">
                <v-card :to="'/book/' + book.id" class="ma-1 book-card">
                    <v-img :src="book.img" :aspect-ratio="11/15">
                        <v-chip small color="primary" class="ma-1 reading-chip">{{ $t('readingState.reading') }}</v-chip>
                    </v-img>
                </v-card>
            </v-col>
        </v-row>

        <!-- 本月读完书籍 -->
        <v-row v-if="monthReadDoneBooks && monthReadDoneBooks.length > 0">
            <v-col cols=12>
                <legend>{{ $t('history.monthReadDoneBooks') }}</legend>
                <v-divider></v-divider>
            </v-col>
            <v-col cols=4 sm=2 v-for="book in monthReadDoneBooks" :key="'done-' + book.id">
                <v-card :to="'/book/' + book.id" class="ma-1 book-card">
                    <v-img :src="book.img" :aspect-ratio="11/15">
                        <v-chip small color="success" class="ma-1 done-chip">{{ $t('readingState.done') }}</v-chip>
                    </v-img>
                </v-card>
            </v-col>
        </v-row>

        <!-- 原有的历史记录 -->
        <v-row align=start v-if="history.length == 0">
            <v-col cols=12>
                <p class="title"> {{ $t('history.noRecords') }} </p>
            </v-col>
        </v-row>
        <v-row v-else v-for="item in history" :key="item.name">
            <v-col cols=12>
                <legend>{{ $t(`history.${item.name}`) }}</legend>
                <v-divider></v-divider>
            </v-col>
            <v-col cols=12 v-if="item.books.length==0" >
                <p class="pb-6">{{ $t('history.noBooks') }}</p>
            </v-col>
            <v-col cols=4 sm=2 v-else v-for="book in item.books" :key="item.name + book.id">
                <v-card :to="book.href" class="ma-1 book-card">
                    <v-img :src="book.img" :aspect-ratio="11/15" > </v-img>
                </v-card>
            </v-col>
        </v-row>
    </div>
</template>

<script>
export default {
    components: {
    },
    computed: {
        history: function() {
            if ( this.user.extra === undefined ) { return [] }
            return [
                { name: 'onlineReading', books: this.get_history(this.user.extra.read_history) },
            ]
        },
    },
    data: () => ({
        user: {},
        readingStats: null,
        currentReadingBooks: [],
        monthReadDoneBooks: [],
    }),
    async asyncData({ params, app, res }) {
        if ( res !== undefined ) {
            res.setHeader('Cache-Control', 'no-cache');
        }
        return app.$backend("/user/info?detail=1");
    },
    head() {
        return { title: this.$t('appHeader.reading_history') };
    },
    created() {
        this.init(this.$route);
    },
    beforeRouteUpdate(to, from, next) {
        this.init(to, next);
    },
    methods: {
        init(route, next) {
            this.$store.commit('navbar', true);

            // 获取用户信息
            this.$backend("/user/info?detail=1")
            .then( rsp => {
                this.user = rsp.user;
            });

            // 获取阅读统计信息
            this.$backend("/reading/stats")
            .then( rsp => {
                if (rsp.err === 'ok') {
                    this.readingStats = rsp.stats;
                    this.currentReadingBooks = rsp.current_reading_books || [];
                    this.monthReadDoneBooks = rsp.month_read_done_books || [];
                }
            })
            .catch(error => {
                console.warn('Failed to load reading stats:', error);
            });

            if ( next ) next();
        },
        get_history(his) {
            if ( ! his ) { return []; }
            return his.map( b => {
                b.href = '/book/' + b.id;
                return b;
            });
        },
    },
}
</script>

<style scoped>
.stats-card {
    transition: transform 0.2s;
}

.stats-card:hover {
    transform: translateY(-2px);
}

.book-card {
    transition: transform 0.2s ease-in-out;
}

.book-card:hover {
    transform: scale(1.02);
}

.reading-chip {
    position: absolute;
    top: 8px;
    left: 8px;
    z-index: 1;
    box-shadow: 0 2px 4px rgba(0,0,0,0.3);
}

.done-chip {
    position: absolute;
    top: 8px;
    left: 8px;
    z-index: 1;
    box-shadow: 0 2px 4px rgba(0,0,0,0.3);
}
</style>
