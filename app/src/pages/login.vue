<template>
    <v-row justify="center" class="fill-center">
        <v-col xs="12" sm="8" md="4">
            <v-card v-if="show_login" class="elevation-12">
                <v-toolbar dark color="primary">
                    <v-toolbar-title>{{ $t('login.welcome') }}</v-toolbar-title>
                    <v-spacer></v-spacer>
                    <v-btn v-if="$store.state.sys && $store.state.sys.allow && $store.state.sys.allow.register" rounded color="green" to="/signup">{{ $t('login.register') }}</v-btn>
                </v-toolbar>
                <v-card-text>
                    <v-form @submit.prevent="do_login">
                        <v-text-field ref="usernameField" prepend-icon="person" v-model="username" :label="$t('login.username')" type="text"></v-text-field>
                        <v-text-field prepend-icon="lock" v-model="password" :label="$t('login.password')" type="password" id="password"></v-text-field>
                        <p class="text-right">
                            <a @click="show_login = !show_login"> {{ $t('login.forgot_password') }} </a>
                        </p>
                        <div align="center">
                            <v-btn type="submit" large rounded color="primary">{{ $t('login.login') }}</v-btn>
                        </div>
                    </v-form>
                </v-card-text>

                <v-card-text v-if="socials.length > 0">
                    <v-divider></v-divider>
                    <div align="center">
                        <br />
                        <small>{{ $t('login.social_login') }}</small>
                        <br />
                        <template v-for="s in socials">
                            <v-btn small outlined :key="s.text" :href="'/auth/login/' + s.value">{{ s.text }}</v-btn>
                            &nbsp;
                        </template>
                    </div>
                </v-card-text>
                <v-alert v-if="alert.msg" :type="alert.type">{{ alert.msg }}</v-alert>
            </v-card>

            <v-card v-else class="elevation-12">
                <v-toolbar dark color="red">
                    <v-toolbar-title>{{ $t('login.reset_password') }}</v-toolbar-title>
                </v-toolbar>
                <v-card-text v-if="!show_login">
                    <v-form @submit.prevent="do_reset">
                        <v-text-field prepend-icon="person" v-model="username" :label="$t('login.username')" type="text"></v-text-field>
                        <v-text-field
                            prepend-icon="email"
                            v-model="email"
                            :label="$t('login.email')"
                            type="text"
                            autocomplete="old-email"
                        ></v-text-field>
                    </v-form>
                    <div align="center">
                        <v-btn rounded color="" class="mr-5" @click="show_login = !show_login">{{ $t('login.back') }}</v-btn>
                        <v-btn rounded dark color="red" @click="do_reset">{{ $t('login.reset') }}</v-btn>
                    </div>
                </v-card-text>
                <v-alert v-if="alert.msg" :type="alert.type">{{ alert.msg }}</v-alert>
            </v-card>
        </v-col>
    </v-row>
</template>

<script>
export default {
    data: () => ({
        username: "",
        password: "",
        email: "",
        show_login: true,
        alert: {
            type: "error",
            msg: "",
        },
    }),
    asyncData({ store }) {
        store.commit("navbar", false);
    },
    head() {
        return { title: this.$t('login.login') };
    },
    created() {
        // Clear the username and password fields
        this.username = "";
        this.password = "";

        this.$store.commit("navbar", false);

        // 只在客户端执行DOM和localStorage操作
        if (process.client) {
            // 为body添加login-page类名，应用背景图样式
            document.body.classList.add('login-page');

            // set the theme according to user/site preference
            const saved_theme = localStorage.getItem('user_theme') || localStorage.getItem('site_theme') || 'light';
            this.$setTheme(saved_theme, false);

            // 延迟执行focus，确保DOM已渲染
            this.$nextTick(() => {
                if (this.$refs.usernameField) {
                    this.$refs.usernameField.focus();
                }
            });
        }

        // API调用放在最后，确保状态管理稳定
        this.$backend("/user/info").then((rsp) => {
            this.$store.commit("login", rsp);
            // 更新页面标题模板
            if (rsp.sys && rsp.sys.title) {
                this.$store.state.site_title_template = "%s | " + rsp.sys.title;
            }
        });
    },
    beforeDestroy() {
        // 页面销毁时移除login-page类名
        if (process.client) {
            document.body.classList.remove('login-page');
        }
    },
    computed: {
        socials: function () {
            if (!this.$store.state.sys || !this.$store.state.sys.socials) {
                return [];
            }
            return this.$store.state.sys.socials;
        },
    },
    methods: {
        do_login: function () {
            var data = new URLSearchParams();
            data.append("username", this.username);
            data.append("password", this.password);
            this.$backend("/user/sign_in", {
                method: "POST",
                body: data,
            }).then((rsp) => {
                if (rsp.err != "ok") {
                    this.alert.type = "error";
                    this.alert.msg = rsp.msg;
                } else {
                    this.$store.commit("navbar", true);
                    this.$router.push("/");
                }
            });
        },
        do_reset: function () {
            var data = new URLSearchParams();
            data.append("username", this.username);
            data.append("email", this.email);
            this.$backend("/user/reset", {
                method: "POST",
                body: data,
            }).then((rsp) => {
                if (rsp.err == "ok") {
                    this.alert.type = "success";
                    this.alert.msg = "重置成功！请查阅密码通知邮件。";
                } else {
                    this.alert.type = "error";
                    this.alert.msg = rsp.msg;
                }
            });
        },
    },
};
</script>

<style>
.fill-center {
    margin-top: 6%;
}
</style>
