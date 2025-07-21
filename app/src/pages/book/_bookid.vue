<template>
    <v-row align="start">
        <v-col cols="12">
            <v-dialog v-model="dialog_epub2audio" persistent width="300">
                <v-card>
                    <v-card-title class="">{{ $t('book.convertToAudio') }}</v-card-title>
                    <v-card-text>
                        <p>{{ $t('book.convertToAudioNote') }}</p>
                        <v-combobox
                            :items="voice_names"
                            outlined
                            dense
                            v-model="voice_name"
                            label="Voices"
                            auto-select-first
                            required
                        ></v-combobox>
                    </v-card-text>
                    <v-card-actions>
                        <v-btn color="" text @click="dialog_epub2audio = false">{{ $t('common.cancel') }}</v-btn>
                        <v-spacer></v-spacer>
                        <v-btn color="primary" text @click="sendto_kindle">{{ $t('common.start') }}</v-btn>
                    </v-card-actions>
                </v-card>
            </v-dialog>

            <v-dialog v-model="dialog_download" persistent width="300">
                <v-card>
                    <v-card-title color="primary" class="">{{ $t('book.downloadBook') }}</v-card-title>
                    <v-card-text>
                        <v-list v-if="book.files.length > 0">
                            <v-list-item :key="'file-'+file.format" v-for="file in book.files" target="_blank"
                                         :href="file.href">
                                <v-list-item-avatar color='primary'>
                                    <v-icon dark>get_app</v-icon>
                                </v-list-item-avatar>
                                <v-list-item-content>
                                    <v-list-item-title>{{ file.format }}</v-list-item-title>
                                    <v-list-item-subtitle v-if="file.size>=1048576">{{
                                            parseInt(file.size / 1048576)
                                        }}MB
                                    </v-list-item-subtitle>
                                    <v-list-item-subtitle v-else>{{
                                            parseInt(file.size / 1024)
                                        }}KB
                                    </v-list-item-subtitle>
                                </v-list-item-content>
                            </v-list-item>
                        </v-list>
                        <p v-else><br/>{{ $t('book.noDownloadableFiles') }}</p>
                    </v-card-text>
                    <v-card-actions>
                        <v-spacer></v-spacer>
                        <v-btn text @click="dialog_download = false">{{ $t('common.close') }}</v-btn>
                        <v-spacer></v-spacer>
                    </v-card-actions>
                </v-card>
            </v-dialog>

            <v-card v-if="dialog_refer">
                <v-toolbar flat dense dark color="primary">
                    {{ $t('book.syncBookInfo') }}
                    <v-spacer></v-spacer>
                    <v-btn outlined text @click="dialog_refer = false">{{ $t('common.cancel') }}</v-btn>
                </v-toolbar>
                <v-card-text xclass="pt-3 px-3 px-sm-6">
                    <p class="py-6 text-center" v-if="refer_books_loading">
                        <v-progress-circular indeterminate color="primary"></v-progress-circular>
                    </p>
                    <p class="py-6 text-center" v-else-if="refer_books.length === 0">{{ $t('book.noMatchingInfo') }}</p>
                    <template v-else>
                        <p>{{ $t('book.selectMatchingRecord') }}</p>
                        <book-cards :books="refer_books">
                            <template #actions="{ book }">
                                <v-card-actions>
                                    <v-chip class="mr-1" small v-if="book.author_sort">{{ book.author_sort }}</v-chip>
                                    <v-chip class="mr-1" small v-if="book.publisher">{{ book.publisher }}</v-chip>
                                    <v-chip small v-if="book.pubyear">{{ book.pubyear }}</v-chip>
                                </v-card-actions>
                                <v-divider></v-divider>
                                <v-card-actions>
                                    <v-chip
                                        small
                                        dark
                                        :href="book.website"
                                        target="__blank"
                                        :color="book.source === '豆瓣' ? 'green' : 'blue'"
                                    >{{ book.source }}
                                    </v-chip
                                    >
                                    <v-spacer></v-spacer>
                                    <v-menu offset-y right>
                                        <template v-slot:activator="{ on }">
                                            <v-btn color="primary" small rounded v-on="on"
                                                   :loading="refer_books_setting_btn_loading">
                                                <v-icon small>done</v-icon>
                                                {{ $t('common.set') }}
                                            </v-btn>
                                        </template>
                                        <v-list dense>
                                            <v-list-item @click="set_refer(book.provider_key, book.provider_value)">
                                                <v-list-item-title>{{ $t('book.setBookInfoAndImage') }}</v-list-item-title>
                                            </v-list-item>
                                            <v-list-item
                                                @click="set_refer(book.provider_key, book.provider_value, { only_meta: 'yes' })">
                                                <v-list-item-title>{{ $t('book.setBookInfoOnly') }}</v-list-item-title>
                                            </v-list-item>
                                            <v-list-item
                                                @click="set_refer(book.provider_key, book.provider_value, { only_cover: 'yes' })">
                                                <v-list-item-title>{{ $t('book.setBookImageOnly') }}</v-list-item-title>
                                            </v-list-item>
                                        </v-list>
                                    </v-menu>
                                </v-card-actions>
                            </template>
                        </book-cards>
                    </template>
                </v-card-text>
            </v-card>

            <v-card v-if="!dialog_refer">
                <v-toolbar flat dense>
                    <!-- download -->
                    <v-btn icon small fab @click="dialog_download = true">
                        <v-icon>get_app</v-icon>
                    </v-btn>
                    <v-btn class="d-none" icon small fab>
                        <v-icon>thumb_up</v-icon>
                    </v-btn>
                    <v-btn class="d-none" icon small fab>
                        <v-icon>share</v-icon>
                    </v-btn>

                    <v-spacer></v-spacer>
                    <v-btn :small="tiny" dark color="primary" class="mx-2 d-flex d-sm-flex"
                           @click="dialog_epub2audio = !dialog_epub2audio"
                    >
                        <v-icon left v-if="!tiny">audio</v-icon>
                        {{ $t('book.convertToAudio') }}
                    </v-btn
                    >
                    <v-btn :small="tiny" dark color="primary" class="mx-2 d-flex d-sm-flex" :href="'/read/' + book.id"
                           target="_blank">
                        <v-icon left v-if="!tiny">import_contacts</v-icon>
                        {{ $t('book.read') }}
                    </v-btn
                    >

                    <template v-if="book.is_owner">
                        <v-menu offset-y>
                            <template v-slot:activator="{ on }">
                                <v-btn v-on="on" dark color="primary" class="ml-2" :small="tiny"
                                >{{ $t('book.manage') }}
                                    <v-icon small>more_vert</v-icon>
                                </v-btn
                                >
                            </template>
                            <v-list>
                                <v-list-item :to="'/book/' + book.id + '/edit'">
                                    <v-icon>settings_applications</v-icon>
                                    {{ $t('book.editBookInfo') }}
                                </v-list-item>
                                <v-list-item @click="get_refer">
                                    <v-icon>apps</v-icon>
                                    {{ $t('book.updateInfoFromInternet') }}
                                </v-list-item>
                                <v-list-item @click="reset_refer">
                                    <v-icon>apps</v-icon>
                                    {{ $t('book.resetInfo') }}
                                </v-list-item>
                                <v-list-item @click="convert_book">
                                    <v-icon>mdi-swap-horizontal</v-icon>
                                    {{ $t('book.convert') }}
                                </v-list-item>
                                <v-divider></v-divider>
                                <v-list-item @click="set_sole">
                                    <v-icon>{{ book.sole ? 'public_off' : 'public' }}</v-icon>
                                    {{ book.sole ? $t('book.setPublic') : $t('book.setSole') }}
                                </v-list-item>
                                <v-list-item @click="delete_book">
                                    <v-icon>delete_forever</v-icon>
                                    {{ $t('book.deleteBook') }}
                                </v-list-item>
                            </v-list>
                        </v-menu>
                    </template>
                </v-toolbar>
                <v-row>
                    <v-col class="mx-auto" cols="8" sm="4">
                        <v-img class="book-img" :src="book.img" :aspect-ratio="11 / 15" max-height="500px"
                               contain></v-img>
                    </v-col>
                    <v-col cols="12" sm="8">
                        <v-card-text>
                            <div>
                                <p class='title mb-0'>{{ book.title }}</p>
                                <span color="grey--text">
                                    <v-icon :color="book.sole ? 'red' : 'green'" class="mr-2">
                                        {{ book.sole ? 'public_off' : 'public' }}
                                    </v-icon>
                                    {{ book.author }}{{ $t('book.author') }}，{{ pub_year }}{{ $t('book.year') }}
                                </span>
                                <span
                                    v-if='book.files.length>0 && book.files[0].format==="PDF" && book.files[0].size >= 1048576'
                                    color="grey--text" style="font-weight: bold">&nbsp;&nbsp;&nbsp;[{{ $t('book.fileFormat') }}: PDF - {{
                                        parseInt(book.files[0].size / 1048576)
                                    }}MB]
                                </span>
                                <span
                                    v-else-if='book.files.length>0 && book.files[0].format==="PDF" && book.files[0].size < 1048576'
                                    color="grey--text" style="font-weight: bold">&nbsp;&nbsp;&nbsp;[{{ $t('book.fileFormat') }}: PDF - {{
                                        parseInt(book.files[0].size / 1024)
                                    }}KB]
                                </span>
                            </div>
                            <v-rating v-model="book.rating" color="yellow accent-4" length="10" readonly dense
                                      small></v-rating>
                            <br/>
                            <div class="tag-chips">
                                <template v-for="author in book.authors">
                                    <v-chip
                                        rounded
                                        small
                                        dark
                                        color="indigo"
                                        :to="'/author/' + encodeURIComponent(author)"
                                        :key="'author-' + author"
                                    >
                                        <v-icon>face</v-icon>
                                        {{ author }}
                                    </v-chip>
                                </template>
                                <v-chip rounded small dark color="indigo"
                                        :to="'/publisher/' + encodeURIComponent(book.publisher)">
                                    <v-icon>group</v-icon>
                                    {{ $t('book.publisher') }}：{{ book.publisher }}
                                </v-chip>
                                <v-chip
                                    rounded
                                    small
                                    dark
                                    color="indigo"
                                    v-if="book.series"
                                    :to="'/series/' + encodeURIComponent(book.series)"
                                >
                                    <v-icon>explore</v-icon>
                                    {{ $t('book.series') }}: {{ book.series }}
                                </v-chip>
                                <v-chip rounded small dark color="grey" v-if="book.isbn">
                                    <v-icon>explore</v-icon>
                                    ISBN：{{ book.isbn }}
                                </v-chip>
                                <template v-for="tag in book.tags">
                                    <v-chip
                                        rounded
                                        small
                                        dark
                                        color="grey"
                                        :key="'tag-' + tag"
                                        v-if="tag"
                                        :to="'/tag/' + encodeURIComponent(tag)"
                                    >
                                        <v-icon>loyalty</v-icon>
                                        {{ tag }}
                                    </v-chip>
                                </template>
                            </div>
                        </v-card-text>
                        <v-card-text>
                            <p v-if="book.comments" v-html="book.comments"></p>
                            <p v-else>{{ $t('book.clickToViewDetails') }}</p>
                        </v-card-text>
                    </v-col>
                </v-row>
                <v-card-text class="align-right book-footer">
                    <span class="grey--text"> {{ book.collector }} @ {{ book.timestamp }} </span>
                </v-card-text>
            </v-card>
        </v-col>
        <v-col cols="12" :sm="is_txt?6:5" :md="is_txt?3:4">
            <v-card outlined>
                <v-list>
                    <v-list-item :href="'/read/' + book.id" target="_blank">
                        <v-list-item-avatar large color="primary">
                            <v-icon dark>import_contacts</v-icon>
                        </v-list-item-avatar>
                        <v-list-item-content>
                            <v-list-item-title>{{ $t('book.onlineReading') }}</v-list-item-title>
                        </v-list-item-content>
                        <v-list-item-action>
                            <v-icon>mdi-arrow-right</v-icon>
                        </v-list-item-action>
                    </v-list-item>
                </v-list>
            </v-card>
        </v-col>
        <v-col cols="12" sm="5" md="3" v-show="is_txt">
          <v-card outlined>
            <v-list>
              <v-list-item :href="'/book/' + book.id+'/readtxt'" target="_blank">
                <v-list-item-avatar large color="primary">
                  <v-icon dark>import_contacts</v-icon>
                </v-list-item-avatar>
                <v-list-item-content>
                  <v-list-item-title>{{ $t('book.txtOnlineReading', { status: txt_parse_inited ? $t('book.parsed') : $t('book.notParsed') }) }}</v-list-item-title>
                </v-list-item-content>
                <v-list-item-action>
                  <v-icon>mdi-arrow-right</v-icon>
                </v-list-item-action>
              </v-list-item>
            </v-list>
          </v-card>
        </v-col>
        <v-col cols="12" :sm="is_txt?6:5" :md="is_txt?3:4">
            <v-card outlined>
                <v-list>
                    <v-list-item @click="dialog_download = !dialog_download">
                        <v-list-item-avatar large color="primary">
                            <v-icon dark>get_app</v-icon>
                        </v-list-item-avatar>
                        <v-list-item-content>
                            <v-list-item-title>{{ $t('book.download') }}</v-list-item-title>
                        </v-list-item-content>
                        <v-list-item-action>
                            <v-icon>mdi-arrow-right</v-icon>
                        </v-list-item-action>
                    </v-list-item>
                </v-list>
            </v-card>
        </v-col>
        <v-col cols="12" :sm="is_txt?6:5" :md="is_txt?3:4">
            <v-card outlined>
                <v-list>
                    <v-list-item @click="dialog_epub2audio = !dialog_epub2audio">
                        <v-list-item-avatar large color="primary">
                            <v-icon dark>audiotrack</v-icon>
                        </v-list-item-avatar>
                        <v-list-item-content>
                            <v-list-item-title>{{ $t('book.convertToAudio') }}</v-list-item-title>
                        </v-list-item-content>
                        <v-list-item-action>
                            <v-icon>mdi-arrow-right</v-icon>
                        </v-list-item-action>
                    </v-list-item>
                </v-list>
            </v-card>
        </v-col>
    </v-row>
