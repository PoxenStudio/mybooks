<template>
    <v-text-field
        dense
        outlined
        hide-details
        single-line
        v-model="searchText"
        :label="label || $t('appHeader.search')"
        @keyup.enter="doSearch"
        @click:append="doSearch"
        append-icon="mdi-magnify"
        class="search-bar"
    >
        <template v-if="categories && categories.length > 1" #prepend-inner>
            <v-menu
                v-model="menuOpen"
                :close-on-content-click="true"
                :nudge-width="130"
                offset-y
            >
                <template #activator="{ on, attrs }">
                    <v-btn
                        v-bind="attrs"
                        v-on="on"
                        text
                        small
                        class="search-bar__category-btn px-1 mr-1"
                        style="min-width: unset; height: 28px;"
                    >
                        {{ $t(currentCategoryLabel) }}
                        <v-icon small right>mdi-chevron-down</v-icon>
                    </v-btn>
                </template>
                <v-list dense>
                    <v-list-item
                        v-for="cat in categories"
                        :key="cat.value"
                        @click="selectCategory(cat.value)"
                        :class="{ 'primary--text font-weight-bold': cat.value === searchCategory }"
                    >
                        <v-list-item-title>{{ $t(cat.label) }}</v-list-item-title>
                    </v-list-item>
                </v-list>
            </v-menu>
            <!-- Subtle divider between category selector and text -->
            <v-divider vertical class="mx-1" style="height: 20px; align-self: center;" />
        </template>
    </v-text-field>
</template>

<script>
export default {
    name: 'SearchBar',

    props: {
        /**
         * Initial query text (supports v-model via `value`).
         */
        value: {
            type: String,
            default: '',
        },
        /**
         * Placeholder / label for the text field.
         */
        label: {
            type: String,
            default: '',
        },
        /**
         * Search category options. Each item: { value: String, label: String (i18n key) }.
         * When only one item is supplied (or prop is omitted) the category selector is hidden.
         */
        categories: {
            type: Array,
            default: () => [],
        },
        /**
         * Default selected category value.
         */
        defaultCategory: {
            type: String,
            default: 'all',
        },
        /**
         * The function called when the user submits a search.
         * Receives an object: { query: String, category: String, fullQuery: String }
         *   - query:     raw text the user typed
         *   - category:  currently selected category value
         *   - fullQuery: query prefixed with "category:" when a specific category is selected
         */
        searchFn: {
            type: Function,
            required: true,
        },
    },

    data() {
        return {
            searchText: this.value || '',
            searchCategory: this.defaultCategory,
            menuOpen: false,
        };
    },

    computed: {
        currentCategoryLabel() {
            if (!this.categories || this.categories.length === 0) return 'appHeader.searchAll';
            const found = this.categories.find(c => c.value === this.searchCategory);
            return found ? found.label : 'appHeader.searchAll';
        },
    },

    watch: {
        value(val) {
            this.searchText = val;
        },
        searchText(val) {
            this.$emit('input', val);
        },
    },

    methods: {
        selectCategory(value) {
            this.searchCategory = value;
            this.menuOpen = false;
        },

        doSearch() {
            const raw = this.searchText.trim();
            // Strip any existing category prefix before re-applying
            const CATEGORY_PREFIX_RE = /^[a-z_]+:/i;
            const query = raw.replace(CATEGORY_PREFIX_RE, '').trim();
            const hasSpecificCategory = this.searchCategory && this.searchCategory !== 'all';
            // 输入为空时不拼接分类前缀，避免传入 "title:" 这样的空查询
            const fullQuery = (hasSpecificCategory && query) ? `${this.searchCategory}:${query}` : query;

            this.searchFn({ query, category: this.searchCategory, fullQuery });
        },
    },
};
</script>

<style scoped>
.search-bar .search-bar__category-btn {
    text-transform: none;
    letter-spacing: 0;
    font-size: 0.85rem;
    opacity: 0.8;
}
.search-bar .search-bar__category-btn:hover {
    opacity: 1;
}
</style>
