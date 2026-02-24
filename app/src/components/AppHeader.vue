<template>
    <div>
        <v-navigation-drawer
            v-model="sidebar"
            app
            fixed
            :width="240"
            :mini-variant-width="64"
            :mini-variant="miniVariant && user.is_login"
            :color="drawerColor"
            :clipped="$vuetify.breakpoint.lgAndUp"
            class="app-navigation-drawer"
            @mouseenter="handleMouseEnter"
            @mouseleave="handleMouseLeave"
        >

            <v-list dense>
                <template v-for="(item, idx) in items">
                    <v-subheader v-if="item.heading" :key="'heading-' + idx" v-show="!miniVariant">{{ $t(item.heading) }}</v-subheader>

                    <v-list-item
                        dense
                        v-else-if="item.groups && item.groups.length > 0 && miniVariant"
                        :key="'item-' + idx"
                        :class="{ 'v-list-item--icon-only': miniVariant }"
                        @click="handleMiniVariantGroupClick(idx, item)"
                    >
                        <v-tooltip bottom>
                            <template v-slot:activator="{ on, attrs }">
                                <v-icon v-bind="attrs" v-on="on" :color="item.color || ''" size="24">{{ item.icon }}</v-icon>
                            </template>
                            {{ $t(item.text) }}
                        </v-tooltip>
                    </v-list-item>

                    <v-list-group
                        v-else-if="item.groups && item.groups.length > 0"
                        no-action
                        :value="isGroupExpanded(idx, item)"
                        @input="toggleGroup(idx, item)"
                        :key="'group-' + idx"
                    >
                        <template v-slot:activator>
                            <v-list-item dense>
                                <v-list-item-action class="mt-1 mb-1 mr-2" dense>
                                    <v-icon class="pa-0 ma-0" :color="item.color || ''">{{ item.icon }}</v-icon>
                                </v-list-item-action>
                                <v-list-item-content>
                                    <v-list-item-title>{{ $t(item.text) }}</v-list-item-title>
                                </v-list-item-content>
                            </v-list-item>
                        </template>

                        <v-list-item
                            v-for="link in item.groups"
                            :key="'link-' + link.href"
                            :to="isExternalLink(link.href) ? undefined : link.href"
                            :href="isExternalLink(link.href) ? link.href : undefined"
                            :target="isExternalLink(link.href) ? '_blank' : undefined"
                        >
                            <v-list-item-content>
                                <v-list-item-title>
                                    <v-icon :color="link.color || ''">{{ link.icon }}</v-icon> {{ $t(link.text) }}
                                </v-list-item-title>
                            </v-list-item-content>
                        </v-list-item>
                    </v-list-group>

                    <template v-else-if="item.links" v-show="!miniVariant">
                        <v-list-item dense v-for="(links, cidx) in chunk(item.links, 2)" :key="'chunk-' + idx + '-' + cidx">
                            <v-row>
                                <v-col class="pa-0" cols="6" v-for="link in links" :key="'btn-' + link.href">
                                    <v-btn v-if="item.target != ''" text target="_blank" :href="link.href">
                                        <v-icon v-if="link.icon" :color="link.color || ''" left>{{ link.icon }}</v-icon> {{ $t(link.text) }}
                                    </v-btn>
                                    <v-btn v-else text :to="link.href">
                                        <v-icon v-if="link.icon" left :color="link.color || ''">{{ link.icon }}</v-icon> {{ $t(link.text) }}
                                    </v-btn>
                                </v-col>
                            </v-row>
                        </v-list-item>
                    </template>

                    <v-list-item
                        dense
                        v-else
                        :key="'item-' + idx + '-' + (item.href || item.text)"
                        :to="item.href"
                        :target="item.target"
                        :class="{ 'v-list-item--icon-only': miniVariant }"
                    >
                        <v-list-item-action class="mt-1 mb-1 mr-2" dense v-if="!miniVariant">
                            <v-icon class="pa-0 ma-0" :color="item.color || ''">{{ item.icon }}</v-icon>
                        </v-list-item-action>
                        <template v-else>
                            <v-tooltip bottom>
                                <template v-slot:activator="{ on, attrs }">
                                    <v-icon v-bind="attrs" v-on="on" :color="item.color || ''" size="24">{{ item.icon }}</v-icon>
                                </template>
                                {{ $t(item.text) }}
                            </v-tooltip>
                        </template>
                        <v-list-item-content v-if="!miniVariant">
                            <v-list-item-title>
                                {{ $t(item.text) }}
                            </v-list-item-title>
                        </v-list-item-content>
                        <v-list-item-action class="mt-1 mb-1 mr-2" v-if="item.count && !miniVariant">
                            <v-chip small outlined>{{ item.count }}</v-chip>
                        </v-list-item-action>
                    </v-list-item>
                </template>
            </v-list>
            <template v-slot:append v-if="user.is_login">
                <v-divider></v-divider>
                <v-list-item dense to="/logout">
                    <v-list-item-action dense>
                        <v-icon>exit_to_app</v-icon>
                    </v-list-item-action>
                    <v-list-item-content v-if="!miniVariant">
                        <v-list-item-title>{{ $t('appHeader.logout') }}</v-list-item-title>
                    </v-list-item-content>
                </v-list-item>
            </template>
        </v-navigation-drawer>

        <v-app-bar class="px-0" :color="appBarColor" dense dark app fixed clipped-left extension-height="64">
            <template v-if="btn_search && $vuetify.breakpoint.xs" #extension>
                <v-container fluid>
                    <v-form @submit.prevent="doSearch">
                        <v-row>
                            <v-col cols="9">
                                <v-text-field
                                    class="ma-0 pa-0"
                                    hide-details
                                    single-line
                                    solo-inverted
                                    v-model="search"
                                    ref="mobile_search"
                                    :loading="ai_thinking"
                                    :disabled="ai_thinking"
                                ></v-text-field>
                            </v-col>
                            <v-col cols="3">
                                <v-btn dark rounded @click="doSearch" color="primary" :disabled="ai_thinking">{{ $t('appHeader.search') }}</v-btn>
                            </v-col>
                        </v-row>
                    </v-form>
                </v-container>
            </template>

            <template v-if="user.is_login">
                <v-btn icon @click="toggleMiniVariant">
                    <v-avatar color="primary" class="avatar-round" size="36">
                        <img :src="user.avatar" @error="handleAvatarError" class="avatar-img" />
                    </v-avatar>
                </v-btn>
            </template>
            <template v-else>
                <v-btn to="/login" color="indigo accent-4" class="ml-4">
                    <v-icon left>account_circle</v-icon> {{ $t('appHeader.please_login') }}
                </v-btn>
            </template>

            <v-toolbar-title class="ml-4 mr-12 align-center d-flex">
                <div class="breathing-light"></div>
                <span class="cursor-pointer ml-2" @click="$router.push('/')">{{ sys.title }}</span>
            </v-toolbar-title>

            <v-spacer></v-spacer>
            <template v-if="$vuetify.breakpoint.smAndUp">
                <v-text-field
                    flat
                    solo-inverted
                    hide-details
                    prepend-inner-icon="search"
                    @keyup.enter="doSearch"
                    @focus="isFocused = true"
                    @blur="isFocused = false"
                    ref="search"
                    v-model="search"
                    name="name"
                    :label="$t('appHeader.search')"
                    class="d-none d-sm-flex ml-8"
                    :loading="ai_thinking"
                    :disabled="ai_thinking"
                >
                    <template #append>
                        <v-btn v-if="isAiFeatureEnabled" :color="isFocused ? (ai_enabled ? 'orange' : 'grey') : 'transparent'" class="black--text" rounded @click="toggleAi">AI</v-btn>
                    </template>
                </v-text-field>
                <v-spacer></v-spacer>
            </template>

            <v-btn v-else icon class="d-flex d-sm-none" @click="btn_search = !btn_search"> <v-icon>search</v-icon> </v-btn>

            <template v-if="err == 'ok' && user.is_login">
                <v-menu offset-y right :close-on-content-click="false" v-if="runningTasks.length > 0">
                    <template v-slot:activator="{ on }">
                        <v-btn v-on="on" icon class="mr-2" width="48px" height="48px">
                            <v-img src="/icons/running.svg" style="margin:8px 8px;" width="32px" height="32px"></v-img>
                        </v-btn>
                    </template>
                    <v-card width="380">
                        <v-card-title class="py-2">
                            <span>{{ $t('appHeader.backgroundTasks') }}</span>
                        </v-card-title>
                        <v-list three-line dense width="380">
                            <v-list-item v-for="task in runningTasks" :key="task.id">
                                <v-list-item-content>
                                    <v-list-item-title class="body-2 font-weight-bold">
                                        {{ getTaskTypeLabel(task.service_type) }}
                                    </v-list-item-title>
                                    <v-list-item-subtitle class="caption mt-1">
                                        {{ task.service_item }}
                                    </v-list-item-subtitle>
                                    <v-list-item-subtitle class="mt-2">
                                        <v-progress-linear
                                            :value="getTaskProgress(task)"
                                            color="primary"
                                            height="6"
                                            rounded
                                        ></v-progress-linear>
                                        <span class="caption mt-1">{{ getTaskProgress(task) }}%</span>
                                    </v-list-item-subtitle>
                                </v-list-item-content>
                            </v-list-item>
                        </v-list>
                    </v-card>
                </v-menu>

                <v-menu offset-y right :close-on-content-click="false" v-if="messages.length > 0">
                    <template v-slot:activator="{ on }">
                        <v-btn v-on="on" icon color="yellow"> <v-icon class="blink">notifications</v-icon> </v-btn>
                    </template>
                    <v-card :width="$vuetify.breakpoint.smAndUp ? 400 : 300">
                        <v-card-title class="py-2">
                            <span>{{ $t('appHeader.message_notification') }}</span>
                            <v-spacer></v-spacer>
                            <v-btn rounded color='error' @click="clearAllMessages" style="color: white;" v-if="messages.length > 3">
                                <v-icon left>mdi-delete-sweep</v-icon>
                                {{ $t('appHeader.clear_messages') }}
                            </v-btn>
                        </v-card-title>
                        <v-list three-line dense max-width="400" min-width="300">
                            <v-list-item v-for="(msg, idx) in messages" :key="msg.id">
                                <v-list-item-avatar>
                                    <v-icon large color="green" v-if="msg.status == 'success'">mdi-information</v-icon>
                                    <v-icon large color="red" v-else>mdi-alert</v-icon>
                                </v-list-item-avatar>

                                <v-list-item-content>
                                    <p class="body-2">
                                        {{ msg.data.message }}
                                        <br />
                                        <span>{{ msg.create_time }}</span>
                                    </p>
                                </v-list-item-content>

                                <v-list-item-action>
                                    <v-btn rounded color='primary' @click.prevent="hideMsg(idx, msg.id)">{{ $t('appHeader.ok') }}</v-btn>
                                </v-list-item-action>
                            </v-list-item>
                        </v-list>
                    </v-card>
                </v-menu>
            </template>
        </v-app-bar>

        <v-dialog v-model="ai_enabled" persistent max-width="700" scrollable>
            <v-card class="dialog-border d-flex flex-column" style="height: 600px;">
                <v-card-title class="primary white--text py-3">
                    <v-icon left color="white">mdi-robot</v-icon>
                    {{ $t('appHeader.aiAssistant') }}
                    <v-spacer></v-spacer>
                    <v-btn icon dark @click="closeAi">
                        <v-icon>mdi-close</v-icon>
                    </v-btn>
                </v-card-title>

                <v-card-text class="flex-grow-1 pa-0" style="overflow-y: auto; height: 100%;">
                    <div class="chat-messages pa-4" ref="chatMessages">
                        <div v-if="ai_messages.length === 0" class="text-center grey--text py-8">
                            <v-icon size="64" color="grey lighten-1">mdi-chat-outline</v-icon>
                            <p class="mt-4">{{ $t('appHeader.aiChatWelcome') }}</p>
                        </div>
                        <div v-for="(message, index) in ai_messages" :key="index"
                             :class="['message-item', 'mb-4']">
                            <div class="d-flex" :class="message.role === 'user' ? 'justify-end' : 'justify-start'">
                                <v-avatar v-if="message.role === 'assistant'" size="32" color="primary" class="mr-2">
                                    <v-icon dark small>mdi-robot</v-icon>
                                </v-avatar>
                                <div :class="['message-bubble', 'pa-3', message.role === 'user' ? 'primary white--text' : ($vuetify.theme.dark ? 'grey darken-3 white--text' : 'grey lighten-4 black--text')]"
                                     style="max-width: 70%; border-radius: 12px; word-break: break-word; white-space: pre-wrap;">
                                    <div v-if="message.status" :class="['caption', 'italic', 'mb-1', $vuetify.theme.dark ? 'grey--text text--lighten-1' : 'grey--text text--darken-1']">{{ message.status }}</div>
                                    <div>{{ message.content }}<span v-if="message.streaming" class="ai-typing">|</span></div>
                                </div>
                                <v-avatar v-if="message.role === 'user'" size="32" color="secondary" class="ml-2">
                                    <v-icon dark small>mdi-account</v-icon>
                                </v-avatar>
                            </div>
                        </div>
                        <div v-if="ai_thinking && ai_messages.length > 0 && ai_messages[ai_messages.length - 1].role === 'user'" class="message-item mb-4">
                            <div class="d-flex justify-start">
                                <v-avatar size="32" color="primary" class="mr-2">
                                    <v-icon dark small>mdi-robot</v-icon>
                                </v-avatar>
                                <div class="message-bubble grey lighten-4 pa-3" style="border-radius: 12px;">
                                    <v-progress-circular indeterminate size="20" width="2" color="primary"></v-progress-circular>
                                    <span class="ml-2 grey--text">{{ $t('appHeader.aiThinking') }}</span>
                                </div>
                            </div>
                        </div>
                    </div>
                </v-card-text>

                <v-divider></v-divider>

                <v-card-actions class="pa-4">
                    <v-text-field
                        v-model="ai_input"
                        :placeholder="$t('appHeader.aiInputPlaceholder')"
                        outlined
                        dense
                        hide-details
                        :disabled="ai_thinking"
                        @keyup.enter="sendAiMessage"
                        class="mr-2"
                        ref="aiInput"
                    >
                    </v-text-field>
                    <v-btn
                        icon
                        color="primary"
                        :loading="ai_thinking"
                        :disabled="!ai_input.trim() || ai_thinking"
                        @click="sendAiMessage"
                        large
                    >
                        <v-icon>mdi-send</v-icon>
                    </v-btn>
                </v-card-actions>
            </v-card>
        </v-dialog>
    </div>
