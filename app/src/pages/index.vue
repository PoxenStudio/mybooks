<template>
    <div>
    <v-row>
        <v-col cols=12>
            <p class="ma-0 title">{{ $t('index.randomRecommendation') }}</p>
        </v-col>
        <v-col cols=6 xs=6 sm=4 md=2 lg=1 v-for="(book,idx) in get_random_books" :key="'rec'+idx+book.id" class="book-card">
            <v-card :to="book.href" class="ma-1">
                <v-img :src="book.img" :aspect-ratio="11/15" style="border-radius: 12px;" class="book-img-hover"> </v-img>
            </v-card>
        </v-col>
    </v-row>
    <v-row>
        <v-col cols=12>
            <v-divider class="new-legend"></v-divider>
            <p class="ma-0 title">{{ $t('index.newRecommendation') }}</p>
        </v-col>
        <v-col cols=12>
            <book-cards :books="get_recent_books"></book-cards>
        </v-col>
    </v-row>
    <v-row>
        <v-col cols=12>
            <v-divider class="new-legend"></v-divider>
            <p class="ma-0 title">{{ $t('index.categoryBrowse') }}</p>
        </v-col>
        <v-col cols=12 sm=6 md=4 v-for="nav in navs" :key="nav.text">
            <v-card outlined style="border-radius: 12px;">
                <v-list>
                    <v-list-item :to="nav.href" >
                        <v-list-item-avatar large color='primary' >
                            <v-icon dark >{{nav.icon}}</v-icon>
                        </v-list-item-avatar>
                        <v-list-item-content>
                            <v-list-item-title>{{nav.text}} </v-list-item-title>
                        </v-list-item-content>
                        <v-list-item-action>
                            <v-icon >mdi-arrow-right</v-icon>
                        </v-list-item-action>
                    </v-list-item>
                </v-list>
            </v-card>
        </v-col>
    </v-row>

    <!-- Release Notes Dialog -->
    <v-dialog v-model="releaseNotesDialog" max-width="480" persistent>
        <v-card class="release-notes-card">
            <v-card-title class="headline text-center">
                {{ $t('index.versionChanges') }}
                <v-spacer></v-spacer>
                <span class="text-body-2 grey--text">{{ countdown }}s</span>
            </v-card-title>
            <v-card-text class="release-notes-card">
                <!-- Render HTML content for release notes -->
                <div v-html="releaseNotesContent" style="max-height: 440px; overflow-y: auto;"></div>
            </v-card-text>
            <v-card-actions class="justify-center">
                <v-btn rounded large color="primary" dark elevation="2" @click="closeReleaseNotesDialog">
                    {{ $t('common.close') }}
                </v-btn>
            </v-card-actions>
        </v-card>
    </v-dialog>
    </div>
</template>

<script>
import BookCards from "~/components/BookCards.vue";
export default {
    name: 'IndexPage',
    components: {
        BookCards,
    },
    computed: {
        get_random_books: function() {
            return this.random_books.map( b => {
                b['href'] = "/book/" + b.id;
                return b;
            });
        },
        get_recent_books: function() {
            return this.new_books.map( b => {
                b['href'] = "/book/" + b.id;
                return b;
            });
        },
    },
    methods: {
        async checkReleaseNotes() {
            try {
                const rsp = await this.$backend('/admin/release/notes?rand='+Math.random());
                if (rsp.err === 'ok' && rsp.msg) {
                    this.releaseNotesContent = rsp.msg;
                    this.releaseNotesDialog = true;
                    this.startCountdown();
                }
            } catch (error) {
                console.error('Failed to check release notes:', error);
            }
        },
        startCountdown() {
            this.countdown = 30;
            this.countdownTimer = setInterval(() => {
                this.countdown--;
                if (this.countdown <= 0) {
                    this.closeReleaseNotesDialog();
                }
            }, 1000);
        },
        closeReleaseNotesDialog() {
            this.releaseNotesDialog = false;
            if (this.countdownTimer) {
                clearInterval(this.countdownTimer);
                this.countdownTimer = null;
            }
        },
    },
    mounted() {
        this.checkReleaseNotes();
    },
    beforeDestroy() {
        if (this.countdownTimer) {
            clearInterval(this.countdownTimer);
        }
    },
    created() {
        this.$store.commit('navbar', true);
        this.navs = [
            { icon: 'widgets',            href:'/nav',       text: this.$t('index.categoryNavigation'),  count: this.$store.state.sys.books      },
            { icon: 'account-group', href:'/author',    text: this.$t('index.authors'),     count: this.$store.state.sys.authors    },
            { icon: 'mdi-home-group',     href:'/publisher', text: this.$t('index.publishers'),   count: this.$store.state.sys.publishers },
            { icon: 'mdi-tag-heart',      href:'/tag',       text: this.$t('index.tags'),     count: this.$store.state.sys.tags       },
            { icon: 'mdi-translate',      href:'/language',       text: this.$t('index.languages'),     count: this.$store.state.sys.languages       },
            { icon: 'mdi-history',        href:'/recent',    text: this.$t('index.allBooks'), },
            { icon: 'mdi-trending-up',    href:'/hot',       text: this.$t('index.hotRanking'), },
            ]
    },
    async asyncData({ app, res }) {
        if ( res !== undefined ) {
            res.setHeader('Cache-Control', 'no-cache');
        }
        return app.$backend("/index?random=12&recent=12");
    },
    data: () => ({
        random_books: [],
        new_books: [],
        navs: [],
        releaseNotesDialog: false,
        releaseNotesContent: '',
        countdown: 10,
        countdownTimer: null,
    }),
    head: () => ({
        titleTemplate: "%s",
    })
}
</script>

<style>
.new-legend {
    margin-top: 30px;
    margin-bottom: 20px;
}
.book-img-hover {
    transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}
.book-img-hover:hover {
    transform: scale(1.06);
    z-index: 2;
    box-shadow: 0 8px 24px rgba(0,0,0,0.18);
}
/* Release Notes Dialog card font size */
.release-notes-card {
    font-size: 16px;
}
/* Ensure close button text is also 16px */
.release-notes-card .v-btn {
    font-size: 16px !important;
}
</style>

