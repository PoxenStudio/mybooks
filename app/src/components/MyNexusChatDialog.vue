<template>
    <AppDialog
        :value="open"
        @input="$emit('update:open', $event)"
        type="action"
        :title="$t('book.mynexusCompanion')"
        icon="mdi-forum-outline"
        color="primary"
        :dismiss-label="$t('common.close')"
        width="760"
        max-width="calc(100vw - 48px)"
        hide-footer-button
    >
        <div ref="mynexusChatMessages" class="mynexus-chat-messages">
            <div
                v-for="(message, index) in mynexusMessages"
                :key="'mynexus-message-' + index"
                class="mynexus-chat-message"
                :class="message.role === 'user' ? 'mynexus-chat-user' : 'mynexus-chat-assistant'"
            >
                <div class="text-caption font-weight-bold mb-1" v-if="message.role !== 'user'">✴</div>
                <template v-if="message.role !== 'user' && !message.content && mynexusChatLoading && index === mynexusMessages.length - 1">
                    <span class="thinking-dots"><span></span><span></span><span></span></span>
                </template>
                <MyNexusMarkdown
                    v-else-if="message.role !== 'user'"
                    class="mynexus-chat-content"
                    :content="message.content"
                />
                <div v-else class="mynexus-chat-content">{{ message.content }}</div>
                <details v-for="(citation, citationIndex) in (message.citations || [])" :key="'mynexus-citation-' + index + '-' + citationIndex" class="mt-2">
                    <summary>{{ $t('book.mynexusCitation') }} {{ citationIndex + 1 }}</summary>
                    <div class="mynexus-chat-content mt-1">{{ citation.content }}</div>
                </details>
            </div>
            <div v-if="mynexusChatError" class="error--text">{{ mynexusChatError }}</div>
            <div v-if="mynexusMessages.length === 0 && !mynexusChatLoading" class="grey--text text-center py-8">
                {{ $t('book.mynexusChatEmpty') }}
            </div>
        </div>
        <v-textarea
            v-model="mynexusQuestion"
            :label="$t('book.mynexusChatPlaceholder')"
            rows="2"
            auto-grow
            hide-details
            class="mt-3"
            @keydown.enter.prevent="sendMyNexusMessage"
        ></v-textarea>
        <template v-slot:actions>
            <div class="d-flex justify-center flex-grow-1">
                <v-btn color="primary" :loading="mynexusChatLoading" :disabled="!mynexusQuestion.trim()" @click="sendMyNexusMessage">
                    {{ $t('common.send') }}
                </v-btn>
            </div>
        </template>
    </AppDialog>
</template>

<script>
import MyNexusMarkdown from "~/components/MyNexusMarkdown.vue";