</template>

<script>
import { colors } from 'vuetify/lib';

export default {
    data: () => ({
        err: "",
        visit_admin_pages: false,
        sidebar: null,
        miniVariant: false,
        right: null,
        btn_search: false,
        search: "",
        isFocused: false,
        ai_enabled: false,
        ai_thinking: false,
        ai_messages: [],
        ai_ws: null,
        ai_input: '',
        user: {},
        sys: {
            books: 0,
            tags: 0,
            authors: 0,
            publishers: 0,
            series: 0,
            users: 0,
            active: 0,
            version: "",
            mtime: "",
            title: "",
            footer: "",
            socials: [],
            friends: [],
            allow: {
                register: true,
                download: true,
                push: true,
                read: true,
            },
        },
        messages: [],
        runningTasks: [],
        taskPollingTimer: null,
        expandedGroups: {},
    }),
    computed: {
        appBarColor() {
            return this.$vuetify.theme.dark ? 'dark' : '#003153';
        },
        drawerColor() {
            return this.$vuetify.theme.dark ? 'dark' : '#F7FAF7';
        },
        isAiFeatureEnabled() {
            if (process.client) {
                return localStorage.getItem('aiEnabled') === 'true';
            }
            return false;
        },
        items: function () {
            const home_links = [
                { icon: "home", href: "/", text: "appHeader.home", color:"primary" },
            ];
            const user_links = [
                {
                    icon: "mdi-account-group",
                    text: "appHeader.user_center",
                    color: "primary",
                    expand: this.isPathMatch("/user/"),
                    groups: [
                        { icon: "mdi-account-cog", href: "/user/usersettings", text: "appHeader.user_setting", color: "primary" },
                        { icon: "mdi-shield-account", href: "/soledbooks", text: "appHeader.soledBooks", color: "primary"},
                    ],
                }
            ];
            const admin_links = [
                {
                    icon: "mdi-cog",
                    text: "appHeader.admin",
                    expand: this.isPathMatch("/admin/"),
                    color: "primary",
                    groups: [
                        { icon: "mdi-cog", href: "/admin/settings", text: "appHeader.systemSettings", color: "primary"},
                        { icon: "mdi-account", href: "/admin/users", text: "appHeader.userManagement", color: "primary"},
                        { icon: "mdi-library-shelves", href: "/admin/books", text: "appHeader.bookManagement", color: "primary"},
                        { icon: "mdi-import", href: "/admin/imports", text: "appHeader.importBooks", color: "primary"},
                        { icon: "sms_failed", href: "https://github.com/PoxenStudio/talebook/issues", text: "appHeader.feedback", color: "primary"},
                    ],
                },
            ];
            const reading_links = [
                {
                    icon: "mdi-book-open-page-variant-outline",
                    text: "appHeader.readingInfo",
                    expand: this.isPathMatch("/reading/") || this.isPathMatch("/favorites/") || this.isPathMatch("/wants/") || this.isPathMatch("/read-done/"),
                    color: "primary",
                    groups: [
                        { icon: "mdi-heart", href: "/favorites", text: "appHeader.favorites", color: "red" },
                        { icon: "mdi-bookmark-plus", href: "/wants", text: "appHeader.wants", color: "orange" },
                        { icon: "mdi-book-open-page-variant", href: "/reading", text: "appHeader.reading", color: "blue" },
                        { icon: "mdi-check-circle", href: "/read-done", text: "appHeader.readDone", color: "green" },
                        { icon: "mdi-history", href: "/user/history", text: "appHeader.reading_history", color: "primary" },
                    ]
                }
            ];

            const nav_links = [
                { icon: "category", href: "/categories", text: "appHeader.categoryBrowse", color: "green" },
                { icon: "mdi-headphones", href: "/audiobooks", text: "appHeader.audioBooks", count: this.sys.audiobooks, color: "purple"},
                { icon: "mdi-account-group", href: "/author", text: "appHeader.authors", count: this.sys.authors, color: "primary"},
                { icon: "mdi-home-group", href: "/publisher", text: "appHeader.publishers", count: this.sys.publishers, color: "primary"},
                { icon: "widgets", href: "/nav", text: "appHeader.tagCategory", count: this.sys.books, color: "primary" },
                { icon: "mdi-tag-heart", href: "/tag", text: "appHeader.tags", count: this.sys.tags, color: "green"},
                { icon: "mdi-library-shelves", href: "/series", text: "appHeader.series", count: this.sys.series, color: "primary"},
                { icon: "mdi-translate", href: "/language", text: "appHeader.languages", color: "primary"},
                { icon: "mdi-history", href: "/all", text: "appHeader.allBooks", color: "primary"},
                { icon: "mdi-bookshelf", href: "/printbooks", text: "appHeader.physicalBooks", color: "primary"},
                { icon: "mdi-star-shooting", href: "/rating", text: "appHeader.rating", color: "orange"},
                { icon: "mdi-trending-up", href: "/hot", text: "appHeader.hotRanking", color: "orange"},
            ];

            const friend_links = [
                {
                    icon: "link",
                    text: "appHeader.friendLinks",
                    color: "primary",
                    groups: this.sys.friends.map((friend) => ({
                        icon: "mdi-open-in-new",
                        href: friend.href,
                        text: friend.text,
                        color: "primary",
                    })),
                }
            ];

            return home_links
                .concat(this.user.is_login ? user_links : [])
                .concat(this.user.is_admin ? admin_links : [])
                .concat(this.user.is_login ? reading_links : [])
                .concat(nav_links)
                .concat(this.sys.friends.length > 0 ? friend_links : [])
        },
    },
    mounted() {
        this.visit_admin_pages = this.isPathMatch("/admin/");
        this.sidebar = true;
        this.miniVariant = false;
        this.$backend("/user/info").then((rsp) => {
            this.err = rsp.err;
            this.sys = rsp.sys;
            this.user = rsp.user;
            this.$store.commit("login", rsp);
            this.$store.commit("set_title", rsp.sys.title);
            this.$store.state.site_title_template = "%s | " + rsp.sys.title;
            this.$store.state.ai_enabled = rsp.sys.aiEnabled;
            this.$store.state.default_page_size = rsp.sys.defaultPageSize;
            this.$store.state.index_page = rsp.sys.indexPage;
            if (rsp.sys.language !== '') {
                this.$i18n.locale = rsp.sys.language;
            }
            if (process.client && rsp.sys.maxUploadSize !== '') {
                localStorage.setItem('max_upload_size', rsp.sys.maxUploadSize);
            }
            if (process.client && rsp.sys.chunkUploadSize !== '') {
                localStorage.setItem('chunk_upload_size', rsp.sys.chunkUploadSize);
            }
            if (process.client && rsp.sys.theme !== '') {
                localStorage.setItem('site_theme', this.sys.theme);
                this.$vuetify.theme.dark = rsp.sys.theme === 'dark';
            }
            if (rsp.sys.footer === '') {
                rsp.sys.footer = this.$t('footer.base_message');
                this.$store.commit("set_footer", rsp.sys.footer);
            }
            if (rsp.sys.header === '') {
                rsp.sys.header = this.$t('appHeader.defaultHeader');
                this.$store.commit("set_header", rsp.sys.header);
            }
            if (rsp.user.is_login) {
                this.sidebar = true;
                this.miniVariant = !this.$vuetify.breakpoint.lgAndUp;
            }
        });
        this.$backend("/user/messages").then((rsp) => {
            if (rsp.err == "ok") {
                this.messages = rsp.messages;
            }
        });

        this.loadRunningTasks();
        this.startTaskPolling();
    },
    beforeDestroy() {
        this.closeAi();
        this.stopTaskPolling();
    },
    methods: {
        isExternalLink(url) {
            return url && (url.startsWith('http://') || url.startsWith('https://'));
        },
        getDefaultAvatar() {
            return window.location.origin + '/avatar/reader.png';
        },
        handleAvatarError(event) {
            event.target.src = this.getDefaultAvatar();
        },
        toggleMiniVariant() {
            if (!this.user.is_login) {
                return;
            }
            this.miniVariant = !this.miniVariant;
            this.sidebar = true;
        },
        handleMouseEnter() {
        },
        handleMouseLeave() {
        },
        toggleAi() {
            if (!this.user.is_login) {
                alert("请先登录以使用AI功能");
                return;
            }
            this.ai_enabled = !this.ai_enabled;
            if (this.ai_enabled) {
                this.connectAi();
                this.$nextTick(() => {
                    if (this.$refs.aiInput) {
                        this.$refs.aiInput.focus();
                    }
                    this.scrollAiBottom();
                });
            } else {
                this.closeAi();
            }
        },
        connectAi() {
            if (this.ai_ws) {
                console.log('WebSocket already connected');
                return;
            }

            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const host = window.location.host;
            const ws_url = `${protocol}//${host}/api/assistant/ws`;

            console.log(`Connecting to AI WebSocket: ${ws_url}`);
            this.ai_ws = new WebSocket(ws_url);

            this.ai_ws.onopen = () => {
                console.log('AI WebSocket connected successfully');
            };

            this.ai_ws.onmessage = (event) => {
                const data = JSON.parse(event.data);
                if (data.type === 'start') {
                    this.ai_thinking = true;
                    this.ai_messages.push({ role: 'assistant', content: '', status: '正在思考...', streaming: true });
                    this.scrollAiBottom();
                } else if (data.type === 'content') {
                    const lastMsg = this.ai_messages[this.ai_messages.length - 1];
                    if (lastMsg) {
                        lastMsg.content += data.content;
                        this.scrollAiBottom();
                    }
                } else if (data.type === 'status') {
                    if (this.ai_messages.length > 0) {
                        const lastMsg = this.ai_messages[this.ai_messages.length - 1];
                        lastMsg.status = data.content;
                    } else {
                        console.log('AI Status:', data.content);
                    }
                } else if (data.type === 'end') {
                    this.ai_thinking = false;
                    const lastMsg = this.ai_messages[this.ai_messages.length - 1];
                    if (lastMsg) {
                        lastMsg.streaming = false;
                        lastMsg.status = '';
                    }
                    this.scrollAiBottom();
                } else if (data.type === 'error') {
                    this.ai_thinking = false;
                    this.ai_messages.push({ role: 'assistant', content: '出错了: ' + data.content, status: 'error' });
                    this.scrollAiBottom();
                }
            };

            this.ai_ws.onerror = (error) => {
                console.error('WebSocket error:', error);
                console.error('Failed to connect to:', ws_url);
                alert('AI连接失败，请检查服务器配置或登录状态');
                this.ai_ws = null;
                this.ai_enabled = false;
                this.ai_thinking = false;
            };

            this.ai_ws.onclose = (event) => {
                console.log('AI WebSocket closed', event.code, event.reason);
                this.ai_ws = null;
                this.ai_thinking = false;
            };
        },
        closeAi() {
            if (this.ai_ws) {
                console.log('Closing AI WebSocket');
                this.ai_ws.close();
                this.ai_ws = null;
            }
            this.ai_enabled = false;
        },
        sendAiMessage() {
            if (!this.ai_input.trim() || this.ai_thinking || !this.ai_ws) return;

            const message = this.ai_input.trim();
            this.ai_input = '';

            this.ai_messages.push({ role: 'user', content: message });

            this.$nextTick(() => {
                this.scrollAiBottom();
            });

            this.ai_ws.send(JSON.stringify({ type: 'query', content: message }));
        },
        scrollAiBottom() {
            this.$nextTick(() => {
                const container = this.$refs.chatMessages;
                if (container) {
                    container.scrollTop = container.scrollHeight;
                }
            });
        },
        chunk: function (arr, len) {
            if (!arr || !Array.isArray(arr)) return [];
            const e = arr.length;
            const r = [];
            for (let idx = 0; idx < e; idx += len) {
                const n = Math.min(idx + len, e);
                r.push(arr.slice(idx, n));
            }
            return r;
        },
        doSearch() {
            if (this.search.trim() !== "") {
                this.$router.push("/search?name=" + this.search.trim());
            } else {
                const ref = this.$refs.mobile_search || this.$refs.search;
                if (ref) {
                    ref.focus();
                }
            }
        },
        hideMsg(idx, msgid) {
            this.$backend("/user/messages", {
                method: "POST",
                body: JSON.stringify({ id: msgid }),
            }).then((rsp) => {
                if (rsp.err == "ok") {
                    this.messages.splice(idx, 1);
                }
            });
        },
        clearAllMessages() {
            this.$backend("/user/messages/clear", {
                method: "POST",
            }).then((rsp) => {
                if (rsp.err == "ok") {
                    this.messages = [];
                }
            });
        },
        loadRunningTasks() {
            if (!this.user.is_login || !this.user.is_admin) {
                this.runningTasks = [];
                return;
            }
            this.$backend("/admin/tasks/running").then((rsp) => {
                if (rsp.err == "ok") {
                    this.runningTasks = rsp.tasks || [];
                }
            }).catch((err) => {
                console.error("Failed to load running tasks:", err);
            });
        },
        startTaskPolling() {
            this.taskPollingTimer = setInterval(() => {
                this.loadRunningTasks();
            }, 10000);
        },
        stopTaskPolling() {
            if (this.taskPollingTimer) {
                clearInterval(this.taskPollingTimer);
                this.taskPollingTimer = null;
            }
        },
        getTaskTypeLabel(serviceType) {
            const typeMap = {
                'autofill': this.$t('appHeader.taskTypeAutofill'),
                'scan': this.$t('appHeader.taskTypeScan'),
                'audio': this.$t('appHeader.taskTypeAudio'),
                'convert': this.$t('appHeader.taskTypeConvert'),
                'ai_fill': this.$t('appHeader.taskTypeAIFill'),
            };
            return typeMap[serviceType] || serviceType;
        },
        getTaskProgress(task) {
            return Math.round(task.progress);
        },
        isGroupExpanded(idx, item) {
            if (this.expandedGroups[idx] !== undefined) {
                return this.expandedGroups[idx];
            }
            return item.expand || false;
        },
        toggleGroup(idx, item) {
            this.$set(this.expandedGroups, idx, !this.isGroupExpanded(idx, item));
        },
        handleMiniVariantGroupClick(idx, item) {
            this.miniVariant = false;
            this.$set(this.expandedGroups, idx, true);
        },
        isPathMatch(path) {
            return this.$route.path.indexOf(path) === 0;
        },
    },
};

