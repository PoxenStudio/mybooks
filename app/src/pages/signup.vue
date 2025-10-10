<template>
    <v-row justify=center class="fill-center">
      <v-col xs=12 sm=8 md=4>
        <v-card class="elevation-12">
            <v-toolbar dark color="primary">
                <v-toolbar-title>{{ $t('signup.title') }}</v-toolbar-title>
            </v-toolbar>
            <v-card-text>
                <v-form ref="form" @submit.prevent="signup">
                    <v-text-field required prepend-icon="person" v-model="username"  :label="$t('signup.username')"   type="text"     autocomplete="new-username"  :rules="[rules.user]"         ></v-text-field>
                    <v-text-field required prepend-icon="lock"   v-model="password"  :label="$t('signup.password')"   type="password" autocomplete="new-password"  :rules="[rules.pass]" ></v-text-field>
                    <v-text-field required prepend-icon="lock"   v-model="password2" :label="$t('signup.confirmPassword')" type="password" autocomplete="new-password2" :rules="[valid]"                  ></v-text-field>
                    <v-text-field required prepend-icon="face"   v-model="nickname"  :label="$t('signup.nickname')"   type="text"     autocomplete="new-nickname"  :rules="[rules.nick]"         ></v-text-field>
                    <v-text-field required prepend-icon="email"  v-model="email"     :label="$t('signup.email')"      type="text"     autocomplete="new-email"     :rules="[rules.email]"            ></v-text-field>
                </v-form>
                <div align="center">
                    <v-btn dark large rounded color="red" @click="signup">{{ $t('signup.registerButton') }}</v-btn>
                </div>
            </v-card-text>

            <v-alert v-if="failmsg" type="error">{{ failmsg }}</v-alert>
        </v-card>
      </v-col>
    </v-row>
</template>

<script>
export default {
    created() {
        this.$store.commit("navbar", false);
    },
    data: () => ({
        username: "",
        password: "",
        password2: "",
        nickname: "",
        email: "",
        failmsg: "",
        validmsg: "",
        rules: {
            user: v => ( 20 >= v.length && v.length >= 5) || '6 ~ 20 字符',
            pass: v => ( 20 >= v.length && v.length >= 8) || '8 ~ 20 字符',
            nick: v => v.length >= 2 || '最少2个字符',
            email: function (email) {
                var re = /^(([^<>()[\]\\.,;:\s@"]+(\.[^<>()[\]\\.,;:\s@"]+)*)|(".+"))@((\[[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\])|(([a-zA-Z\-0-9]+\.)+[a-zA-Z]{2,}))$/;
                return re.test(email) || "错误的邮箱格式";
            },
        },

    }),
    head() {
        return {
            title: this.$t('signup.pageTitle'),
        };
    },
    methods: {
        valid: function(v) {
            if ( v.length < 8 ) {
                return '最少8个字符';
            }
            return v == this.password || "密码不匹配";
        },
        signup: function() {
            if ( ! this.$refs.form.validate() ) {
                return false;
            }

            var data = new URLSearchParams();
            data.append('username', this.username);
            data.append('password', this.password);
            data.append('nickname', this.nickname);
            data.append('email', this.email);
            this.$backend('/user/sign_up', {
                method: 'POST',
                body: data,
            })
            .then( rsp => {
                if ( rsp.err != 'ok' ) {
                    this.failmsg = rsp.msg;
                } else {
                    this.$store.commit("navbar", true);
                    this.$router.push("/");
                }
            });
        }
    },
}
</script>

<style>
.fill-center {
    margin-top: 6%;
}
</style>

