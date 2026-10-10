<template>
    <div>
        <AppDialog
            v-model="internalValue"
            type="action"
            :title="$t('share.dialogTitle')"
            icon="mdi-cloud-outline"
            max-width="900"
            :confirm-text="isActive ? $t('common.save') : $t('share.create')"
            :confirm-loading="submitting"
            :confirm-disabled="loading || (!form.allow_read && !form.allow_download)"
            @confirm="submit"
        >
            <v-row>
                <v-col cols="12" md="5">
                    <ShareCardView :image-url="cardImageUrl" :generating="cardGenerating" :alt="book.title" />
                    <div v-if="cardImageUrl && !cardGenerating" class="text-center mt-3">
                        <v-btn text color="primary" @click="downloadCard">
                            <v-icon left>mdi-download</v-icon>{{ $t('book.downloadShareCard') }}
                        </v-btn>
                    </div>
                </v-col>
                <v-col cols="12" md="7">
                    <v-progress-linear v-if="loading" indeterminate></v-progress-linear>
                    <template v-else>
                        <template v-if="isActive">
                            <v-text-field
                                :value="shareUrl"
                                :label="$t('share.link')"
                                readonly
                                append-icon="mdi-content-copy"
                                @click:append="copy(shareUrl)"
                            ></v-text-field>
                            <div class="mb-4 text-caption grey--text">
                                {{ viewsText }}
                                <v-chip v-if="share.state !== 'active'" x-small color="orange" text-color="white" class="ml-2">{{ $t('share.state.' + share.state) }}</v-chip>
                            </div>
                        </template>

                        <v-switch v-model="form.allow_read" :label="$t('share.allowRead')" color="primary" class="mt-0" hide-details></v-switch>
                        <v-switch v-model="form.allow_download" :label="$t('share.allowDownload')" color="primary" hide-details></v-switch>
                        <div v-if="!form.allow_read && !form.allow_download" class="error--text text-caption mt-1">{{ $t('share.needOnePermission') }}</div>

                        <v-select v-model="form.expire_days" :items="expireItems" :label="$t('share.expire')" class="mt-4"></v-select>
                        <v-text-field
                            v-model="form.max_views"
                            :label="$t('share.maxViews')"
                            type="number"
                            min="0"
                            :rules="[v => v === '' || Number(v) >= 0 || $t('share.invalidNumber')]"
                        ></v-text-field>
                        <v-text-field
                            v-model="form.password"
                            :label="$t('share.password')"
                            maxlength="32"
                            append-icon="mdi-dice-multiple-outline"
                            @click:append="randomPassword"
                        ></v-text-field>

                        <div v-if="isActive" class="text-center mt-2">
                            <v-btn text color="deep-orange" @click="cancelDialog = true">
                                <v-icon left>mdi-link-off</v-icon>{{ $t('share.cancelShare') }}
                            </v-btn>
                        </div>
                    </template>
                </v-col>
            </v-row>
        </AppDialog>

        <AppDialog
            v-model="cancelDialog"
            type="confirm"
            :title="$t('share.cancelShare')"
            color="deep-orange"
            confirm-dark
            max-width="420"
            :confirm-text="$t('share.cancelShare')"
            :confirm-loading="cancelling"
            @confirm="cancelShare"
        >
            {{ $t('share.cancelConfirm') }}
        </AppDialog>
    </div>
</template>

<script>
import { downloadImage, renderBookShareCard, shareCardFileName } from '~/utils/bookShareCard';

const DEFAULT_EXPIRE_DAYS = 7;