</script>

<style>
.avatar-round {
    border-radius: 55% !important;
    overflow: hidden;
}

.avatar-img {
    border-radius: 50% !important;
    width: 100%;
    height: 100%;
    object-fit: cover;
    padding: 2px;
}

.app-navigation-drawer {
    border-right: 2px solid rgba(0, 0, 0, 0.08) !important;
    box-shadow: 2px 0 12px rgba(0, 0, 0, 0.08) !important;
    transition: all 0.3s ease !important;
    border-bottom-right-radius: 12px !important;
}



.app-navigation-drawer ::-webkit-scrollbar {
    width: 8px;
    height: 8px;
}

.app-navigation-drawer ::-webkit-scrollbar-track {
    background: transparent;
    border-radius: 10px;
}

.app-navigation-drawer ::-webkit-scrollbar-thumb {
    background: linear-gradient(135deg, rgba(102, 126, 234, 0.55) 0%, rgba(118, 75, 162, 0.55) 100%);
    border-radius: 10px;
    transition: all 0.3s ease;
}

.app-navigation-drawer ::-webkit-scrollbar-thumb:hover {
    background: linear-gradient(135deg, rgba(118, 75, 162, 0.55) 0%, rgba(102, 126, 234, 0.55) 100%);
    box-shadow: 0 0 10px rgba(102, 126, 234, 0.425);
}

