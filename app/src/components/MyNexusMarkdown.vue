<template>
    <div class="mynexus-markdown" v-html="renderedContent"></div>
</template>

<script>
// marked / DOMPurify 只在 AI 回答真正需要渲染时才加载，
// 避免它们被 AppHeader 的初始 chunk 带进首页首屏。
let markdownLibs = null;
const loadMarkdownLibs = () => {
    if (!markdownLibs) {
        markdownLibs = Promise.all([import("dompurify"), import("marked")]).then(([dompurify, marked]) => ({
            DOMPurify: dompurify.default || dompurify,
            marked: marked.marked || marked.default || marked,
        }));
    }
    return markdownLibs;
};

export default {
    props: {
        content: {
            type: String,
            default: "",
        },
    },
    data() {
        return {
            renderedContent: "",
        };
    },
    watch: {
        content: {
            immediate: true,
            handler: "renderContent",
        },
    },
    methods: {
        async renderContent() {
            const content = this.content || "";
            if (!content) {
                this.renderedContent = "";
                return;
            }
            const { DOMPurify, marked } = await loadMarkdownLibs();
            // 内容在异步加载期间又变了，丢弃旧结果
            if (content !== (this.content || "")) {
                return;
            }
            this.renderedContent = DOMPurify.sanitize(marked.parse(content, { breaks: true, gfm: true }));
        },
    },
};
</script>

<style scoped>
.mynexus-markdown {
    overflow-wrap: anywhere;
    line-height: 1.6;
}

.mynexus-markdown :deep(> :first-child) {
    margin-top: 0;
}

.mynexus-markdown :deep(> :last-child) {
    margin-bottom: 0;
}

.mynexus-markdown :deep(h1),
.mynexus-markdown :deep(h2),
.mynexus-markdown :deep(h3),
.mynexus-markdown :deep(h4) {
    margin: 1rem 0 0.5rem;
    line-height: 1.3;
}

.mynexus-markdown :deep(p) {
    margin: 0.6rem 0;
}

.mynexus-markdown :deep(ul),
.mynexus-markdown :deep(ol) {
    margin: 0.6rem 0;
    padding-left: 1.4rem;
}

.mynexus-markdown :deep(pre),
.mynexus-markdown :deep(table) {
    max-width: 100%;
    overflow-x: auto;
}

.mynexus-markdown :deep(pre) {
    padding: 0.6rem 0.8rem;
    border-radius: 8px;
    background: rgba(128, 128, 128, 0.12);
}

.mynexus-markdown :deep(code) {
    padding: 0.1rem 0.3rem;
    border-radius: 4px;
    background: rgba(128, 128, 128, 0.12);
    font-size: 0.9em;
}
</style>
