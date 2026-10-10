<template>
    <AppDialog
        v-model="internalValue"
        type="action"
        :title="mode === 'create' ? $t('booklist.createTitle') : $t('booklist.editTitle')"
        icon="mdi-format-list-bulleted-square"
        max-width="600"
        :confirm-text="$t('common.save')"
        :confirm-loading="submitting"
        :confirm-disabled="!form.name || !form.name.trim()"
        @confirm="submit"
    >
                <v-text-field
                    v-model="form.name"
                    :label="$t('booklist.fieldName')"
                    counter="100"
                    maxlength="100"
                    :rules="[v => !!(v && v.trim()) || $t('booklist.nameRequired')]"
                ></v-text-field>
                <v-textarea
                    v-model="form.description"
                    :label="$t('booklist.fieldDescription')"
                    counter="500"
                    maxlength="500"
                    rows="3"
                ></v-textarea>

                <div class="mb-2 grey--text text-caption">{{ $t('booklist.fieldColor') }}</div>
                <div class="d-flex flex-wrap mb-4">
                    <v-btn
                        v-for="c in colors"
                        :key="c.key"
                        icon
                        class="ma-1 booklist-color-swatch"
                        :style="{ backgroundColor: dark ? c.dark : c.light }"
                        @click="form.color = c.key"
                    >
                        <v-icon v-if="form.color === c.key" color="white">mdi-check</v-icon>
                    </v-btn>
                </div>

                <v-switch
                    v-model="form.is_public"
                    :label="form.is_public ? $t('booklist.publicHint') : $t('booklist.privateHint')"
                    color="primary"
                ></v-switch>
                <v-switch
                    v-if="canSetGuestRead"
                    v-model="form.guest_read"
                    :disabled="!form.is_public"
                    :label="$t('booklist.guestReadHint')"
                    color="primary"
                    class="mt-0"
                ></v-switch>
    </AppDialog>
</template>

<script>
import { BOOKLIST_COLORS, DEFAULT_BOOKLIST_COLOR } from '~/utils/booklistColors';

export default {
    name: 'BookListEditDialog',
    props: {
        value: { type: Boolean, default: false },
        mode: { type: String, default: 'create' }, // 'create' | 'edit'
        booklist: { type: Object, default: null }, // 编辑态下的原始书单对象
    },
    data() {
        return {
            colors: BOOKLIST_COLORS,
            submitting: false,
            form: {
                name: '',
                description: '',
                color: DEFAULT_BOOKLIST_COLOR,
                is_public: false,
                guest_read: false,
            },
        };
    },
    computed: {
        internalValue: {
            get() { return this.value; },
            set(v) { this.$emit('input', v); },
        },
        dark() {
            return this.$vuetify.theme.dark;
        },
        canSetGuestRead() {
            return this.$store.state.user?.is_admin === true && !this.$store.state.sys.allow.read;
        },
    },
    watch: {
        'form.is_public'(v) {
            if (!v) this.form.guest_read = false;
        },
        value(v) {
            if (v) this.resetForm();
        },
    },
    methods: {
        resetForm() {
            if (this.mode === 'edit' && this.booklist) {
                this.form = {
                    name: this.booklist.name,
                    description: this.booklist.description || '',
                    color: this.booklist.color || DEFAULT_BOOKLIST_COLOR,
                    is_public: !!this.booklist.is_public,
                    guest_read: !!this.booklist.guest_read,
                };
            } else {
                this.form = { name: '', description: '', color: DEFAULT_BOOKLIST_COLOR, is_public: false, guest_read: false };
            }
        },
        close() {
            this.internalValue = false;
        },
        async submit() {
            if (this.submitting || !this.form.name || !this.form.name.trim()) return;
            this.submitting = true;
            try {
                const payload = {
                    name: this.form.name.trim(),
                    description: (this.form.description || '').trim(),
                    color: this.form.color,
                    is_public: this.form.is_public,
                };
                if (this.canSetGuestRead) payload.guest_read = this.form.guest_read;
                const url = this.mode === 'edit' ? `/booklist/${this.booklist.id}/update` : '/booklist/create';
                const rsp = await this.$backend(url, { method: 'POST', body: JSON.stringify(payload) });
                if (rsp.err === 'ok') {
                    this.$alert('success', rsp.msg || this.$t('message.operationSuccess'));
                    this.$emit('saved', rsp.booklist);
                    this.close();
                } else {
                    this.$alert('error', rsp.msg || this.$t('message.operationFailed'));
                }
            } catch (e) {
                this.$alert('error', this.$t('message.networkError'));
            } finally {
                this.submitting = false;
            }
        },
    },
};
</script>

<style scoped>
.booklist-color-swatch {
    border: 2px solid transparent;
}
</style>
