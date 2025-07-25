<template>
    <v-row align="start">
        <v-col cols="12">
            <v-dialog v-model="dialog_epub2audio" persistent width="380">
                <v-card>
                    <v-card-title class="">{{ $t('book.convertToAudio') }}</v-card-title>
                    <v-card-text>
                        <p>{{ $t('book.convertToAudioNote') }}</p>
                        <v-select
                            :items="voice_options"
                            outlined
                            dense
                            v-model="voice_name"
                            label="选择声音"
                            item-text="display_name"
                            item-value="voice_name"
                            required
                        >
                            <template v-slot:selection="{ item }">
                                {{ item.display_name }}
                            </template>
                            <template v-slot:item="{ item }">
                                <v-list-item-content>
                                    <v-list-item-title>{{ item.display_name }}</v-list-item-title>
                                </v-list-item-content>
                                <v-list-item-action>
                                    <v-btn
                                        icon
                                        small
                                        @click.stop="play_sample_voice(item)"
                                        :loading="playing_sample === item.voice_name"
                                    >
                                        <v-icon>play_arrow</v-icon>
                                    </v-btn>
                                </v-list-item-action>
                            </template>
                        </v-select>
                    </v-card-text>
                    <v-card-actions>
                        <v-btn color="" text @click="dialog_epub2audio = false">{{ $t('common.cancel') }}</v-btn>
                        <v-spacer></v-spacer>
                        <v-btn color="primary" text @click="generate_audio">{{ $t('common.start') }}</v-btn>
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
        audios: {count: 0, files: [], status: "ok"},
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
        voice_name: "zh-CN-XiaoxiaoNeural", // 默认选择小晓
        playing_sample: null,
        currentAudio: null,
        voice_options: [
            {
                voice_name: "zh-CN-liaoning-XiaobeiNeural",
                display_name: "女声 | 晓北（辽宁）",
                gender: "female",
                sample_file: "female/zh-CN-liaoning-XiaobeiNeural.mp3"
            },
            {
                voice_name: "zh-CN-XiaoxiaoNeural",
                display_name: "女声 | 晓晓",
                gender: "female",
                sample_file: "female/zh-CN-XiaoxiaoNeural.mp3"
            },
            {
                voice_name: "zh-CN-XiaoyiNeural",
                display_name: "女声 | 晓伊",
                gender: "female",
                sample_file: "female/zh-CN-XiaoyiNeural.mp3"
            },
            {
                voice_name: "zh-HK-HiuGaaiNeural",
                display_name: "女声 | 晓佳（香港）",
                gender: "female",
                sample_file: "female/zh-HK-HiuGaaiNeural.mp3"
            },
            {
                voice_name: "zh-CN-YunjianNeural",
                display_name: "男声 | 云健",
                gender: "male",
                sample_file: "male/zh-CN-YunjianNeural.mp3"
            },
            {
                voice_name: "zh-CN-YunxiNeural",
                display_name: "男声 | 云希",
                gender: "male",
                sample_file: "male/zh-CN-YunxiNeural.mp3"
            },
            {
                voice_name: "zh-CN-YunyangNeural",
                display_name: "男声 | 云扬",
                gender: "male",
                sample_file: "male/zh-CN-YunyangNeural.mp3"
            },
            {
                voice_name: "zh-HK-WanLungNeural",
                display_name: "男声 | 云龙（香港）",
                gender: "male",
                sample_file: "male/zh-HK-WanLungNeural.mp3"
            }
        ],
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
    beforeDestroy() {
        // 清理音频资源
        this.stop_current_audio();
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
        generate_audio() {
            this.$backend(`/audio/${this.book.id}/conversion`, {
                method: "POST",
                body: JSON.stringify({voice: this.voice_name}),
            }).then((rsp) => {
                if (rsp.err === "ok") {
                    this.$alert("success", this.$t('book.audioGenerated'));
                } else {
                    this.$alert("error", rsp.msg);
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
        play_sample_voice(voice_option) {
            if (this.playing_sample === voice_option.voice_name) {
                // 如果正在播放相同的样本，则停止播放
                this.stop_current_audio();
                return;
            }

            // 停止当前播放的音频
            this.stop_current_audio();

            // 设置正在播放状态
            this.playing_sample = voice_option.voice_name;

            // 创建音频对象并播放
            const audioUrl = `/static/epub_to_audio/samples/chinese/${voice_option.sample_file}`;
            this.currentAudio = new Audio(audioUrl);

            this.currentAudio.addEventListener('ended', () => {
                this.playing_sample = null;
                this.currentAudio = null;
            });

            this.currentAudio.addEventListener('error', () => {
                this.playing_sample = null;
                this.currentAudio = null;
                this.$alert("error", "音频文件加载失败");
            });

            this.currentAudio.play().catch(() => {
                this.playing_sample = null;
                this.currentAudio = null;
                this.$alert("error", "音频播放失败");
            });
        },
        stop_current_audio() {
            if (this.currentAudio) {
                this.currentAudio.pause();
                this.currentAudio = null;
            }
            this.playing_sample = null;
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
