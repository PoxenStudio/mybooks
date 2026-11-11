<template>
    <v-row align-center justify=center>
        <v-col xs=12 sm=8 md=4>
            <v-card class="elevation-12">
                <v-toolbar dark color="#003153">
                    <v-toolbar-title>{{ $t('install.title') }}</v-toolbar-title>
                </v-toolbar>
                <v-card-text>
                    <v-form dark ref="form" @submit.prevent="do_intall">
                        <v-text-field required prepend-icon="mdi-home" v-model="title" :label="$t('install.siteTitle')"
                            type="text"></v-text-field>
                        <v-select
                            prepend-icon="mdi-web"
                            v-model="language"
                            :items="languageOptions"
                            item-text="text"
                            item-value="value"
                            :label="$t('install.defaultLanguage')"
                        ></v-select>
                        <v-text-field required prepend-icon="mdi-account" v-model="username" :label="$t('install.adminUsername')" type="text"
                            autocomplete="new-username" :rules="[rules.user]"></v-text-field>
                        <v-text-field required prepend-icon="mdi-lock" v-model="password" :label="$t('install.adminPassword')" type="text"
                            autocomplete="new-password" :rules="[rules.pass]"></v-text-field>
                        <v-text-field required prepend-icon="mdi-email" v-model="email" :label="$t('install.adminEmail')" type="text"
                            autocomplete="new-email" :rules="[rules.email]"></v-text-field>
                        <v-divider class="my-4"></v-divider>
                        <v-sheet outlined rounded class="pa-3">
                            <div class="text-subtitle-2 mb-2">{{ $t('install.modulesTitle') }}</div>
                            <v-checkbox v-model="moduleMultiUser" :label="$t('install.moduleMultiUser')"
                                prepend-icon="mdi-account-multiple-outline" hide-details class="mt-0"></v-checkbox>
                            <v-checkbox v-model="moduleCommunity" :label="$t('install.moduleCommunity')"
                                prepend-icon="mdi-account-group-outline" hide-details class="mt-0"></v-checkbox>
                            <v-checkbox v-model="moduleSharedReading" :label="$t('install.moduleSharedReading')"
                                prepend-icon="mdi-format-list-bulleted-square" hide-details class="mt-0"></v-checkbox>
                            <v-checkbox v-model="moduleAudio" :label="$t('install.moduleAudio')"
                                prepend-icon="mdi-headphones" hide-details class="mt-0"></v-checkbox>
                            <v-checkbox v-model="modulePhysical" :label="$t('install.modulePhysical')"
                                prepend-icon="mdi-bookshelf" hide-details class="mt-0"></v-checkbox>
                            <v-checkbox v-model="moduleAi" :label="$t('install.moduleAi')"
                                prepend-icon="mdi-robot-outline" hide-details class="mt-0"></v-checkbox>
                            <p class="text-caption grey--text mt-2 mb-0">{{ $t('install.modulesHint') }}</p>
                        </v-sheet>
                    </v-form>
                    <v-alert type="info" v-if="tips"><span v-html="tips"></span></v-alert>
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
        // 新装默认勾多用户/共享阅读/有声书/实体书/AI；社区互动默认关闭。
        // 后端 MODULES 默认仍为 true，用于老实例升级零变化。
        moduleMultiUser: true,
        moduleCommunity: false,
        moduleSharedReading: true,
        moduleAudio: true,
        modulePhysical: true,
        moduleAi: true,
        language: "zh",
        title: "MyBooks",
        tips: "",
        retry: 20,
        installing: false,
        rules: {
            user: null,
            pass: null,
            email: null,
        },

    }),
    asyncData({ store }) {
        store.commit("navbar", false);
    },
    created() {
        this.rules.user = (v) => (20 >= v.length && v.length >= 3) || this.$t('install.usernameRule');
        this.rules.pass = (v) => (20 >= v.length && v.length >= 6) || this.$t('install.passwordRule');
        this.rules.email = (email) => {
            var re = /^(([^<>()[\]\\.,;:\s@"]+(\.[^<>()[\]\\.,;:\s@"]+)*)|(".+"))@((\[[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\])|(([a-zA-Z\-0-9]+\.)+[a-zA-Z]{2,}))$/;
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
        }
    },
    mounted() {
        this.$backend('/admin/install').then(rsp => {
            if (rsp.installed) {
                this.$router.push('/');
            }
        });
    },
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
            data.append('title', this.title);
            data.append('language', this.language);
            data.append('ENABLE_MODULE_MULTIUSER', this.moduleMultiUser ? 'true' : 'false');
            data.append('ENABLE_MODULE_COMMUNITY', this.moduleCommunity ? 'true' : 'false');
            data.append('ENABLE_MODULE_SHARED_READING', this.moduleSharedReading ? 'true' : 'false');
            data.append('ENABLE_MODULE_AUDIO', this.moduleAudio ? 'true' : 'false');
            data.append('ENABLE_MODULE_PHYSICAL', this.modulePhysical ? 'true' : 'false');
            data.append('ENABLE_MODULE_AI', this.moduleAi ? 'true' : 'false');
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