.app-navigation-drawer ::-webkit-scrollbar-corner {
    background: transparent;
}

.app-navigation-drawer::before {
    content: '';
    position: absolute;
    top: 0;
    right: 0;
    width: 1px;
    height: 100%;
    background: linear-gradient(to bottom, transparent, rgba(0, 0, 0, 0.12), transparent);
}

.app-navigation-drawer .v-list {
    padding: 12px 8px !important;
}

.app-navigation-drawer .v-subheader {
    font-weight: 600 !important;
    letter-spacing: 0.5px !important;
    font-size: 0.75rem !important;
    opacity: 0.8 !important;
}

.app-navigation-drawer .v-icon {
    filter: drop-shadow(0 2px 4px rgba(0, 0, 0, 0.2)) drop-shadow(0 1px 2px rgba(0, 0, 0, 0.1));
    transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1) !important;
    transform: translateZ(0);
}

.app-navigation-drawer .v-list-item:hover .v-icon {
    filter: drop-shadow(0 4px 8px rgba(0, 0, 0, 0.3)) drop-shadow(0 2px 4px rgba(0, 0, 0, 0.15));
    transform: translateY(-2px) scale(1.05);
}

.app-navigation-drawer .v-list-item--active .v-icon {
    filter: drop-shadow(0 5px 10px rgba(0, 0, 0, 0.35)) drop-shadow(0 2px 5px rgba(0, 0, 0, 0.2));
    transform: translateY(-2px) scale(1.02);
}

