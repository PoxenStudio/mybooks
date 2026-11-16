<template>
    <v-row justify=center class='fill-center'>
      <v-col xs=12 sm=8 md=4>
        <v-card class="elevation-12">
            <v-toolbar dark color="blue-grey" class="logout-toolbar">
                <v-toolbar-title></v-toolbar-title>
            </v-toolbar>
            <v-card-text>
                <div class="text-center title primary--text">
                    <p class="pt-8">{{ $t('logout.message') }}</p>
                </div>
            </v-card-text>
            <v-card-actions>
                <v-spacer></v-spacer>
                <v-btn class="mb-4" rounded color="primary" href="/">{{ $t('logout.homeButton') }}</v-btn>
                <v-spacer></v-spacer>
            </v-card-actions>
        </v-card>
          </v-col>
        </v-row>
</template>

<script>
export default {
    created() {
        this.$store.commit("navbar", false);
        this.logout();
    },
    computed: {
        msg() {
            return this.$t('logout.message'); // Dynamically compute msg using $t
        },
    },
    head() {
        return {
            title: this.$t('logout.pageTitle'),
        };
    },
    methods: {
        logout: function() {
            // 成功失败都清本地状态：网络错误/5xx 时 $backend 会 reject，
            // 只写在 .then 里会让"已退出"的画面和"还登录着"的缓存打架。
            const clear = () => {
                // 清掉守卫缓存的会话快照与 store 里的登录态，否则「必须登录」模式下
                // 点回首页时守卫仍以为已登录，白跑一次请求才被后端弹回 /login。
                if (this.$resetSession) {
                    this.$resetSession();
                }
                this.$store.commit("clear_user");
            };
            this.$backend('/user/sign_out').then(clear, clear);
        }
    },
}
</script>

<style>
.v-application .v-toolbar.logout-toolbar,
.v-application .v-toolbar.logout-toolbar > .v-toolbar__content {
    border-bottom-left-radius: 0px !important;
    border-bottom-right-radius: 0px !important;
    overflow: hidden;
}
</style>

