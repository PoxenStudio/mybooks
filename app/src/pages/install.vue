<template>
    <v-row align-center justify=center>
        <v-col xs=12 sm=8 md=4>
            <v-card class="elevation-12">
                <v-toolbar dark color="primary">
                    <v-toolbar-title>{{ $t('install.title') }}</v-toolbar-title>
                </v-toolbar>
                <v-card-text>
                    <v-form ref="form" @submit.prevent="do_intall">
                        <v-text-field required prepend-icon="home" v-model="title" :label="$t('install.siteTitle')"
                            type="text"></v-text-field>
                        <v-text-field required prepend-icon="person" v-model="username" :label="$t('install.adminUsername')" type="text"
                            autocomplete="new-username" :rules="[rules.user]"></v-text-field>
                        <v-text-field required prepend-icon="lock" v-model="password" :label="$t('install.adminPassword')" type="text"
                            autocomplete="new-password" :rules="[rules.pass]"></v-text-field>
                        <v-text-field required prepend-icon="email" v-model="email" :label="$t('install.adminEmail')" type="text"
                            autocomplete="new-email" :rules="[rules.email]"></v-text-field>
                        <v-checkbox v-model="invite" :label="$t('install.privateLibraryMode')"></v-checkbox>
                        <template v-if="invite">
                            <v-text-field required prepend-icon="lock" v-model="code" :label="$t('install.accessCode')" type="text"
                                autocomplete="new-code"></v-text-field>
                        </template>
                    </v-form>
                    <v-alert type="info" v-if="tips" v-html="tips"></v-alert>
                </v-card-text>

                <v-card-actions>
                    <v-spacer></v-spacer>
                    <v-btn ref="install_btn"  @click="do_install" color="blue" style="color: white;">{{ $t('install.completeSetup') }}</v-btn>
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
        title: "TaleBook",
        tips: "",
        retry: 20,
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
        this.rules.user = (v) => (20 >= v.length && v.length >= 5) || this.$t('install.usernameRule');
        this.rules.pass = (v) => (20 >= v.length && v.length >= 8) || this.$t('install.passwordRule');
        this.rules.email = (email) => {
            var re = /^(([^<>()[\]\\.,;:\s@"]+(\.[^<>()[\]\\.,;:\s@"]+)*)|(".+"))@((\[[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\])|(([a-zA-Z\-0-9]+\.)+[a-zA-Z]{2,}))$/;
            return re.test(email) || this.$t('install.invalidEmail');
        };
        this.$store.commit("navbar", false);
    },
    methods: {
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
            // set install_btn to be disabled
            this.$refs.install_btn.disabled = true;

            var data = new URLSearchParams();
            data.append('username', this.username);
            data.append('password', this.password);
            data.append('email', this.email);
            data.append('code', this.code);
            data.append('invite', this.invite);
            data.append('title', this.title);
            this.tips = this.$t('install.writingConfig');
            this.$backend('/admin/install', {
                method: 'POST',
                body: data,
            })
                .then(rsp => {
                    if (rsp.err != 'ok') {
                        this.$refs.install_btn.disabled = false;
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
}
</script>