.app-navigation-drawer .v-list-item-action {
    background: linear-gradient(145deg, rgba(255, 255, 255, 0.15), rgba(255, 255, 255, 0.05));
    border-radius: 12px;
    padding: 8px !important;
    box-shadow: inset 0 1px 3px rgba(0, 0, 0, 0.08), 0 1px 2px rgba(255, 255, 255, 0.1);
    transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1) !important;
}

.app-navigation-drawer .v-list-item:hover .v-list-item-action {
    background: linear-gradient(145deg, rgba(255, 255, 255, 0.25), rgba(255, 255, 255, 0.1));
    box-shadow: inset 0 2px 5px rgba(0, 0, 0, 0.12), 0 2px 4px rgba(255, 255, 255, 0.15);
    transform: translateY(-1px);
}

.app-navigation-drawer .v-list-item--active .v-list-item-action {
    background: linear-gradient(145deg, rgba(255, 255, 255, 0.3), rgba(255, 255, 255, 0.15));
    box-shadow: inset 0 2px 6px rgba(0, 0, 0, 0.15), 0 3px 6px rgba(255, 255, 255, 0.2);
    transform: translateY(-1px);
}

.app-navigation-drawer .v-list-item--icon-only {
    justify-content: center;
    padding: 2px 0 !important;
    min-height: 36px !important;
}

