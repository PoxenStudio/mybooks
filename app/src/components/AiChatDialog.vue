<template>
    <AppDialog
        :value="value"
        @input="$emit('input', $event)"
        type="action"
        :title="$t('appHeader.aiAssistant')"
        icon="mdi-robot"
        color="primary"
        toolbar-class="ai-chat-toolbar"
        :light-header="!titleDark"
        dismiss-icon
        :dismiss-label="$t('common.close')"
        width="720"
        max-width="calc(100vw - 48px)"
        hide-footer-button
    >
        <div
            ref="chatMessages"
            class="ai-chat-messages"
            role="log"
            aria-live="polite"
            :aria-busy="thinking ? 'true' : 'false'"
            @scroll="onScroll"
        >
            <div v-if="messages.length === 0" class="ai-chat-empty">
                <v-icon size="56" color="grey lighten-1">mdi-robot-outline</v-icon>
                <p class="mt-4 mb-0">{{ $t('appHeader.aiChatWelcome') }}</p>
            </div>

            <template v-for="(message, index) in messages">
                <div
                    :key="index"
                    class="ai-chat-message"
                    :class="message.role === 'user' ? 'is-user' : 'is-assistant'"
                >
                    <div class="ai-chat-bubble" :class="{ 'is-error': message.error }">
                        <div v-if="message.status" class="ai-chat-status">{{ message.status }}</div>

                        <div v-if="message.error" class="ai-chat-error">
                            <v-icon size="16" color="error" class="mr-1">mdi-alert-circle-outline</v-icon>
                            <span>{{ message.content }}</span>
                        </div>
                        <div v-else-if="message.role === 'user'" class="ai-chat-text">{{ message.content }}</div>
                        <MyNexusMarkdown
                            v-else-if="message.content"
                            :content="message.streaming ? message.content + ' ▍' : message.content"
                        />
                        <span v-else-if="message.streaming" class="thinking-dots">
                            <span></span><span></span><span></span>
                        </span>

                        <div v-if="message.retry" class="ai-chat-error-actions">
                            <v-btn text x-small color="primary" :disabled="thinking" @click="retryMessage(message)">
                                {{ $t("common.retry") }}
                            </v-btn>
                        </div>
                    </div>

                    <v-btn
                        v-if="canCopy(message)"
                        class="ai-chat-copy"
                        icon
                        x-small
                        :aria-label="message.copied ? $t('common.copied') : $t('common.copy')"
                        @click="copyMessage(message)"
                    >
                        <v-icon size="16">{{ message.copied ? "mdi-check" : "mdi-content-copy" }}</v-icon>
                    </v-btn>
                </div>
            </template>

            <div v-if="showPendingBubble" class="ai-chat-message is-assistant">
                <div class="ai-chat-bubble">
                    <span class="thinking-dots"><span></span><span></span><span></span></span>
                </div>
            </div>
        </div>

        <template v-slot:actions>
            <div class="ai-chat-composer">
                <v-textarea
                    ref="aiInput"
                    v-model="input"
                    rows="1"
                    auto-grow
                    outlined
                    dense
                    hide-details
                    :placeholder="$t('appHeader.aiInputPlaceholder')"
                    @keydown.enter.exact="onEnter"
                ></v-textarea>
                <v-btn
                    icon
                    color="primary"
                    :loading="thinking"
                    :disabled="!connected || !input.trim() || thinking"
                    :aria-label="$t('common.send')"
                    @click="sendMessage"
                >
                    <v-icon>mdi-send</v-icon>
                </v-btn>
            </div>
        </template>
    </AppDialog>
</template>

<script>
import MyNexusMarkdown from "~/components/MyNexusMarkdown.vue";

