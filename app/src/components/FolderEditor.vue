<template>
    <div>
        <div class="d-flex align-center">
            <template v-for="(part, idx) in parts">
                <span v-if="idx > 0" :key="'sep' + idx" class="mx-1 text-h6 grey--text">.</span>
                <v-text-field
                    :key="'input' + idx"
                    :ref="'input' + idx"
                    :value="part"
                    :label="$t('folder.level', { n: idx + 1 })"
                    :disabled="disabled"
                    :autofocus="autofocus && idx === parts.length - 1"
                    :dense="dense"
                    :counter="maxLen"
                    hide-details="auto"
                    outlined
                    @focus="activeLevel = idx"
                    @input="onInput(idx, $event)"
                    @keydown="onKeydown(idx, $event)"
                    @paste="onPaste(idx, $event)"
                ></v-text-field>
            </template>
        </div>
        <div class="caption grey--text mt-1">{{ $t('folder.editorHint') }}</div>
        <div v-if="visibleCandidates.length" class="mt-2">
            <v-chip
                v-for="item in visibleCandidates"
                :key="item.name"
                small
                label
                class="mr-1 mb-1"
                :color="item.source === 'folder' ? 'amber lighten-4' : undefined"
                @click="pick(item.name)"
            >
                <v-icon v-if="item.source === 'folder'" left small>mdi-folder</v-icon>
                {{ item.name }}
            </v-chip>
        </div>
    </div>
</template>

<script>
const MAX_LEN = 24;
const DEFAULT_MAX_DEPTH = 2;
const INVALID_CHARS = /[^\p{L}\p{N}]/gu;
const SEPARATORS = /[.。]/;

export const cleanSegment = (text) => (text || '').replace(INVALID_CHARS, '').slice(0, MAX_LEN);

export default {
    name: 'FolderEditor',
    props: {
        value: { type: String, default: '' },
        dense: { type: Boolean, default: false },
        disabled: { type: Boolean, default: false },
        autofocus: { type: Boolean, default: false },
    },
    data() {
        return {
            maxLen: MAX_LEN,
            maxDepth: DEFAULT_MAX_DEPTH,
            parts: this.splitValue(this.value),
            activeLevel: 0,
            candidates: [],
            fetchTimer: null,
        };
    },
    computed: {
        joined() {
            return this.parts.filter((p) => p).join('.');
        },
        isValid() {
            return this.parts.every((p, idx) => p || (idx === this.parts.length - 1 && idx > 0));
        },
        visibleCandidates() {
            const text = (this.parts[this.activeLevel] || '').toLowerCase();
            return this.candidates.filter((c) => c.name.toLowerCase() !== text && c.name.toLowerCase().includes(text)).slice(0, 12);
        },
    },
    watch: {
        value(newValue) {
            if (newValue !== this.joined) {
                this.parts = this.splitValue(newValue);
            }
        },
        joined(newValue) {
            this.$emit('input', newValue);
        },
        isValid: {
            immediate: true,
            handler(valid) {
                this.$emit('valid-change', valid);
            },
        },
        activeLevel() {
            this.scheduleFetch();
        },
    },
    mounted() {
        this.fetchCandidates();
    },
    beforeDestroy() {
        clearTimeout(this.fetchTimer);
    },
    methods: {
        splitValue(value) {
            const parts = (value || '').split('.').map(cleanSegment);
            return parts.length ? parts : [''];
        },
        focus(idx = this.parts.length - 1) {
            this.$nextTick(() => {
                const refs = this.$refs['input' + idx];
                if (refs && refs[0]) {
                    refs[0].focus();
                }
            });
        },
        setPart(idx, text) {
            this.$set(this.parts, idx, text);
            // v-text-field 内部缓存了原始输入，需要手动回写过滤后的文本
            const refs = this.$refs['input' + idx];
            if (refs && refs[0]) {
                refs[0].lazyValue = text;
            }
        },
        addLevel() {
            if (this.parts.length >= this.maxDepth) {
                this.$alert('warning', this.$t('folder.maxDepth', { n: this.maxDepth }));
                return;
            }
            this.parts.push('');
            this.focus(this.parts.length - 1);
        },
        onInput(idx, raw) {
            this.setPart(idx, cleanSegment(raw));
            this.scheduleFetch();
        },
        onKeydown(idx, event) {
            if (event.key === '.' || event.key === '。') {
                event.preventDefault();
                if (idx === this.parts.length - 1 && this.parts[idx]) {
                    this.addLevel();
                }
            } else if (event.key === 'Backspace' && idx > 0 && idx === this.parts.length - 1 && !this.parts[idx]) {
                event.preventDefault();
                this.parts.pop();
                this.focus(idx - 1);
            }
        },
        onPaste(idx, event) {
            const text = (event.clipboardData || window.clipboardData).getData('text');
            if (!SEPARATORS.test(text)) {
                return;
            }
            event.preventDefault();
            const pieces = text.split(SEPARATORS).map(cleanSegment).filter((p) => p);
            if (!pieces.length) {
                return;
            }
            if (pieces.length > 1) {
                this.parts = [...this.parts.slice(0, idx), ...pieces].slice(0, this.maxDepth);
                this.focus(this.parts.length - 1);
            } else {
                this.setPart(idx, pieces[0]);
            }
        },
        pick(name) {
            const idx = this.activeLevel;
            this.setPart(idx, name);
            if (idx === this.parts.length - 1 && idx + 1 < this.maxDepth) {
                this.addLevel();
            } else {
                this.focus(idx);
            }
        },
        scheduleFetch() {
            clearTimeout(this.fetchTimer);
            this.fetchTimer = setTimeout(this.fetchCandidates, 250);
        },
        async fetchCandidates() {
            const parents = this.parts.slice(0, this.activeLevel);
            if (parents.some((p) => !p)) {
                this.candidates = [];
                return;
            }
            const query = new URLSearchParams({ level: this.activeLevel + 1, parent: parents.join('.'), q: this.parts[this.activeLevel] || '' });
            try {
                const rsp = await this.$backend(`/folder/candidates?${query}`);
                this.candidates = rsp.err === 'ok' ? rsp.items : [];
                if (rsp.max_depth) {
                    this.maxDepth = rsp.max_depth;
                }
            } catch (error) {
                this.candidates = [];
            }
        },
    },
};
</script>