.app-navigation-drawer .v-list-item--icon-only .v-icon {
    font-size: 24px;
}

.app-navigation-drawer .v-list-group {
    padding-left: 0 !important;
}

.app-navigation-drawer .v-list-group__header {
    padding-left: 0 !important;
}

.app-navigation-drawer .v-list-group__header > .v-list-item {
    padding-left: 16px !important;
    padding-right: 0 !important;
}

.app-navigation-drawer .v-list-group__header > .v-list-item > .v-list-item__prepend {
    margin-right: 16px !important;
    min-width: auto !important;
}

.app-navigation-drawer .v-list-group__header > .v-list-item > .v-list-item__content {
    margin-right: 48px !important;
}

.app-navigation-drawer .v-list-group__header > .v-list-item > .v-list-item__append {
    position: absolute !important;
    right: 0 !important;
}

.app-navigation-drawer .v-list-group__header > .v-list-item {
    position: relative !important;
}

.app-navigation-drawer .v-list-group__items > .v-list-item {
    padding-left: 48px !important;
}

.v-list-item--disabled {
    opacity: 0.4 !important;
    pointer-events: none !important;
    cursor: not-allowed !important;
}

.v-list-item--disabled .v-icon {
    filter: grayscale(100%) !important;
}

.app-prepend-item {
    min-height: 48px !important;
    height: 48px !important;
    padding-top: 4px !important;
    padding-bottom: 4px !important;
}

