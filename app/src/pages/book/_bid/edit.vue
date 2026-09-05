<template>
    <v-row align=start>
        <v-col cols=12>
            <v-card>
                <v-toolbar dark color="primary">
                    <v-toolbar-title align-center>{{ $t('book.edit.title') }}</v-toolbar-title>
                    <v-spacer></v-spacer>
                    <v-btn class='mr-2' color='red' :to="'/book/'+book.id">{{ $t('book.edit.cancel') }}</v-btn>
                    <v-btn color='green' @click="save_book">{{ $t('book.edit.save') }}</v-btn>
                </v-toolbar>
                <v-card-text class="pa-0 pa-md-2">
                    <v-form>
                        <v-container>
                            <v-row>
                                <v-col class='py-0' cols=12 sm=6>
                                    <v-text-field :label="$t('book.edit.fields.title')" v-model="book.title">{{ book.title }}</v-text-field>
                                </v-col>
                                <v-col class='py-4' cols=12 sm=6>
                                    <v-rating :label="$t('book.edit.fields.rating')" v-model="ratingStars" color="yellow accent-4" length="5"
                                              dense></v-rating>
                                </v-col>
                                <v-col class='py-0' cols=12 sm=6>
                                    <!-- AUTHORS -->
                                    <v-combobox v-model="book.authors" :items="authorNames" :label="$t('book.edit.fields.authors.label')"
                                                :search-input.sync="author_input" :loading="authors_loading"
                                                hide-selected multiple small-chips>
                                        <template v-slot:no-data>
                                            <v-list-item>
                                                <span v-if="! author_input">{{ $t('book.edit.fields.authors.noData') }}</span>
                                                <div v-else>
                                                    <span class="subheading">{{ $t('book.edit.fields.authors.add') }}</span>
                                                    <v-chip color="green lighten-3" label small rounded> {{
                                                            author_input
                                                        }}
                                                    </v-chip>
                                                </div>
                                            </v-list-item>
                                        </template>
                                        <!-- author chip & close -->
                                        <template v-slot:selection="{ attrs, item, parent, selected }">
                                            <v-chip v-bind="attrs" color="green lighten-3" :input-value="selected" label
                                                    small>
                                                <span class="pr-2"> {{ item }} </span>
                                                <v-icon small @click="parent.selectItem(item)">mdi-close</v-icon>
                                            </v-chip>
                                        </template>
                                    </v-combobox>
                                </v-col>
                                <v-col class='py-0' cols=12 sm=6>
                                    <!-- TRANSLATORS -->
                                    <v-combobox v-model="book.translators" :items="book.translators" :label="$t('book.edit.fields.translators')"
                                                :search-input.sync="translator_input" hide-selected multiple small-chips>
                                        <template v-slot:no-data>
                                            <v-list-item>
                                                <span v-if="! translator_input">{{ $t('book.edit.fields.authors.noData') }}</span>
                                                <div v-else>
                                                    <span class="subheading">{{ $t('book.edit.fields.authors.add') }}</span>
                                                    <v-chip color="green lighten-3" label small rounded> {{translator_input}}</v-chip>
                                                </div>
                                            </v-list-item>
                                        </template>
                                        <template v-slot:selection="{ attrs, item, parent, selected }">
                                            <v-chip v-bind="attrs" color="green lighten-3" :input-value="selected" label small>
                                                <span class="pr-2"> {{ item }} </span>
                                                <v-icon small @click="parent.selectItem(item)">mdi-close</v-icon>
                                            </v-chip>
                                        </template>
                                    </v-combobox>
                                </v-col>
                                <v-col class='py-0' cols=8 sm=4>
                                    <v-text-field :label="$t('book.edit.fields.series')" v-model="book.series">{{ book.series }}</v-text-field>
                                </v-col>
                                <v-col class='py-0' cols=4 sm=2>
                                    <v-text-field
                                        :label="$t('book.edit.fields.series_index')"
                                        :disabled="!book.series"
                                        v-model="book.series_index"
                                        type="text"
                                        inputmode="decimal"
                                        pattern="^\\d+(\\.\\d{0,2})?$"
                                        @input="onSeriesIndexInput"
                                        @blur="onSeriesIndexBlur"
                                    ></v-text-field>
                                </v-col>
                                <v-col class='py-0' cols=12 sm=6>
                                    <v-combobox
                                        :label="$t('book.edit.fields.publisher')"
                                        v-model="book.publisher"
                                        :items="publisherNames"
                                        :search-input.sync="publisher_input"
                                        :loading="publishers_loading"
                                        clearable
                                        hide-no-data
                                        :filter="publisherFilter"
                                    ></v-combobox>
                                </v-col>
                                <v-col class='py-0' cols=12 sm=3>
                                    <v-text-field :label="$t('book.edit.fields.pubdate')" v-model="book.pubdate">{{ book.pubdate }}</v-text-field>
                                </v-col>
                                <v-col class='py-0' cols=12 sm=3>
                                    <v-select
                                        :label="$t('book.edit.fields.language')"
                                        v-model="book.languages"
                                        :items="languageOptions"
                                        item-text="name"
                                        item-value="code"
                                        :return-object="false"
                                        :menu-props="{ maxHeight: '300px' }"
                                        clearable
                                    >
                                    </v-select>
                                </v-col>
                                <v-col class='py-0' cols=12 sm=6>
                                    <v-text-field :label="$t('book.edit.fields.isbn')" v-model="book.isbn">{{ book.isbn }}</v-text-field>
                                </v-col>
                                <v-col class='py-0' cols=12 sm=4 v-if="book.book_type === 1">
                                    <v-text-field :label="$t('book.edit.fields.location')" v-model="book.location">{{ book.location }}</v-text-field>
                                </v-col>
                                <v-col class='py-0' cols=12 sm=2 v-if="book.book_type === 1">
                                    <v-text-field
                                        :label="$t('book.edit.fields.book_count')"
                                        :disabled="book.book_type != 1"
                                        v-model="book.book_count"
                                        type="text"
                                        inputmode="numeric"
                                        pattern="^\\d+$"
                                        @input="onSeriesIndexInput"
                                        @blur="onSeriesIndexBlur"
                                    ></v-text-field>
                                </v-col>
                                <v-col class='py-0' cols=12 sm=6>
                                    <!-- TAGS -->
                                    <v-combobox v-model="book.tags" :items="tagNames" :label="$t('book.edit.fields.tags.label')"
                                                :search-input.sync="tag_input" :loading="tags_loading" :filter="tagFilter"
                                                hide-selected multiple small-chips>
                                        <template v-slot:no-data>
                                            <v-list-item>
                                                <span v-if="!tag_input">{{ $t('book.edit.fields.tags.noData') }}</span>
                                                <div v-else>
                                                    <span class="subheading">{{ $t('book.edit.fields.tags.add') }}</span>
                                                    <v-chip color="green lighten-3" label small rounded>
                                                        {{tag_input}}
                                                    </v-chip>
                                                </div>
                                            </v-list-item>
                                        </template>
                                        <!-- tag chip & close -->
                                        <template v-slot:selection="{ attrs, item, parent, selected }">
                                            <v-chip v-bind="attrs" color="green lighten-3" :input-value="selected" label
                                                    small>
                                                <span class="pr-2"> {{ item }} </span>
                                                <v-icon small @click="parent.selectItem(item)">mdi-close</v-icon>
                                            </v-chip>
                                        </template>
                                    </v-combobox>
                                </v-col>
                                <v-col class='py-0' cols=12 sm=6>
                                    <v-text-field
                                        :label="$t('book.edit.fields.ext_link')"
                                        v-model="book.ext_link"
                                        :rules="[v => !v || /^https?:\/\/.+/.test(v) || $t('book.edit.fields.ext_link_invalid')]"
                                    >{{ book.ext_link }}</v-text-field>
                                </v-col>
                                <v-col class='py-0' cols="12">
                                    <v-textarea small outlined rows="15" :label="$t('book.edit.fields.comments')" v-model="book.comments"
                                                :value="book.comments"></v-textarea>
                                </v-col>
                                <v-divider></v-divider>
                                <v-col align=center cols="12">
                                    <v-btn dark color='green' @click='save_book'>{{ $t('book.edit.save') }}</v-btn>
                                </v-col>
                            </v-row>
                        </v-container>

                    </v-form>
                </v-card-text>
            </v-card>
        </v-col>
    </v-row>