export default {
    name: "AiChatDialog",
    components: { MyNexusMarkdown },
    props: {
        /** 对话框是否打开（v-model） */
        value: { type: Boolean, default: false },
        /** 标题栏是否按深色底渲染，用于决定关闭按钮图标颜色 */
        titleDark: { type: Boolean, default: true },
    },
    data() {
        return {
            thinking: false,
            messages: [],
            ws: null,
            input: "",
            /** 消息区是否贴底：用户往上翻历史时不要被流式输出强行拽回底部 */
            stickToBottom: true,
            /** WebSocket 是否已握手完成：握手期间点发送会抛 InvalidStateError 并丢掉草稿 */
            connected: false,
            /** 等待连接建立后补发的文本（握手期间发送、或断线后重试） */
            pending: "",
        };
    },
    computed: {
        showPendingBubble() {
            const last = this.messages[this.messages.length - 1];
            return this.thinking && !!last && last.role === "user";
        },
    },
    watch: {
        value(val) {
            if (val) {
                this.connect();
                this.$nextTick(() => {
                    if (this.$refs.aiInput) {
                        this.$refs.aiInput.focus();
                    }
                    this.scrollToBottom(true);
                });
            } else {
                this.disconnect();
            }
        },
    },
    beforeDestroy() {
        this.disconnect();
    },
    methods: {
        setThinking(val) {
            if (this.thinking === val) return;
            this.thinking = val;
            this.$emit("thinking", val);
        },
        onScroll() {
            const el = this.$refs.chatMessages;
            if (!el) return;
            this.stickToBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
        },
        onEnter(event) {
            // 中文/日文输入法用回车确认候选词时不能直接发送
            if (event.isComposing || event.keyCode === 229) return;
            event.preventDefault();
            this.sendMessage();
        },
        canCopy(message) {
            return message.role === "assistant" && !message.error && !message.streaming && !!message.content;
        },
        connect() {
            if (this.ws) return;

            const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
            const host = window.location.host;
            const wsUrl = `${protocol}//${host}/api/assistant/ws`;

            const socket = new WebSocket(wsUrl);
            this.ws = socket;

            socket.onopen = () => {
                if (this.ws !== socket) return;
                this.connected = true;
                if (this.pending) {
                    const text = this.pending;
                    this.pending = "";
                    this.dispatch(text);
                }
            };

            socket.onmessage = (event) => {
                if (this.ws !== socket) return;
                let data;
                try {
                    data = JSON.parse(event.data);
                } catch (error) {
                    console.error("Invalid AI WebSocket frame:", error);
                    return;
                }
                if (data.type === "start") {
                    this.setThinking(true);
                    this.messages.push({ role: "assistant", content: "", streaming: true });
                    this.scrollToBottom();
                } else if (data.type === "content") {
                    const lastMsg = this.messages[this.messages.length - 1];
                    if (lastMsg) {
                        lastMsg.content += data.content;
                        this.scrollToBottom();
                    }
                } else if (data.type === "status") {
                    const lastMsg = this.messages[this.messages.length - 1];
                    if (lastMsg) {
                        lastMsg.status = data.content;
                    }
                } else if (data.type === "end") {
                    const lastMsg = this.messages[this.messages.length - 1];
                    if (lastMsg) {
                        lastMsg.streaming = false;
                        lastMsg.status = "";
                    }
                    this.setThinking(false);
                    this.scrollToBottom();
                } else if (data.type === "error") {
                    this.setThinking(false);
                    this.finishStreaming();
                    this.pushError(data.content, this.lastUserQuestion());
                    this.scrollToBottom();
                }
            };

            // 连接类错误留在对话里，不再弹窗并关掉对话框——那会把用户刚问的问题一起丢掉
            socket.onerror = (error) => {
                if (this.ws !== socket) return;
                console.error("AI WebSocket error:", error);
                this.ws = null;
                this.connected = false;
                this.restorePendingToInput();
                this.finishStreaming();
                this.setThinking(false);
                this.pushError(this.$t("appHeader.aiConnectionError"), this.lastUserQuestion());
                this.scrollToBottom();
            };

            socket.onclose = (event) => {
                if (this.ws !== socket) return;
                const wasThinking = this.thinking;
                this.ws = null;
                this.connected = false;
                this.finishStreaming();
                this.setThinking(false);
                this.restorePendingToInput();
                if (wasThinking) {
                    this.pushError(this.$t("appHeader.aiConnectionError"), this.lastUserQuestion());
                    this.scrollToBottom();
                } else if (event.code && event.code !== 1000) {
                    console.log("AI WebSocket closed", event.code, event.reason);
                }
            };
        },
        disconnect() {
            if (this.ws) {
                this.ws.close();
                this.ws = null;
            }
            this.connected = false;
            this.pending = "";
            this.finishStreaming();
            this.setThinking(false);
        },
        /** 断开/关窗时给还在流式中的气泡收尾，否则会一直停着一个光标 */
        finishStreaming() {
            const lastMsg = this.messages[this.messages.length - 1];
            if (!lastMsg || !lastMsg.streaming) return;
            // 本轮一个字都还没产出就中断了，占位气泡直接去掉，别留一个空气泡
            if (!lastMsg.content) {
                this.messages.pop();
                return;
            }
            lastMsg.streaming = false;
            lastMsg.status = "";
        },
        restorePendingToInput() {
            if (this.pending) {
                if (!this.input) this.input = this.pending;
                this.pending = "";
            }
        },
        lastUserQuestion() {
            for (let i = this.messages.length - 1; i >= 0; i -= 1) {
                if (this.messages[i].role === "user") return this.messages[i].content;
            }
            return "";
        },
        pushError(content, retryText) {
            this.messages.push({
                role: "assistant",
                content: content,
                error: true,
                retry: retryText || "",
            });
        },
        sendMessage() {
            const text = this.input.trim();
            if (!text || this.thinking) return;

            this.input = "";
            this.pending = text;
            if (this.connected && this.ws) {
                this.pending = "";
                this.dispatch(text);
            } else {
                // 连接还没建好：先排队，onopen 后自动发出去
                this.connect();
            }
        },
        /** 把一条用户提问发给后端，并插入对应的用户气泡 */
        dispatch(text) {
            if (!this.ws) return;
            this.messages.push({ role: "user", content: text });
            this.setThinking(true);
            this.scrollToBottom(true);
            this.ws.send(JSON.stringify({ type: "query", content: text }));
        },
        retryMessage(message) {
            if (this.thinking) return;
            const text = message.retry;
            if (!text) return;

            const index = this.messages.indexOf(message);
            if (index < 0) return;
            this.messages.splice(index, 1);

            // 连带去掉这条错误对应的用户气泡，重试后对话里只保留一份
            const prev = this.messages[index - 1];
            if (prev && prev.role === "user" && prev.content === text) {
                this.messages.splice(index - 1, 1);
            }

            this.pending = text;
            if (this.connected && this.ws) {
                this.pending = "";
                this.dispatch(text);
            } else {
                this.connect();
            }
        },
        async copyMessage(message) {
            const text = message.content;
            if (!text) return;
            try {
                if (navigator.clipboard && window.isSecureContext) {
                    await navigator.clipboard.writeText(text);
                } else {
                    this.legacyCopy(text);
                }
                this.$set(message, "copied", true);
                setTimeout(() => {
                    if (!this._isDestroyed) this.$set(message, "copied", false);
                }, 1500);
            } catch (error) {
                console.error("Copy failed:", error);
                this.$alert("error", this.$t("message.operationFailed"));
            }
        },
        /** 局域网 http 部署没有 navigator.clipboard，退回 execCommand */
        legacyCopy(text) {
            const textarea = document.createElement("textarea");
            textarea.value = text;
            textarea.setAttribute("readonly", "");
            textarea.style.position = "fixed";
            textarea.style.opacity = "0";
            document.body.appendChild(textarea);
            textarea.select();
            document.execCommand("copy");
            document.body.removeChild(textarea);
        },
        scrollToBottom(force = false) {
            if (force) this.stickToBottom = true;
            this.$nextTick(() => {
                const container = this.$refs.chatMessages;
                if (container && this.stickToBottom) {
                    container.scrollTop = container.scrollHeight;
                }
            });
        },
    },
};
</script>

