<template>
    <v-row justify="center" class="fill-center">
        <v-col cols="12" sm="8" md="5" lg="4">
            <v-card class="elevation-12">
                <v-toolbar flat dark color="primary">
                    <v-icon class="mr-2">mdi-cloud-outline</v-icon>
                    <v-toolbar-title>{{ $t('share.pageTitle') }}</v-toolbar-title>
                </v-toolbar>

                <v-card-text v-if="err !== 'ok'" class="text-center py-8">
                    <v-icon size="48" color="grey">mdi-link-off</v-icon>
                    <div class="text-h6 mt-3">{{ $t('share.invalidTitle') }}</div>
                    <p class="mt-2 mb-0 grey--text">{{ $t('share.invalidDesc') }}</p>
                </v-card-text>

                <template v-else>
                    <v-card-text>
                        <div class="d-flex">
                            <v-img :src="thumb || img" :aspect-ratio="11 / 15" max-width="110" class="flex-grow-0 mr-4" style="border-radius: 8px"></v-img>
                            <div style="min-width: 0">
                                <div class="text-h6">{{ title }}</div>
                                <div class="grey--text mb-2">{{ author }}</div>
                                <div v-if="expire_time" class="text-caption grey--text">{{ $t('share.expireAt', { time: expireText }) }}</div>
                            </div>
                        </div>
                        <div v-if="comments" class="mt-4 share-comments" v-html="comments"></div>
                    </v-card-text>

                    <v-card-text v-if="!granted">
                        <v-form v-if="need_password" @submit.prevent="verify">
                            <v-text-field
                                v-model="password"
                                :label="$t('share.passwordLabel')"
                                prepend-icon="mdi-lock"
                                :error-messages="msg"
                                :loading="verifying"
                                autofocus
                            ></v-text-field>
                        </v-form>
                        <v-progress-linear v-else-if="verifying" indeterminate></v-progress-linear>
                        <div v-else-if="msg" class="error--text text-center">{{ msg }}</div>
                    </v-card-text>

                    <v-card-actions v-if="!granted && need_password" class="justify-center pb-4">
                        <v-btn color="primary" :loading="verifying" :disabled="!password" @click="verify">{{ $t('share.submit') }}</v-btn>
                    </v-card-actions>

                    <v-card-text v-if="granted" class="text-center pb-6">
                        <v-btn v-if="allow_read" color="primary" class="ma-1" :href="'/read/' + book_id" target="_blank">
                            <v-icon left>mdi-book-open-page-variant</v-icon>{{ $t('share.read') }}
                        </v-btn>
                        <template v-if="allow_download">
                            <v-btn v-for="file in files" :key="file.format" color="primary" class="ma-1" :href="file.href">
                                <v-icon left>mdi-download</v-icon>{{ file.format.toUpperCase() }}
                            </v-btn>
                        </template>
                    </v-card-text>
                </template>
            </v-card>
        </v-col>
    </v-row>
</template>

<script>
export default {
    data: () => ({
        err: 'ok',
        title: '',
        author: '',
        comments: '',
        img: '',
        thumb: '',
        allow_read: false,
        allow_download: false,
        need_password: false,
        granted: false,
        expire_time: null,
        book_id: 0,
        files: [],
        password: '',
        verifying: false,
        msg: '',
    }),
    async asyncData({ params, app, res }) {
        app.store.commit('navbar', false);
        if (res !== undefined) {
            res.setHeader('Cache-Control', 'no-cache');
        }
        return app.$backend(`/share/${params.token}`);
    },
    head() {
        return { title: this.title || this.$t('share.pageTitle') };
    },
    computed: {
        expireText() {
            return this.expire_time ? new Date(this.expire_time).toLocaleString() : '';
        },
    },
    created() {
        this.$store.commit('navbar', false);
    },
    mounted() {
        if (this.err === 'ok' && !this.granted && !this.need_password) {
            this.verify();
        }
    },
    methods: {
        async verify() {
            if (this.verifying) return;
            this.verifying = true;
            this.msg = '';
            try {
                const rsp = await this.$backend(`/share/${this.$route.params.token}/verify`, {
                    method: 'POST',
                    body: JSON.stringify({ password: this.password }),
                });
                if (rsp.err === 'ok') {
                    Object.assign(this, rsp);
                } else if (rsp.err === 'share.invalid') {
                    this.err = rsp.err;
                } else {
                    this.msg = rsp.msg || this.$t('message.operationFailed');
                }
            } catch (e) {
                this.msg = this.$t('message.networkError');
            } finally {
                this.verifying = false;
            }
        },
    },
};
</script>

<style scoped>
.share-comments {
    max-height: 160px;
    overflow: auto;
    font-size: 14px;
}
</style>