.v-list-item.justify-center {
    padding: 4px 0 !important;
    justify-content: center !important;
    transition: none !important;
    transform: none !important;
    min-height: 48px !important;
    height: 48px !important;
}

.v-list-item.justify-center .v-list-item__prepend {
    margin: 0 !important;
}

.v-list-item.justify-center .v-list-item-avatar {
    margin: 0 !important;
    transition: none !important;
    transform: none !important;
}

.v-list-item.justify-center:hover,
.v-list-item.justify-center:active,
.v-list-item.justify-center:focus,
.v-list-item.justify-center:focus-within,
.v-list-item.justify-center:focus-visible {
    transform: none !important;
    transition: none !important;
}

.v-list-item.justify-center .v-list-item__content {
    display: none !important;
}

.v-list-item.justify-center .v-list-item__prepend,
.v-list-item.justify-center .v-list-item__append {
    transition: none !important;
    transform: none !important;
}

.v-list-item.justify-center * {
    transition: none !important;
    transform: none !important;
    animation: none !important;
}

.v-list-item.justify-center::before,
.v-list-item.justify-center::after {
    display: none !important;
}
</style>

<style scoped>
@keyframes blink {
  0%, 50%, 100% { opacity: 1; }
  25%, 75% { opacity: 0; }
}
.blink {
  animation: blink 3s infinite;
}