export default {
    name: "MyNexusChatDialog",
    components: { MyNexusMarkdown },
    props: {
        open: { type: Boolean, default: false },
        book: { type: Object, required: true },
    },
    watch: {
        open(val) {
            if (val) this.loadSession();
        },
    },
    data() {
        return {
            mynexusChatLoading: false,
            mynexusChatError: "",
            mynexusQuestion: "",
            mynexusMessages: [],
        };
    },
    methods: {
        async loadSession() {
            this.mynexusChatError = "";
            try {
                const response = await this.$backend(`/book/${this.book.id}/mynexus/session`);
                if (response.err === "mynexus.missing" || response.err === "mynexus.not_ready") {
                    this.$emit("update:open", false);
                    this.$emit("unavailable", response.err);
                    return;
                }
                if (response.err !== "ok") throw new Error(response.msg || this.$t("book.mynexusChatFailed"));
                this.mynexusMessages = response.messages || [];
                if (this.mynexusMessages.length === 0 && this.book?.title) {
                    const greeting = `现在我们开始伴读《${this.book.title}》这本书`;
                    this.mynexusQuestion = greeting;
                    this.$nextTick(() => this.sendMyNexusMessage());
                }
            } catch (error) {
                this.$alert("error", error.message || this.$t("book.mynexusChatFailed"));
            }
        },
        async sendMyNexusMessage() {
            const question = this.mynexusQuestion.trim();
            if (!question || this.mynexusChatLoading) return;
            this.mynexusQuestion = "";
            this.mynexusChatError = "";
            this.mynexusMessages.push({ role: "user", content: question });
            this.mynexusMessages.push({ role: "assistant", content: "", citations: [] });
            const assistant = this.mynexusMessages[this.mynexusMessages.length - 1];
            this.mynexusChatLoading = true;
            this.scrollMynexusToBottom();
            try {
                const response = await fetch(`/api/book/${this.book.id}/mynexus/chat`, {
                    method: "POST",
                    credentials: "same-origin",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ messages: this.mynexusMessages.slice(0, -1) }),
                });
                if (!response.ok) {
                    const error = await response.json();
                    throw new Error(error.msg || this.$t("book.mynexusChatFailed"));
                }
                if (!response.body) throw new Error(this.$t("book.mynexusChatFailed"));
                const reader = response.body.getReader();
                const decoder = new TextDecoder();
                let buffer = "";
                let done = false;
                while (!done) {
                    const chunk = await reader.read();
                    done = chunk.done;
                    buffer += decoder.decode(chunk.value || new Uint8Array(), { stream: !done });
                    buffer = buffer.replace(/\r\n/g, "\n");
                    let boundary = buffer.indexOf("\n\n");
                    while (boundary >= 0) {
                        const frame = buffer.slice(0, boundary);
                        buffer = buffer.slice(boundary + 2);
                        const payload = frame.split("\n").filter((line) => line.startsWith("data:")).map((line) => line.slice(5).trim()).join("\n");
                        if (payload && payload !== "[DONE]") {
                            const event = JSON.parse(payload);
                            if (event.error) throw new Error(event.error);
                            assistant.content += event.choices?.[0]?.delta?.content || "";
                            if (event.citations) assistant.citations = event.citations;
                            this.scrollMynexusToBottom();
                        }
                        boundary = buffer.indexOf("\n\n");
                    }
                }
            } catch (error) {
                this.mynexusMessages.splice(-2, 2);
                this.mynexusChatError = error.message || this.$t("book.mynexusChatFailed");
            } finally {
                this.mynexusChatLoading = false;
            }
        },
        scrollMynexusToBottom() {
            this.$nextTick(() => {
                const el = this.$refs.mynexusChatMessages;
                if (el) el.scrollTop = el.scrollHeight;
            });
        },
    },
};
</script>

<style scoped>
.mynexus-chat-messages {
    display: flex;
    flex-direction: column;
    gap: 12px;
    max-height: 48vh;
    min-height: 180px;
    overflow-y: auto;
}
.mynexus-chat-message {
    max-width: 92%;
    padding: 10px 14px;
    border-radius: 12px;
    overflow-wrap: anywhere;
}
.mynexus-chat-user {
    align-self: flex-end;
    background: rgba(25, 118, 210, 0.12);
}
.mynexus-chat-assistant {
    align-self: flex-start;
    background: rgba(128, 128, 128, 0.12);
}
.mynexus-chat-content {
    line-height: 1.6;
    overflow-wrap: anywhere;
}
.thinking-dots {
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
    margin: 0.35rem 0 0;
    color: inherit;
}
.thinking-dots span {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: currentColor;
    opacity: 0.4;
    animation: thinking-bounce 1s infinite ease-in-out;
}
.thinking-dots span:nth-child(2) { animation-delay: 0.15s; }
.thinking-dots span:nth-child(3) { animation-delay: 0.3s; }
@keyframes thinking-bounce {
    0%, 80%, 100% { opacity: 0.4; transform: translateY(0); }
    40% { opacity: 1; transform: translateY(-3px); }
}
@media (max-width: 600px) {
    .mynexus-chat-message {
        max-width: 100%;
    }
}
</style>