</template>

<script>
import { languageOptions } from "~/utils/languageCodes";
import { toStars, fromStars } from "~/utils/rating";

export default {
    components: {},
    data: () => ({
        bookid: 0,
        book: {'id': 0, 'files': [], 'tags': [], 'pubdate': ''},
        author_input: null,
        tag_input: null,
        publisher_input: null,
        publishers: [],
        publishers_loading: false,
        tags_list: [],
        tags_loading: false,
        authors_list: [],
        authors_loading: false,
        author_search_timer: null,
        debug: false,
        mail_to: "",
        dialog_kindle: false,
        dialog_msg: false,
        alert_msg: "please login",
        alert_type: "error",
        languageOptions: languageOptions,
        cameFromBookDetail: false,
    }),
    computed: {
        pub_year: function () {
            if (this.book === null) {
                return "";
            }
            return this.book.pubdate.split("-")[0];
        },
        publisherNames() {
            return this.publishers.map(p => p.name);
        },
        tagNames() {
            return this.tags_list.map(t => t.name);
        },
        authorNames() {
            return this.authors_list.map(a => a.name);
        },
        ratingStars: {
            get() {
                return toStars(this.book.rating);
            },
            set(stars) {
                this.book.rating = fromStars(stars);
            },
        },
    },
    watch: {
        author_input(val) {
            if (this.author_search_timer) clearTimeout(this.author_search_timer);
            this.author_search_timer = setTimeout(() => {
                this.searchAuthors(val || '');
            }, 300);
        },
    },
    async mounted() {
        this.publishers_loading = true;
        this.tags_loading = true;
        try {
            const [pubRsp, tagRsp] = await Promise.all([
                this.$backend('/publisher'),
                this.$backend('/tag'),
                this.searchAuthors(''),
            ]);
            if (pubRsp && pubRsp.items) {
                this.publishers = pubRsp.items.slice(0, 100);
            }
            if (tagRsp && tagRsp.items) {
                this.tags_list = tagRsp.items.slice(0, 100);
            }
        } catch (e) {
            // ignore
        } finally {
            this.publishers_loading = false;
            this.tags_loading = false;
        }
    },
    async asyncData({params, app, res}) {
        if (res !== undefined) {
            res.setHeader('Cache-Control', 'no-cache');
        }
        return app.$backend("/book/" + params.bid);
    },
    head() {
        return {
            title: "编辑 " + this.book.title,
        }
    },
    created() {
        //this.$store.commit('navbar', true);
        //this.init(this.$route);
    },
    beforeRouteEnter(to, from, next) {
        next(vm => {
            vm.cameFromBookDetail = from.path === "/book/" + to.params.bid;
        });
    },
    beforeRouteUpdate(to, from, next) {
        this.init(to, next);
    },
    methods: {
        init(route, next) {
            //this.$store.commit('navbar', true);
            this.bookid = this.$route.params.bid;
            this.$backend("/book/" + this.bookid)
                .then(rsp => {
                    this.book = rsp.book;
                });
            if (next) next();
        },
        save_book() {
            this.saving = true;
            this.$backend("/book/" + this.book.id + "/edit", {
                method: "POST",
                body: JSON.stringify(this.book),
            })
                .then(rsp => {
                    if (rsp.err === 'ok') {
                        this.$alert("success", this.$t('book.edit.saveSuccess'));
                        if (this.cameFromBookDetail) {
                            this.$router.back();
                        } else {
                            this.$router.push("/book/" + this.book.id);
                        }
                    } else {
                        this.$alert("error", rsp.msg);
                    }
                });
        },
        publisherFilter(item, queryText) {
            return item.toLowerCase().includes(queryText.toLowerCase());
        },
        tagFilter(item, queryText) {
            return item.toLowerCase().includes(queryText.toLowerCase());
        },
        async searchAuthors(q) {
            this.authors_loading = true;
            try {
                const rsp = await this.$backend('/authors/search?q=' + encodeURIComponent(q) + '&limit=100');
                if (rsp && rsp.err === 'ok') {
                    this.authors_list = rsp.authors || [];
                }
            } catch (e) {
                // ignore, 保留上一次的查询结果
            } finally {
                this.authors_loading = false;
            }
        },
        languageName(code) {
            const found = this.languageOptions.find(opt => opt.code === code);
            return found ? found.name : code;
        },
        onSeriesIndexInput(value) {
            if (value === null || value === undefined) {
                this.book.series_index = "";
                return;
            }
            let sanitized = String(value).replace(/[^\d.]/g, "");
            if (sanitized.startsWith(".")) {
                sanitized = "0" + sanitized;
            }
            const parts = sanitized.split(".");
            const integerPart = parts[0] || "";
            const decimalPart = parts.slice(1).join("").slice(0, 2);
            this.book.series_index = decimalPart ? `${integerPart}.${decimalPart}` : integerPart;
        },
        onSeriesIndexBlur() {
            const value = this.book.series_index;
            if (value === "" || value === null || value === undefined) {
                return;
            }
            const num = Number(value);
            if (Number.isNaN(num)) {
                this.book.series_index = "";
                return;
            }
            this.book.series_index = num.toFixed(2);
        },
    },
}
</script>

<style>
.align-right {
    text-align: right;
}

.book-footer {
    padding-top: 0;
    padding-bottom: 3px;
}

.tag-chips a {
    margin: 4px 2px;
}
</style>