@keyframes breathing {
  0%, 100% {
    color: white;
    opacity: 0.3;
    transform: scale(1);
  }
  50% {
    color: white;
    opacity: 1;
    transform: scale(1.2);
  }
}

.breathing-light {
  width: 12px !important;
  height: 12px !important;
  background-color: #ffffff !important;
  border-radius: 50% !important;
  animation: breathing 3s ease-in-out infinite !important;
  margin-left: 4px !important;
  margin-right: 4px !important;
  box-shadow: 0 0 6px rgba(255, 255, 255, 0.6) !important;
  background: #ffffff !important;
  color: #ffffff !important;
  border: none !important;
  outline: none !important;
  filter: none !important;
  -webkit-appearance: none !important;
  appearance: none !important;
}

.dialog-border {
    border: 2px solid #e0e0e0 !important;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15) !important;
    border-radius: 8px !important;
}

.dialog-border .v-card__title {
    border-bottom: 1px solid #e0e0e0;
}

.chat-messages {
    overflow-y: auto;
    scroll-behavior: smooth;
}

.chat-messages::-webkit-scrollbar {
    width: 8px;
}

.chat-messages::-webkit-scrollbar-track {
    background: #f1f1f1;
}

.chat-messages::-webkit-scrollbar-thumb {
    background: #cccccc;
    border-radius: 4px;
}

.chat-messages::-webkit-scrollbar-thumb:hover {
    background: #999999;
}

.message-item {
    animation: fadeIn 0.3s ease-in;
}

@keyframes fadeIn {
    from {
        opacity: 0;
        transform: translateY(10px);
    }
    to {
        opacity: 1;
        transform: translateY(0);
    }
}

.message-bubble {
    line-height: 1.6;
    font-size: 14px;
}

.ai-typing {
    display: inline-block;
    width: 2px;
    background-color: orange;
    margin-left: 2px;
    animation: blink 1s infinite;
}
</style>
