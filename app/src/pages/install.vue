<template>
    <v-row align-center justify=center>
        <v-col xs=12 sm=8 md=4>
            <v-card class="elevation-12">
                <v-toolbar dark color="#003153">
                    <v-toolbar-title>{{ $t('install.title') }}</v-toolbar-title>
                </v-toolbar>
                <v-card-text>
                    <v-form dark ref="form" @submit.prevent="do_intall">
                        <v-text-field required prepend-icon="home" v-model="title" :label="$t('install.siteTitle')"
                            type="text"></v-text-field>
                        <v-select
                            prepend-icon="language"
                            v-model="language"
                            :items="languageOptions"
                            item-text="text"
                            item-value="value"
                            :label="$t('install.defaultLanguage')"
                        ></v-select>
                        <v-text-field required prepend-icon="person" v-model="username" :label="$t('install.adminUsername')" type="text"
                            autocomplete="new-username" :rules="[rules.user]"></v-text-field>
                        <v-text-field required prepend-icon="lock" v-model="password" :label="$t('install.adminPassword')" type="text"
                            autocomplete="new-password" :rules="[rules.pass]"></v-text-field>
                        <v-text-field required prepend-icon="email" v-model="email" :label="$t('install.adminEmail')" type="text"
                            autocomplete="new-email" :rules="[rules.email]"></v-text-field>
                        <v-checkbox v-model="invite" :label="$t('install.privateLibraryMode')"></v-checkbox>
                        <template v-if="invite">
                            <v-text-field required prepend-icon="lock" v-model="code" :label="$t('install.accessCode')" type="text"
                                autocomplete="new-code" :rules="[rules.code]"></v-text-field>
                        </template>
                    </v-form>
                    <v-alert type="info" v-if="tips" v-html="tips"></v-alert>
                </v-card-text>

                <v-card-actions>
                    <v-spacer></v-spacer>
                    <v-btn ref="install_btn" @click="do_install" color="blue" style="color: white;" :disabled="installing" :loading="installing">{{ $t('install.completeSetup') }}</v-btn>
                    <v-spacer></v-spacer>
                </v-card-actions>
            </v-card>
        </v-col>
    </v-row>
</template>

<script>
export default {
    data: () => ({
        e1: 1,
        username: "admin",
        password: "",
        email: "",
        code: "",
        invite: false,
        language: "zh",
        title: "MyBooks",
        tips: "",
        retry: 20,
        installing: false,
        rules: {
            user: null,
            pass: null,
            email: null,
            code: null,
        },

    }),
    asyncData({ store }) {
        store.commit("navbar", false);
    },
    created() {
        this.rules.user = (v) => (20 >= v.length && v.length >= 3) || this.$t('install.usernameRule');
        this.rules.pass = (v) => (20 >= v.length && v.length >= 6) || this.$t('install.passwordRule');
        this.rules.code = (v) => (64 >= v.length && v.length >= 4) || this.$t('install.accessCodeRule');
        this.rules.email = (email) => {
            var re = /^(([^<>()\[\]\\.,;:\s@"]+(\.[^<>()\[\]\\.,;:\s@"]+)*)|(".+"))@((\[[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\])|(([a-zA-Z\-0-9]+\.)+[a-zA-Z]{2,}))$/;
            return re.test(email) || this.$t('install.invalidEmail');
        };
        this.$store.commit("navbar", false);
        this.language = this.getDefaultLanguage();
        // 设置默认为dark主题
        if (process.client) {
            this.$vuetify.theme.dark = true;
            document.body.classList.add('install-page');
        }
    },
    beforeDestroy() {
        // 页面销毁时移除install-page类名
        if (process.client) {
            document.body.classList.remove('install-page');
        }    },
    methods: {
        getDefaultLanguage() {
            // Prefer current UI locale, then browser locale; support zh/en only.
            const locale = ((this.$i18n && this.$i18n.locale) || "").toLowerCase();
            console.log("Local:", locale);
            if (locale.startsWith("en")) return "en";
            if (locale.startsWith("zh")) return "zh";

            if (process.client && navigator.language) {
                const navLang = String(navigator.language).toLowerCase();
                console.log("Nav:", navLang);
                if (navLang.startsWith("en")) return "en";
            } else {
                console.log("No language found, use default zh");
            }
            return "zh";
        },
        check_install: function () {
            fetch("/api/index").then(rsp => {
                if (rsp.status == 200) {
                    this.tips += this.$t('install.apiServiceNormal') + "<br/>" + this.$t('install.installSuccess');
                } else {
                    this.retry -= 1;
                    if (this.retry > 0) {
                        setTimeout(() => {
                            this.check_install();
                        }, 1000);
                    } else {
                        this.tips += this.$t('install.timeoutRetry');
                    }
                    return;
                }

                // force refresh index.html
                fetch("/?r=" + Math.random()).then(rsp => {
                    rsp.text();
                    this.$store.commit("navbar", true);
                    this.$router.push("/");
                });

            });
        },
        do_install: function () {
            if (!this.$refs.form.validate()) {
                return false;
            }
            // 设置按钮为禁用状态
            this.installing = true;

            var data = new URLSearchParams();
            data.append('username', this.username);
            data.append('password', this.password);
            data.append('email', this.email);
            data.append('code', this.code);
            data.append('invite', this.invite);
            data.append('title', this.title);
            data.append('language', this.language);
            this.tips = this.$t('install.writingConfig');
            this.$backend('/admin/install', {
                method: 'POST',
                body: data,
            })
                .then(rsp => {
                    if (rsp.err != 'ok') {
                        this.installing = false;
                        this.tips = "";
                        this.$alert("error", rsp.msg);
                    } else {
                        this.tips += this.$t('install.configSuccess') + "<br/>" + this.$t('install.checkingServer');
                        setTimeout(() => {
                            this.check_install();
                        }, 5000);
                    }
                });
        },
    },
    computed: {
        languageOptions() {
            return [
                { text: this.$t('install.languageChinese'), value: 'zh' },
                { text: this.$t('install.languageEnglish'), value: 'en' },
            ];
        },
    },
}
</script>
