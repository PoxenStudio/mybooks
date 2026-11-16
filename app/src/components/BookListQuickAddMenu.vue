<template>
    <div class="d-inline-block">
        <v-menu v-model="menu" :close-on-content-click="false" offset-y @input="onMenuToggle">
            <template v-slot:activator="{ on, attrs }">
                <slot name="activator" :on="on" :attrs="attrs">
                    <v-btn icon v-bind="attrs" v-on="on" :aria-label="$t('booklist.addToBooklist')">
                        <v-icon>mdi-playlist-plus</v-icon>
                    </v-btn>
                </slot>
            </template>

            <v-card min-width="280" max-width="320">
                <v-card-text class="pb-1">
                    <v-text-field
                        v-model="filter"
                        :placeholder="$t('booklist.filterMyBooklists')"
                        hide-details
                        dense
                        clearable
                    ></v-text-field>
                </v-card-text>
                <v-progress-circular v-if="loading" indeterminate color="primary" size="24" class="d-block mx-auto my-4"></v-progress-circular>
                <v-list v-else dense max-height="260" style="overflow-y: auto">
                    <v-list-item v-if="filteredBooklists.length === 0">
                        <v-list-item-title class="grey--text">{{ $t('booklist.noMatchingBooklists') }}</v-list-item-title>
                    </v-list-item>
                    <v-list-item v-for="b in filteredBooklists" :key="b.id" @click="toggle(b)">
                        <v-list-item-icon>
                            <v-icon small :color="b.contains_book ? 'primary' : undefined">
                                {{ b.contains_book ? 'mdi-checkbox-marked' : 'mdi-checkbox-blank-outline' }}
                            </v-icon>
                        </v-list-item-icon>
                        <v-list-item-title class="text-truncate">{{ b.name }}</v-list-item-title>
                        <v-icon v-if="!b.is_public" x-small color="grey">mdi-lock-outline</v-icon>
                    </v-list-item>
                </v-list>
                <v-divider></v-divider>
                <v-list dense>
                    <v-list-item @click="createDialog = true">
                        <v-list-item-icon><v-icon small color="primary">mdi-plus</v-icon></v-list-item-icon>
                        <v-list-item-title class="primary--text">{{ $t('booklist.createAndAdd') }}</v-list-item-title>
                    </v-list-item>
                </v-list>
            </v-card>
        </v-menu>

        <BookListEditDialog v-model="createDialog" mode="create" @saved="onCreated" />
    </div>
</template>

<script>
import BookListEditDialog from '~/components/BookListEditDialog.vue';

export default {
    name: 'BookListQuickAddMenu',
    components: { BookListEditDialog },
    props: {
        bookId: { type: [Number, String], required: true },
    },
    data() {
        return {
            menu: false,
            loading: false,
            filter: '',
            booklists: [],
            createDialog: false,
        };
    },
    computed: {
        filteredBooklists() {
            const kw = (this.filter || '').trim().toLowerCase();
            if (!kw) return this.booklists;
            return this.booklists.filter(b => b.name.toLowerCase().includes(kw));
        },
    },
    methods: {
        onMenuToggle(open) {
            if (open) this.fetchBooklists();
        },
        async fetchBooklists() {
            this.loading = true;
            try {
                const rsp = await this.$backend(`/book/${this.bookId}/booklists`);
                this.booklists = (rsp && rsp.booklists) || [];
            } catch (e) {
                this.$alert('error', this.$t('message.networkError'));
            } finally {
                this.loading = false;
            }
        },
        async toggle(b) {
            const wasIn = b.contains_book;
            b.contains_book = !wasIn;
            try {
                const url = wasIn ? `/booklist/${b.id}/books/remove` : `/booklist/${b.id}/books/add`;
                const rsp = await this.$backend(url, { method: 'POST', body: JSON.stringify({ book_id: this.bookId }) });
                if (rsp.err !== 'ok') {
                    b.contains_book = wasIn;
                    this.$alert('error', rsp.msg || this.$t('message.operationFailed'));
                }
            } catch (e) {
                b.contains_book = wasIn;
                this.$alert('error', this.$t('message.networkError'));
            }
        },
        async onCreated(booklist) {
            if (!booklist) return;
            try {
                const rsp = await this.$backend(`/booklist/${booklist.id}/books/add`, {
                    method: 'POST',
                    body: JSON.stringify({ book_id: this.bookId }),
                });
                if (rsp.err === 'ok') {
                    this.$alert('success', this.$t('booklist.createdAndAdded'));
                    await this.fetchBooklists();
                } else {
                    this.$alert('error', rsp.msg || this.$t('message.operationFailed'));
                }
            } catch (e) {
                this.$alert('error', this.$t('message.networkError'));
            }
        },
    },
};
</script>