<style>
/* 标题栏沿用顶栏品牌色（可由外观设置改成任意颜色），前景色随之切换 */
.v-application .ai-chat-toolbar.v-toolbar {
    background-color: var(--app-nav-bg, #003153) !important;
    border-color: var(--app-nav-bg, #003153) !important;
    color: var(--app-nav-fg, rgba(255, 255, 255, 0.87)) !important;
}
</style>

<style scoped>
.ai-chat-messages {
    display: flex;
    flex-direction: column;
    gap: 12px;
    height: min(60vh, 500px);
    min-height: 200px;
    overflow-y: auto;
    overscroll-behavior: contain;
}

.ai-chat-messages::-webkit-scrollbar {
    width: 8px;
}

.ai-chat-messages::-webkit-scrollbar-thumb {
    background: rgba(128, 128, 128, 0.35);
    border-radius: 4px;
}

.ai-chat-messages::-webkit-scrollbar-thumb:hover {
    background: rgba(128, 128, 128, 0.55);
}

.ai-chat-empty {
    margin: auto 0;
    text-align: center;
    color: inherit;
    opacity: 0.72;
}

.ai-chat-message {
    display: flex;
    animation: ai-chat-fade-in 0.25s ease-out;
}

.ai-chat-message.is-user {
    justify-content: flex-end;
}

.ai-chat-message.is-assistant {
    justify-content: flex-start;
    align-items: flex-end;
}

.ai-chat-bubble {
    max-width: 86%;
    padding: 10px 14px;
    border-radius: 14px;
    font-size: 14px;
    line-height: 1.6;
    overflow-wrap: anywhere;
}

/* 气泡使用主色的低透明度叠加，跟随外观设置里的主色，而不是写死蓝色 */
.ai-chat-message.is-user .ai-chat-bubble {
    /* 不支持 color-mix 的旧内核回退，否则气泡会全透明 */
    background-color: rgba(25, 118, 210, 0.14);
    background-color: color-mix(in srgb, var(--primary-color, #1976d2) 16%, transparent);
    border-bottom-right-radius: 4px;
}

.ai-chat-message.is-assistant .ai-chat-bubble {
    background-color: rgba(128, 128, 128, 0.12);
    border-bottom-left-radius: 4px;
}

.ai-chat-message .ai-chat-bubble.is-error {
    background-color: rgba(244, 67, 54, 0.14);
}

.ai-chat-error {
    display: flex;
    align-items: flex-start;
}

.ai-chat-error-actions {
    margin: 2px 0 -6px -8px;
}

/* 换行只作用在正文上：若放在气泡上，模板里的空白文本节点会被 pre-wrap 当成一整行空白 */
.ai-chat-text {
    white-space: pre-wrap;
    word-break: break-word;
}

.ai-chat-status {
    margin-bottom: 4px;
    font-size: 13px;
    line-height: 1.4;
    opacity: 0.75;
}

.ai-chat-copy {
    flex: 0 0 auto;
    margin-left: 4px;
    opacity: 0;
}

.ai-chat-message:hover .ai-chat-copy,
.ai-chat-copy:focus {
    opacity: 1;
}

/* 触屏没有 hover，复制按钮常显 */
@media (hover: none) {
    .ai-chat-copy {
        opacity: 0.7;
    }
}

/* 助手气泡里渲染的是 Markdown，首尾段落的默认外边距会让气泡上下不对称 */
.ai-chat-bubble ::v-deep .mynexus-markdown > :first-child {
    margin-top: 0;
}

.ai-chat-bubble ::v-deep .mynexus-markdown > :last-child {
    margin-bottom: 0;
}

.ai-chat-composer {
    display: flex;
    align-items: flex-end;
    gap: 8px;
    width: 100%;
    /* v-card__actions 自带 8px/16px 内边距，这里抵消掉，让分隔线铺满整宽 */
    margin: -8px -16px;
    padding: 12px 16px 8px;
    border-top: 1px solid rgba(128, 128, 128, 0.24);
}

.ai-chat-composer .v-btn {
    flex: 0 0 auto;
    margin-bottom: 2px;
}

.thinking-dots {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 4px 0;
}

.thinking-dots span {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: currentColor;
    opacity: 0.4;
    animation: ai-chat-dot 1s infinite ease-in-out;
}

.thinking-dots span:nth-child(2) {
    animation-delay: 0.15s;
}

.thinking-dots span:nth-child(3) {
    animation-delay: 0.3s;
}

@keyframes ai-chat-dot {
    0%, 80%, 100% { opacity: 0.4; transform: translateY(0); }
    40% { opacity: 1; transform: translateY(-3px); }
}

@keyframes ai-chat-fade-in {
    from { opacity: 0; transform: translateY(6px); }
    to { opacity: 1; transform: translateY(0); }
}

@media (prefers-reduced-motion: reduce) {
    .ai-chat-message,
    .thinking-dots span {
        animation: none !important;
    }
}

@media (max-width: 600px) {
    .ai-chat-messages {
        height: min(58vh, 420px);
    }

    .ai-chat-bubble {
        max-width: 92%;
    }
}
</style>