</template>

<script>
import BookCards from "~/components/BookCards.vue";

export default {
    components: {
        BookCards,
    },
    computed: {
        is_txt(){
          if(!this.book)return false
          let formats=this.book.files.map(x=>x.format.toLowerCase())
          return formats.includes("txt")
        },
        pub_year: function () {
            if (this.book === null || this.book.pubdate == null) {
                return "N/A";
            }
            return this.book.pubdate.split("-")[0];
        },
        tiny: function () {
            return this.$vuetify.breakpoint.xsOnly;
        }
    },
    data: () => ({
        err: "",
        msg: "",
        book: {id: 0, title: "", files: [], tags: [], pubdate: ""},
        debug: false,
        mail_to: "",
        kindle_sender: "",
        txt_parse_inited: false,
        dialog_download: false,
        dialog_epub2audio: false,
        dialog_refer: false,
        dialog_msg: false,
        refer_books_loading: false,
        refer_books_setting_btn_loading:false,
        refer_books: [],
        email_rules: function (email) {
            var re = /^(([^<>()[\]\\.,;:\s@"]+(\.[^<>()[\]\\.,;:\s@"]+)*)|(".+"))@((\[[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\])|(([a-zA-Z\-0-9]+\.)+[a-zA-Z]{2,}))$/;
            return (email !== this.kindle_sender && re.test(email)) || "Invalid email format";
        },
    }),
    async asyncData({params, app, res}) {
        if (res !== undefined) {
            res.setHeader("Cache-Control", "no-cache");
        }
        return app.$backend(`/book/${params.bookid}`);
    },
    head() {
        return {
            title: this.book.title,
        };
    },
    created() {
        this.init(this.$route);
        this.mail_to = this.$store.state.user.kindle_email;
        this.get_txt_parse_status()
        if (process.client) {
            this.mail_to = this.$cookies.get("last_mailto");
        }
    },
    beforeRouteUpdate(to, from, next) {
        this.init(to, next);
    },
    methods: {
        init(route, next) {
            this.$store.commit("navbar", true);
            var rsp = this;
            if (rsp.err !== "ok") {
                this.$alert("error", rsp.msg, "/");
            }
            if (next) next();
        },
        sendto_kindle() {
            if (process.client) {
                this.$cookies.set("last_mailto", this.mail_to);
            }
            this.$backend("/book/" + this.book.id + "/push", {
                method: "POST",
                body: "mail_to=" + this.mail_to,
                headers: {
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            }).then((rsp) => {
                this.dialog_epub2audio = false;
                if (rsp.err === "ok") {
                    this.$alert("success", rsp.msg, "#");
                } else {
                    this.$alert("error", rsp.msg, "#");
                }
            });
        },
        get_txt_parse_status(){
          this.$backend(`/book/txt/init?id=${this.book.id}&test=1`,)
            .then(res => {
              if (res.err === "ok" && res.msg === "已解析") {
                this.txt_parse_inited = true;
              }
            })
        },
        get_refer() {
            this.dialog_refer = true;
            this.refer_books_loading = true;
            this.$backend("/book/" + this.book.id + "/refer")
                .then((rsp) => {
                    this.refer_books = rsp.books.map((b) => {
                        b.href = "";
                        b.img = "/get/pcover?url=" + encodeURIComponent(b.cover_url);
                        return b;
                    });
                })
                .finally(() => {
                    this.refer_books_loading = false;
                });
        },
        set_refer(provider_key, provider_value, opt) {
            // 防止多次重复点击
            if(this.refer_books_setting_btn_loading) return;
            // 显示加载条提示
            this.refer_books_setting_btn_loading = true;
            var data = new URLSearchParams(opt);
            data.append("provider_key", provider_key);
            data.append("provider_value", provider_value);
            this.$backend("/book/" + this.book.id + "/refer", {
                method: "POST",
                body: data,
            }).then((rsp) => {
                this.dialog_refer = false;
                if (rsp.err === "ok") {
                    this.$router.push("/book/" + this.book.id);
                    location.reload();
                    this.$alert("success", "设置成功！");
                } else {
                    this.$alert("error", rsp.msg);
                }
                this.init(this.$route);
            }).finally(()=>{
               //关闭加载条提示
               this.refer_books_setting_btn_loading = false;
            });
        },
        reset_refer() {
            // 使用本地书籍信息覆盖
            this.$backend("/book/" + this.book.id + "/refer", {
                method: "POST",
                body: new URLSearchParams({reset: "yes"}),
            }).then((rsp) => {
                if (rsp.err === "ok") {
                    this.$alert("success", this.$t('book.resetSuccessful'));
                    this.$router.push("/book/" + this.book.id);
                    location.reload();
                } else {
                    this.$alert("error", rsp.msg);
                }
            });
        },
        convert_book() {
            this.$backend("/book/" + this.book.id + "/convert", {
                method: "POST",
                body: new URLSearchParams({reset: "yes"}),
            }).then((rsp) => {
                if (rsp.err === "ok") {
                    this.$alert("success", this.$t('book.convertSuccessful'));
                    this.$router.push("/book/" + this.book.id);
                } else {
                    this.$alert("error", rsp.msg);
                }
            });
        },
        set_sole() {
            this.$backend("/book/" + this.book.id + "/setsole", {
                method: "POST",
            }).then((rsp) => {
                if (rsp.err === "ok") {
                    this.$alert("success", "设置成功");
                    this.$router.push("/book/" + this.book.id);
                    location.reload();
                } else {
                    this.$alert("error", rsp.msg);
                }
            });
        },
        delete_book() {
            this.$backend("/book/" + this.book.id + "/delete", {
                method: "POST",
            }).then((rsp) => {
                if (rsp.err === "ok") {
                    this.$alert("success", "删除成功");
                    this.$router.push("/");
                } else {
                    this.$alert("error", rsp.msg);
                }
            });
        },
        check_proxy_address(address) {
            // address should be valid ip(v4/v6) address or host uri, the port is optional. Ex: <ip>:<port>, <host>:<port>, <ip>, <host>
            if (!address || address.trim() === '') {
                return "代理地址不能为空";
            }

            // Split address and port
            let host, port;
            if (address.includes('[') && address.includes(']')) {
                // IPv6 with port: [::1]:8080
                const match = address.match(/^\[(.+)\]:(\d+)$/) || address.match(/^\[(.+)\]$/);
                if (match) {
                    host = match[1];
                    port = match[2];
                } else {
                    return "IPv6地址格式错误";
                }
            } else if (address.includes(':')) {
                // IPv4:port or host:port
                const parts = address.split(':');
                if (parts.length === 2) {
                    host = parts[0];
                    port = parts[1];
                } else {
                    return "地址格式错误";
                }
            } else {
                // Just host or IP
                host = address;
            }

            // Validate port if present
            if (port !== undefined) {
                const portNum = parseInt(port);
                if (isNaN(portNum) || portNum < 1 || portNum > 65535) {
                    return "端口号必须在1-65535之间";
                }
            }

            // IPv4 regex
            const ipv4Regex = /^(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$/;

            // IPv6 regex (simplified)
            const ipv6Regex = /^([0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}$|^::1$|^::$|^([0-9a-fA-F]{1,4}:){1,7}:$|^([0-9a-fA-F]{1,4}:){1,6}:[0-9a-fA-F]{1,4}$|^([0-9a-fA-F]{1,4}:){1,5}(:[0-9a-fA-F]{1,4}){1,2}$|^([0-9a-fA-F]{1,4}:){1,4}(:[0-9a-fA-F]{1,4}){1,3}$|^([0-9a-fA-F]{1,4}:){1,3}(:[0-9a-fA-F]{1,4}){1,4}$|^([0-9a-fA-F]{1,4}:){1,2}(:[0-9a-fA-F]{1,4}){1,5}$|^[0-9a-fA-F]{1,4}:((:[0-9a-fA-F]{1,4}){1,6})$|^:((:[0-9a-fA-F]{1,4}){1,7}|:)$/;

            // Hostname regex (allows domain names and localhost)
            const hostnameRegex = /^([a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)*[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?$|^localhost$/;

            if (ipv4Regex.test(host) || ipv6Regex.test(host) || hostnameRegex.test(host)) {
                return true;
            }

            return "请输入有效的IP地址或主机名";
        }
    },
};
</script>

<style>
.book-img {
    /*
    margin-left: 16px;
    box-shadow: 1px 1px 1px rgba(0,0,0,0.12);
    box-shadow: 0px 3px 1px -2px rgba(0,0,0,0.2), 0px 2px 2px 0px rgba(0,0,0,0.14), 0px 1px 5px 0px rgba(0,0,0,0.12);
    */
}

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

.book-comments {
    /*text-indent: 2em;*/
    overflow: hidden;
    display: -webkit-box;
    -webkit-line-clamp: 3;
    -webkit-box-orient: vertical;
    text-overflow: clip;
    margin-top: 6px;
    text-align: left;
}

.book-comments p {
    font-size: small;
    margin-bottom: 0;
}

h1.book-detail-title {
    line-height: inherit;
}
</style>