export default {
    name: 'BookShareDialog',
    props: {
        value: { type: Boolean, default: false },
        book: { type: Object, required: true },
    },
    data() {
        return {
            loading: false,
            submitting: false,
            cancelling: false,
            cancelDialog: false,
            share: null,
            form: this.defaultForm(),
            cardImageUrl: null,
            cardGenerating: false,
            cardSeq: 0,
        };
    },
    computed: {
        internalValue: {
            get() { return this.value; },
            set(v) { this.$emit('input', v); },
        },
        bookId() {
            return this.book.id;
        },
        cardQrUrl() {
            return this.shareUrl || `${window.location.origin}/read/${this.bookId}`;
        },
        isActive() {
            return !!this.share && this.share.status === 1;
        },
        shareUrl() {
            return this.share && typeof window !== 'undefined' ? window.location.origin + this.share.path : '';
        },
        expireItems() {
            const items = [
                { text: this.$t('share.expire1d'), value: 1 },
                { text: this.$t('share.expire7d'), value: 7 },
                { text: this.$t('share.expire30d'), value: 30 },
                { text: this.$t('share.expireForever'), value: 0 },
            ];
            if (this.isActive) {
                items.unshift({ text: this.currentExpireText, value: -1 });
            }
            return items;
        },
        currentExpireText() {
            if (!this.share || !this.share.expire_time) return this.$t('share.expireKeepForever');
            return this.$t('share.expireKeep', { time: new Date(this.share.expire_time).toLocaleString() });
        },
        viewsText() {
            if (!this.share) return '';
            const max = this.share.max_views > 0 ? this.share.max_views : '∞';
            return this.$t('share.viewsUsed', { count: this.share.view_count, max });
        },
    },
    watch: {
        value(v) {
            if (!v) return;
            this.load();
            this.refreshCard();
        },
        cardQrUrl() {
            if (this.value) this.refreshCard();
        },
    },
    methods: {
        defaultForm() {
            return { allow_read: true, allow_download: false, expire_days: DEFAULT_EXPIRE_DAYS, max_views: '', password: '' };
        },
        applyShare(share) {
            this.share = share;
            if (share && share.status === 1) {
                this.form = {
                    allow_read: share.allow_read,
                    allow_download: share.allow_download,
                    expire_days: -1,
                    max_views: share.max_views > 0 ? String(share.max_views) : '',
                    password: share.password || '',
                };
            } else {
                this.form = this.defaultForm();
            }
        },
        async load() {
            this.loading = true;
            try {
                const rsp = await this.$backend(`/admin/share/book/${this.bookId}`);
                if (rsp.err === 'ok') {
                    this.applyShare(rsp.share);
                } else {
                    this.$alert('error', rsp.msg || this.$t('message.operationFailed'));
                    this.internalValue = false;
                }
            } catch (e) {
                this.$alert('error', this.$t('message.networkError'));
                this.internalValue = false;
            } finally {
                this.loading = false;
            }
        },
        async refreshCard() {
            const seq = ++this.cardSeq;
            this.cardGenerating = true;
            try {
                const url = await renderBookShareCard({
                    title: this.book.title,
                    comments: this.book.comments,
                    coverUrl: this.book.img,
                    qrUrl: this.cardQrUrl,
                    qrLabel: this.shareUrl ? this.$t('share.cardScan') : undefined,
                    siteTitle: localStorage.getItem('sys_title') || 'MyBooks',
                });
                if (seq === this.cardSeq) this.cardImageUrl = url;
            } catch (e) {
                if (seq === this.cardSeq) this.cardImageUrl = null;
            } finally {
                if (seq === this.cardSeq) this.cardGenerating = false;
            }
        },
        downloadCard() {
            if (this.cardImageUrl) downloadImage(this.cardImageUrl, `${shareCardFileName(this.book.title)}.png`);
        },
        randomPassword() {
            const chars = 'abcdefghjkmnpqrstuvwxyz23456789';
            let result = '';
            for (let i = 0; i < 8; i++) result += chars[Math.floor(Math.random() * chars.length)];
            this.form.password = result;
        },
        async submit() {
            if (this.submitting) return;
            this.submitting = true;
            try {
                const payload = {
                    allow_read: this.form.allow_read,
                    allow_download: this.form.allow_download,
                    expire_days: this.form.expire_days,
                    max_views: Number(this.form.max_views) || 0,
                    password: this.form.password,
                };
                const rsp = await this.$backend(`/admin/share/book/${this.bookId}`, { method: 'POST', body: JSON.stringify(payload) });
                if (rsp.err === 'ok') {
                    this.applyShare(rsp.share);
                    this.$emit('changed', true);
                    this.$alert('success', rsp.msg || this.$t('message.operationSuccess'));
                } else {
                    this.$alert('error', rsp.msg || this.$t('message.operationFailed'));
                }
            } catch (e) {
                this.$alert('error', this.$t('message.networkError'));
            } finally {
                this.submitting = false;
            }
        },
        async cancelShare() {
            if (this.cancelling || !this.share) return;
            this.cancelling = true;
            try {
                const rsp = await this.$backend(`/admin/share/${this.share.id}/cancel`, { method: 'POST' });
                if (rsp.err === 'ok') {
                    this.cancelDialog = false;
                    this.share = null;
                    this.form = this.defaultForm();
                    this.$emit('changed', false);
                    this.internalValue = false;
                    this.$alert('success', rsp.msg || this.$t('message.operationSuccess'));
                } else {
                    this.$alert('error', rsp.msg || this.$t('message.operationFailed'));
                }
            } catch (e) {
                this.$alert('error', this.$t('message.networkError'));
            } finally {
                this.cancelling = false;
            }
        },
        async copy(text) {
            try {
                await navigator.clipboard.writeText(text);
                this.$alert('success', this.$t('share.copied'));
            } catch (e) {
                this.$alert('error', this.$t('message.operationFailed'));
            }
        },
    },
};
</script>
