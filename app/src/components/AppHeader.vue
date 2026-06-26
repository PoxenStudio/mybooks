<template>
    <div>
        <v-navigation-drawer
            v-if="$store.state.nav"
            v-model="sidebar"
            app
            fixed
            :width="240"
            :mini-variant-width="64"
            :mini-variant="miniVariant"
            :color="drawerColor"
            :clipped="$vuetify.breakpoint.lgAndUp"
            class="app-navigation-drawer"
            @mouseenter="handleMouseEnter"
            @mouseleave="handleMouseLeave"
        >
            <div class="drawer-click-area">
                <v-list dense @click.stop>
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
                                :key="'link-' + (link.href || link.text)"
                                :to="!link.action && !isExternalLink(link.href) ? link.href : undefined"
                                :href="!link.action && isExternalLink(link.href) ? link.href : undefined"
                                :target="!link.action && isExternalLink(link.href) ? '_blank' : undefined"
                                class="v-list-item--group-child"
                                @click="link.action ? handleLinkAction(link.action) : undefined"
                            >
                                <v-list-item-action class="mt-1 mb-1 mr-2" dense>
                                    <img v-if="link.favicon" :src="link.favicon" class="friend-favicon" @error="$event.target.style.display='none'" />
                                    <v-icon v-else class="pa-0 ma-0" :color="link.color || ''">{{ link.icon }}</v-icon>
                                </v-list-item-action>
                                <v-list-item-content>
                                    <v-list-item-title>
                                        {{ $t(link.text) }}
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
                            :class="{ 'v-list-item--icon-only': miniVariant, 'login-button': item.text === 'appHeader.please_login' }"
                            @click="item.action ? handleLinkAction(item.action) : undefined"
                        >
                            <v-list-item-action class="mt-1 mb-1 mr-2" dense v-if="!miniVariant">
                                <v-icon class="pa-0 ma-0" :color="item.color || 'white'">{{ item.icon }}</v-icon>
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
            </div>
            <template v-slot:append v-if="user.is_login">
                <div @click.stop>
                    <v-divider></v-divider>
                    <v-list-item dense to="/logout">
                        <v-list-item-action dense>
                            <v-icon>logout</v-icon>
                        </v-list-item-action>
                        <v-list-item-content v-if="!miniVariant">
                            <v-list-item-title>{{ $t('appHeader.logout') }}</v-list-item-title>
                        </v-list-item-content>
                    </v-list-item>
                </div>
            </template>
        </v-navigation-drawer>

        <v-app-bar v-if="$store.state.nav" class="px-0" color="#003153" dense dark app fixed clipped-left extension-height="64">
            <template v-if="btn_search && $vuetify.breakpoint.xs" #extension>
                <v-container fluid class="py-2">
                    <v-form @submit.prevent="doSearch">
                        <v-text-field
                            solo-inverted
                            hide-details
                            @keyup.enter="doSearch"
                            @focus="isMobileFocused = true"
                            @blur="isMobileFocused = false"
                            ref="mobile_search"
                            v-model="search"
                            :label="$t('appHeader.search')"
                            :loading="ai_thinking"
                            :disabled="ai_thinking"
                            class="mobile-search-field"
                        >
                            <template #prepend-inner>
                                <v-menu
                                    v-model="mobileCategoryMenu"
                                    :close-on-content-click="true"
                                    :nudge-width="120"
                                    offset-y
                                >
                                    <template #activator="{ on, attrs }">
                                        <v-btn
                                            v-bind="attrs"
                                            v-on="on"
                                            class="category-selector"
                                            :class="isMobileFocused ? 'black--text' : 'white--text'"
                                            color="transparent"
                                            style="padding: 3px 8px; margin-right: 8px;"
                                            rounded
                                        >
                                            {{ $t(searchCategories.find(c => c.value === searchCategory)?.label || 'appHeader.searchAll') }}
                                        </v-btn>
                                    </template>
                                    <v-list>
                                        <v-list-item
                                            v-for="category in searchCategories"
                                            :key="category.value"
                                            @click="selectCategory(category.value)"
                                            class="category-item"
                                        >
                                            <v-list-item-title>{{ $t(category.label) }}</v-list-item-title>
                                        </v-list-item>
                                    </v-list>
                                </v-menu>
                            </template>
                            <template #append>
                                <v-btn dark rounded @click="doSearch" color="primary" :disabled="ai_thinking" small>{{ $t('appHeader.search') }}</v-btn>
                            </template>
                        </v-text-field>
                    </v-form>
                </v-container>
            </template>

            <v-tooltip bottom v-if="$store.state.nav">
                <template v-slot:activator="{ on, attrs }">
                    <v-btn icon @click="toggleMiniVariant" v-bind="attrs" v-on="on">
                        <v-avatar color="primary" class="avatar-round" size="36">
                            <img :src="user.is_login ? user.avatar : getGuestAvatar()" @error="handleAvatarError" class="avatar-img" />
                        </v-avatar>
                    </v-btn>
                </template>
                <span v-if="user.is_login">{{ user.username }}({{ user.email }})</span>
                <span v-else>{{ $t('appHeader.not_login') }}</span>
            </v-tooltip>

            <v-toolbar-title class="ml-4 mr-12 align-center d-flex">
                <span>{{ sys.title }}</span>
            </v-toolbar-title>

            <v-spacer></v-spacer>
            <template v-if="$vuetify.breakpoint.smAndUp">
                <v-text-field
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
                    :loading="ai_thinking"
                    :disabled="ai_thinking"
                    class="d-none d-sm-flex ml-8 desktop-search-field"
                >
                    <template #prepend-inner>
                        <v-menu
                            v-model="categoryMenu"
                            :close-on-content-click="true"
                            :nudge-width="120"
                            offset-y
                        >
                            <template #activator="{ on, attrs }">
                                <v-btn
                                    v-bind="attrs"
                                    v-on="on"
                                    rounded
                                    color="transparent"
                                    class="category-selector"
                                    :class="isFocused ? 'black--text' : 'white--text'"
                                    style="padding: 3px 8px; margin-right: 8px;"
                                >
                                    {{ $t(searchCategories.find(c => c.value === searchCategory)?.label || 'appHeader.searchAll') }}
                                </v-btn>
                            </template>
                            <v-list>
                                <v-list-item
                                    v-for="category in searchCategories"
                                    :key="category.value"
                                    @click="selectCategory(category.value)"
                                    class="category-item"
                                >
                                    <v-list-item-title>{{ $t(category.label) }}</v-list-item-title>
                                </v-list-item>
                            </v-list>
                        </v-menu>
                    </template>
                    <template #append>
                        <v-btn v-if="isAiFeatureEnabled" :color="isFocused ? (ai_enabled ? 'orange' : 'grey') : 'transparent'" class="black--text" rounded @click="toggleAi">AI</v-btn>
                    </template>
                </v-text-field>
                <v-spacer></v-spacer>
            </template>

            <v-btn v-else icon class="d-flex d-sm-none" @click="btn_search = !btn_search"> <v-icon>search</v-icon> </v-btn>

            <appearance-menu />

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
                        <v-btn v-on="on" icon color="yellow">
                            <v-badge color="red" class="blink" :content="messages.length > 99 ? '...' : String(messages.length)" overlap>
                                <v-icon>notifications</v-icon>
                            </v-badge>
                        </v-btn>
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

                <v-btn icon v-if="user.is_login" :to="'/logout'" :title="$t('appHeader.logout')">
                    <v-icon>logout</v-icon>
                </v-btn>

            </template>
        </v-app-bar>

        <v-dialog v-model="feedbackDialog" max-width="420">
            <v-card>
                <v-toolbar dark :color="appBarColor">
                    <v-icon left color="white">mdi-comment-question-outline</v-icon>
                    <v-toolbar-title>{{ $t('appHeader.feedbackDialogTitle') }}</v-toolbar-title>
                    <v-spacer></v-spacer>
                    <v-btn icon dark @click="feedbackDialog = false">
                        <v-icon>mdi-close</v-icon>
                    </v-btn>
                </v-toolbar>
                <v-card-text class="text-center pt-6 pb-2">
                    <v-img
                        src="/logo/link_gongzhonghao.jpg"
                        max-width="200"
                        class="mx-auto rounded elevation-2 mb-5"
                        contain
                    ></v-img>
                    <p class="body-1 font-weight-medium mb-1">{{ $t('appHeader.feedbackScanQrCode') }}</p>
                    <p class="body-2 grey--text mt-3 mb-0">{{ $t('appHeader.feedbackOrGithub') }}</p>
                </v-card-text>
                <v-card-actions class="justify-center pb-5">
                    <v-btn
                        outlined
                        color="primary"
                        href="https://github.com/PoxenStudio/mybooks/issues"
                        target="_blank"
                        rel="noopener noreferrer"
                    >
                        <v-icon left small>mdi-github</v-icon>
                        {{ $t('appHeader.feedbackGithubIssues') }}
                    </v-btn>
                </v-card-actions>
            </v-card>
        </v-dialog>

        <v-dialog v-model="memoDialog" max-width="500">
            <v-card>
                <v-toolbar dark :color="appBarColor">
                    <v-icon left color="white">mdi-message-draw</v-icon>
                    <v-toolbar-title>{{ $t('appHeader.memoDialogTitle') }}</v-toolbar-title>
                    <v-spacer></v-spacer>
                    <v-btn icon dark @click="memoDialog = false">
                        <v-icon>mdi-close</v-icon>
                    </v-btn>
                </v-toolbar>
                <v-card-text class="pt-6">
                    <v-select
                        v-model="memoType"
                        :items="[
                            { text: $t('appHeader.memoTypeSuggestion'), value: 0 },
                            { text: $t('appHeader.memoTypeBookRequest'), value: 1 },
                            { text: $t('appHeader.memoTypeHelp'), value: 2 }
                        ]"
                        :label="$t('appHeader.memoTypeLabel')"
                        outlined
                        dense
                    ></v-select>
                    <v-textarea
                        v-model="memoContent"
                        :label="$t('appHeader.memoContentLabel')"
                        :placeholder="$t('appHeader.memoContentPlaceholder')"
                        outlined
                        rows="5"
                        auto-grow
                        hide-details
                    ></v-textarea>
                </v-card-text>
                <v-card-actions class="px-6 pb-4">
                    <v-spacer></v-spacer>
                    <v-btn text @click="memoDialog = false">{{ $t('appHeader.memoCancel') }}</v-btn>
                    <v-btn color="primary" @click="submitMemo" :loading="memoSubmitting">{{ $t('appHeader.memoSubmit') }}</v-btn>
                </v-card-actions>
            </v-card>
        </v-dialog>

        <v-dialog v-model="ai_enabled" persistent max-width="700" scrollable>
            <v-card class="dialog-border d-flex flex-column" style="height: 600px;">
                <v-card-title class="primary white--text py-3 ai-dialog-title">
                    <div left color="white">
                        <svg fill="#ffffff" version="1.1" id="Layer_1" xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="32px" height="32px" viewBox="0 0 256 256" enable-background="new 0 0 256 256" xml:space="preserve" stroke="#ffffff"><g id="bgCarrier" stroke-width="0"></g><g id="tracerCarrier" stroke-linecap="round" stroke-linejoin="round"></g><g id="iconCarrier"> <path d="M98.6,32.6c24,0,43.4,19.4,43.4,43.4s-19.4,43.6-43.4,43.6s-43.4-19.4-43.4-43.4S74.6,32.6,98.6,32.6z M221.8,215.6h-54.4 l25.4-43.8c5.2-9.2,2-20.8-7-26s-20.6-2-25.8,7l-25.4,43.8l-37.8-64.8C93.2,125,86,121.6,77,121.6c-1.2,0-3.8,0.4-5.2,0.8 c-1.2,0.2-3,0.8-4.4,1.2C31,135.6,2.2,193.8,2.2,254c1,0,87.4,0,109.4,0c-0.8-1.2-1.6-2.2-2.4-3.4L65.4,175c-1.4-2.6-0.4-6,2-7.4 c2.6-1.4,6-0.4,7.4,2l43.4,75c3.2,5.6,9.2,9.4,16.2,9.4h87.4c10.6,0,19-8.6,19-19C241,224,232.2,215.6,221.8,215.6z M203.613,29.883 v-6.156l-6.453-1.09c-0.477-2.109-1.309-4.086-2.43-5.863l3.793-5.332l-4.355-4.355l-5.332,3.793 c-1.773-1.121-3.75-1.949-5.863-2.43L181.887,2h-6.16l-1.086,6.449c-2.113,0.48-4.09,1.309-5.863,2.43l-5.332-3.793l-4.355,4.355 l3.793,5.332c-1.121,1.777-1.953,3.754-2.43,5.863L154,23.727v6.156l6.453,1.086c0.477,2.113,1.309,4.09,2.43,5.867l-3.793,5.332 l4.355,4.352l5.332-3.793c1.773,1.121,3.75,1.953,5.863,2.43l1.086,6.453h6.16l1.086-6.453c2.113-0.477,4.09-1.309,5.863-2.43 l5.332,3.793l4.355-4.352l-3.793-5.332c1.121-1.777,1.953-3.754,2.43-5.867L203.613,29.883z M178.805,36.594 c-5.402,0-9.785-4.383-9.785-9.789s4.383-9.789,9.785-9.789c5.406,0,9.789,4.383,9.789,9.789S184.211,36.594,178.805,36.594z M246.48,65.19l7.52-4.667l-3.154-7.707l-8.635,1.943c-1.629-2.327-3.659-4.397-6.043-6.096l2.017-8.616l-7.68-3.22l-4.73,7.479 c-2.883-0.509-5.782-0.505-8.584-0.035l-4.668-7.52l-7.707,3.154l1.943,8.635c-2.327,1.629-4.397,3.659-6.096,6.043l-8.616-2.017 l-3.22,7.68l7.479,4.73c-0.509,2.883-0.505,5.782-0.035,8.584l-7.52,4.668l3.154,7.707l8.635-1.943 c1.629,2.327,3.659,4.397,6.043,6.096l-2.017,8.616l7.68,3.22l4.73-7.479c2.883,0.509,5.782,0.505,8.584,0.035l4.668,7.52 l7.707-3.154l-1.943-8.635c2.327-1.629,4.397-3.659,6.096-6.043l8.616,2.017l3.22-7.68l-7.479-4.73 C246.953,70.891,246.95,67.992,246.48,65.19z M233.584,74.493c-2.827,6.743-10.584,9.918-17.327,7.091 c-6.743-2.827-9.918-10.584-7.091-17.327s10.584-9.918,17.327-7.091C233.236,59.993,236.41,67.75,233.584,74.493z"></path></g></svg>
                    </div>
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
import AppearanceMenu from "~/components/AppearanceMenu.vue";

export default {
    components: { AppearanceMenu },
    data() {
        let sidebar = false;
        let miniVariant = false;

        if (process.client) {
            const isLargeScreen = window.innerWidth >= 1280;
            const savedSidebar = localStorage.getItem('drawerSidebar');
            const savedMiniVariant = localStorage.getItem('drawerMiniVariant');

            if (isLargeScreen) {
                if (savedMiniVariant !== null) {
                    miniVariant = savedMiniVariant === 'true';
                    sidebar = true;
                } else if (savedSidebar !== null) {
                    sidebar = savedSidebar === 'true';
                }
            }
        }

        return {
            err: "",
            sidebar,
            miniVariant,
        right: null,
        btn_search: false,
        search: "",
        searchCategory: 'all',
        searchCategories: [
            { value: 'all', label: 'appHeader.searchAll' },
            { value: 'title', label: 'appHeader.searchTitle' },
            { value: 'title_sort', label: 'appHeader.searchTitleSort' },
            { value: 'author', label: 'appHeader.searchAuthor' },
            { value: 'isbn', label: 'appHeader.searchISBN' },
            { value: 'comments', label: 'appHeader.searchComments' },
            { value: 'tags', label: 'appHeader.searchTags' },
            { value: 'series', label: 'appHeader.searchSeries' },
        ],
        categoryMenu: false,
        mobileCategoryMenu: false,
        isFocused: false,
        isMobileFocused: false,
        ai_enabled: false,
        ai_thinking: false,
        ai_messages: [],
        ai_ws: null,
        ai_input: '',
        user: { is_login: false },
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
        feedbackDialog: false,
        memoDialog: false,
        memoType: 0,
        memoContent: '',
        memoSubmitting: false,
    };
    },
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
            const login_link = { icon: "account_circle", href: "/login", text: "appHeader.please_login", color:"white" };
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
                        { icon: "mdi-shield-account", href: "/soledbooks", text: "appHeader.soledBooks", color: "#EDC10A"},
                        { icon: "mdi-notebook", href: "/expected", text: "expected.title", color: "green"},
                    ],
                }
            ];
            const admin_links = [
                {
                    icon: "mdi-cog",
                    text: "appHeader.admin",
                    expand: this.isPathMatch("/admin/"),
                    color: "orange",
                    groups: [
                        { icon: "mdi-cog", href: "/admin/settings", text: "appHeader.systemSettings", color: "primary"},
                        { icon: "mdi-account", href: "/admin/users", text: "appHeader.userManagement", color: "#EDC10A"},
                        { icon: "mdi-import", href: "/admin/imports", text: "appHeader.importBooks", color: "green"},
                        { icon: "mdi-library-shelves", href: "/admin/books", text: "appHeader.bookManagement", color: "primary"},
                        { icon: "mdi-notebook", href: "/admin/all-expected", text: "expected.allPageTitle", color: "green"},
                        { icon: "mdi-message-text-outline", href: "/admin/user-memos", text: "memos.pageTitle", color: "blue"},
                        { icon: "mdi-math-log", href: "/admin/syslog", text: "appHeader.syslog", color: "#FB9795"},
                        { icon: "mdi-toolbox-outline", href: "/admin/toolbox", text: "appHeader.toolbox", color: "#FB9795"},
                        { icon: "mdi-rhombus-split", href: "/admin/resources", text: "appHeader.resources", color: "teal"},
                        { icon: "sms_failed", action: "openFeedback", text: "appHeader.feedback", color: "orange"},
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
                { icon: "widgets", href: "/nav", text: "appHeader.tagCategory", count: this.sys.books, color: "primary" },
                { icon: "mdi-tag-heart", href: "/tag", text: "appHeader.tags", count: this.sys.tags, color: "green"},
                { icon: "mdi-home-group", href: "/publisher", text: "appHeader.publishers", count: this.sys.publishers, color: "primary"},
                { icon: "mdi-bookshelf", href: "/printbooks", text: "appHeader.physicalBooks", count: this.sys.physicals, color: "orange"},
                { icon: "mdi-library-shelves", href: "/series", text: "appHeader.series", count: this.sys.series, color: "primary"},
                { icon: "mdi-translate", href: "/language", text: "appHeader.languages", color: "purple"},
                { icon: "mdi-check-all", href: "/all", text: "appHeader.allBooks", color: "primary"},
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
                        favicon: friend.icon || "",
                    })),
                }
            ];

            const memo_link = [
                {
                    icon: "mdi-message-text-outline",
                    text: "appHeader.memo",
                    color: "green",
                    ...(this.user.is_login ? { href: "/memos" } : { action: "openMemo" })
                },
            ];

            return [].concat(this.user.is_login ? [] : [login_link])
                .concat(home_links)
                .concat(this.user.is_login ? user_links : [])
                .concat(this.user.is_admin ? admin_links : [])
                .concat(this.user.is_login ? reading_links : [])
                .concat(nav_links)
                .concat(memo_link)
                .concat(this.sys.friends.length > 0 ? friend_links : [])
        },
    },
    mounted() {
        // Load saved search category from localStorage
        if (process.client) {
            const savedCategory = localStorage.getItem('searchCategory');
            if (savedCategory) {
                this.searchCategory = savedCategory;
            }
        }

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
            localStorage.setItem('sys_title', rsp.sys.title);
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
                localStorage.setItem('site_theme', rsp.sys.theme);
                const userAppearanceSettings = localStorage.getItem('appearance_settings');
                if (!userAppearanceSettings) {
                    this.$vuetify.theme.dark = rsp.sys.theme === 'dark';
                }
            }
            if (rsp.sys.footer === '') {
                rsp.sys.footer = this.$t('appHeader.defaultFooter');
                this.$store.commit("set_footer", rsp.sys.footer);
            }
            this.$store.commit("set_footer_watermark", rsp.sys.footer_watermark);
            this.$store.commit("set_standalone", rsp.sys.standalone);
            this.$store.commit("set_hide_project_links", rsp.sys.hide_project_links);
            if (rsp.user.is_login) {
                if (process.client && localStorage.getItem('drawerSidebar') === null) {
                    this.sidebar = this.$vuetify.breakpoint.lgAndUp;
                    localStorage.setItem('drawerSidebar', this.sidebar);
                }
                if (process.client && localStorage.getItem('drawerMiniVariant') === null) {
                    this.miniVariant = this.$vuetify.breakpoint.lgAndUp;
                    localStorage.setItem('drawerMiniVariant', this.miniVariant);
                }
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
            if (process.client) {
                return window.location.origin + '/avatar/reader.svg';
            }
            return '/avatar/reader.svg';
        },
        getGuestAvatar() {
            if (process.client) {
                return window.location.origin + '/icons/user-guest.svg';
            }
            return '/icons/user-guest.svg';
        },
        handleAvatarError(event) {
            event.target.src = this.getDefaultAvatar();
        },
        toggleMiniVariant() {
            if (!this.sidebar) {
                this.sidebar = true;
                this.miniVariant = false;
            } else {
                this.miniVariant = !this.miniVariant;
            }
            if (process.client) {
                localStorage.setItem('drawerSidebar', this.sidebar);
                localStorage.setItem('drawerMiniVariant', this.miniVariant);
            }
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
                    this.ai_messages.push({ role: 'assistant', content: '', status: '......', streaming: true });
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
                    this.ai_messages.push({ role: 'assistant', content: 'ERROR: ' + data.content, status: 'error' });
                    this.scrollAiBottom();
                }
            };

            this.ai_ws.onerror = (error) => {
                console.error('WebSocket error:', error);
                console.error('Failed to connect to:', ws_url);
                alert(this.$t('appHeader.aiConnectionError'));
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
        selectCategory(category) {
            this.searchCategory = category;
            this.categoryMenu = false;
            // Save the selected category to localStorage
            if (process.client) {
                localStorage.setItem('searchCategory', category);
            }
        },
        doSearch() {
            if (this.search.trim() !== "") {
                let searchText = this.search.trim();

                // Add the appropriate prefix based on selected category
                if (this.searchCategory !== 'all') {
                    searchText = searchText.replace(/^(title:|title_sort:|author:|isbn:|comments:|tags:|series:|#)/i, '').trim();
                    searchText = this.searchCategory + ':' + searchText;
                }

                // Save the selected category to localStorage
                if (process.client) {
                    localStorage.setItem('searchCategory', this.searchCategory);
                }

                this.$router.push("/search?name=" + searchText);
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
                    this.messages = rsp.messages || this.messages;
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
                'audio_import': this.$t('appHeader.taskTypeAudioImport'),
                'convert': this.$t('appHeader.taskTypeConvert'),
                'ai_fill': this.$t('appHeader.taskTypeAIFill'),
                'title_sort_update': this.$t('appHeader.taskTypeTitleSortUpdate'),
                'metadata_update': this.$t('appHeader.taskTypeMetadataUpdate'),
                'cover_update': this.$t('appHeader.taskTypeCoverUpdate'),
                'save_meta': this.$t('appHeader.taskTypeSaveMeta'),
            };
            return typeMap[serviceType] || "";
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
            if (process.client) {
                localStorage.setItem('drawerMiniVariant', this.miniVariant);
            }
        },
        isPathMatch(path) {
            return this.$route.path.indexOf(path) === 0;
        },
        handleLinkAction(action) {
            if (action === 'openFeedback') {
                this.feedbackDialog = true;
            } else if (action === 'openMemo') {
                this.resetMemo();
                this.memoDialog = true;
            }
        },
        submitMemo() {
            if (!this.memoContent.trim()) {
                this.$store.commit('show_snackbar', { message: this.$t('appHeader.memoContentRequired'), color: 'error' });
                return;
            }
            this.memoSubmitting = true;
            this.$backend("/user/memo", {
                method: "POST",
                body: JSON.stringify({
                    memo: this.memoContent.trim(),
                    memo_type: this.memoType
                })
            }).then(rsp => {
                this.memoSubmitting = false;
                if (rsp.err === 'ok') {
                    this.$store.commit('show_snackbar', { message: this.$t('appHeader.memoSubmitSuccess'), color: 'success' });
                    this.memoDialog = false;
                    this.resetMemo();
                } else {
                    this.$store.commit('show_snackbar', { message: rsp.msg || this.$t('appHeader.memoSubmitFailed'), color: 'error' });
                }
            }).catch(() => {
                this.memoSubmitting = false;
                this.$store.commit('show_snackbar', { message: this.$t('appHeader.memoSubmitFailed'), color: 'error' });
            });
        },
        resetMemo() {
            this.memoType = 0;
            this.memoContent = '';
        },
    },
};

</script>

<style>
.avatar-round {
    border-radius: 55% !important;
    overflow: hidden;
    animation: breathing-avatar 3s ease-in-out infinite;
    box-shadow: 0 0 8px rgba(255, 255, 255, 0.6);
}

@keyframes breathing-avatar {
    0%, 100% {
        box-shadow: 0 0 8px rgba(255, 255, 255, 0.3);
        transform: scale(1);
    }
    50% {
        box-shadow: 0 0 16px rgba(255, 255, 255, 0.9);
        transform: scale(1.05);
    }
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
    transition: background-color 0.2s ease, border-color 0.2s ease, box-shadow 0.2s ease !important;
    border-bottom-right-radius: 12px !important;
    top: 56px !important;
    height: calc(100vh - 56px) !important;
    opacity: 1 !important;
}

.theme--dark .app-navigation-drawer {
    border-right-color: rgba(255, 255, 255, 0.08) !important;
    box-shadow: 2px 0 12px rgba(0, 0, 0, 0.3) !important;
}

@media (max-width: 1024px) {
    .app-navigation-drawer {
        top: 56px !important;
        height: calc(100vh - 56px) !important;
        opacity: 1 !important;
    }
}

.app-navigation-drawer .v-list-item {
    position: relative !important;
    z-index: 1 !important;
    opacity: 1 !important;
}

.app-navigation-drawer .v-list-group {
    position: relative !important;
    z-index: 1 !important;
}

.app-navigation-drawer .v-list-item--icon-only {
    z-index: 2 !important;
    opacity: 1 !important;
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

.login-button {
    background-color: #01847f !important;
    border-radius: 8px !important;
    margin: 3px 0 !important;
    padding: 3px !important;
    color: white !important;
}

.login-button .v-list-item-title {
    font-size: 16px !important;
    font-weight: bold !important;
    color: white !important;
}

.login-button .v-icon {
    margin-left: 12px !important;
}

.app-navigation-drawer .v-list-item--icon-only.login-button .v-icon {
    margin-left: 0 !important;
    color: white !important;
}

.app-navigation-drawer .v-subheader {
    font-weight: 600 !important;
    letter-spacing: 0.5px !important;
    font-size: 0.75rem !important;
    opacity: 0.8 !important;
}

.app-navigation-drawer .v-list--dense .v-list-item .v-list-item__title,
.app-navigation-drawer .v-list-item--dense .v-list-item__title {
    font-size: 0.9rem !important; /* 1rem = 16px (默认字体大小) */
    font-weight: 500 !important;
    line-height: 1.25rem !important;
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

.app-navigation-drawer .v-list-group__items > .v-list-item--group-child {
    padding-left: 48px !important;
    min-height: 40px !important;
    position: relative !important;
    z-index: 1 !important;
    opacity: 1 !important;
}

.app-navigation-drawer .v-list-group__items > .v-list-item--group-child .v-list-item-action {
    margin-right: 12px !important;
}

.app-navigation-drawer .v-list-group__items {
    position: relative !important;
    z-index: 1 !important;
    opacity: 1 !important;
}

.app-navigation-drawer .v-list-group__items > .v-list-item--group-child:hover {
    background: linear-gradient(90deg, rgba(102, 126, 234, 0.08) 0%, rgba(102, 126, 234, 0.02) 100%);
    border-radius: 0 8px 8px 0;
}

.app-navigation-drawer .v-list-group__items > .v-list-item--active {
    background: linear-gradient(90deg, rgba(102, 126, 234, 0.15) 0%, rgba(102, 126, 234, 0.05) 100%);
    border-radius: 0 8px 8px 0;
}

.theme--light .app-navigation-drawer .v-list-group__items > .v-list-item--group-child.v-list-item--active {
    color: rgba(0, 0, 0, 0.87) !important;
    caret-color: rgba(0, 0, 0, 0.87) !important;
}

.theme--dark .app-navigation-drawer .v-list-group__items > .v-list-item--group-child.v-list-item--active {
    color: rgba(255, 255, 255, 0.87) !important;
    caret-color: rgba(255, 255, 255, 0.87) !important;
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

@media (max-width: 1024px) {
    .v-navigation-drawer--temporary {
        box-shadow: 2px 0 12px rgba(0, 0, 0, 0.2) !important;
    }

    .v-navigation-drawer--temporary .v-navigation-drawer__scrim {
        opacity: 0.5 !important;
        background-color: rgba(0, 0, 0, 0.5) !important;
    }

    .app-navigation-drawer {
        box-shadow: 4px 0 20px rgba(0, 0, 0, 0.15) !important;
    }
}

.friend-favicon {
    width: 20px;
    height: 20px;
    object-fit: contain;
    border-radius: 50%;
    background-color: #ffffff;
    padding: 2px;
    filter: drop-shadow(0 1px 2px rgba(0, 0, 0, 0.15));
}

.v-application .primary.ai-dialog-title {
    background-color: #003153 !important;
    border-color: #003153 !important;
}
</style>

<style scoped>
.category-selector {
    border: 1px dashed rgba(255, 255, 255, 0.2) !important;
}
/* Search field highlight styles */
.desktop-search-field :deep(.v-input__slot),
.mobile-search-field :deep(.v-input__slot) {
    border: 2px solid rgba(255, 255, 255, 0.55) !important;
    border-radius: 24px !important;
    margin-bottom: 2px;
    transition: border-color 0.25s ease, box-shadow 0.25s ease !important;
}

/* light theme focused: bg turns dark → white border */
.desktop-search-field.v-input--is-focused :deep(.v-input__slot),
.mobile-search-field.v-input--is-focused :deep(.v-input__slot) {
    border-color: rgba(255, 255, 255, 0.95) !important;
    box-shadow: 0 0 0 2px rgba(255, 255, 255, 0.2) !important;
}

/* dark theme focused: solo-inverted bg turns white/light → dark border */
.theme--dark .desktop-search-field.v-input--is-focused :deep(.v-input__slot),
.theme--dark .mobile-search-field.v-input--is-focused :deep(.v-input__slot) {
    border-color: rgba(0, 0, 0, 0.6) !important;
    box-shadow: 0 0 0 2px rgba(0, 0, 0, 0.15) !important;
}

/* dark theme default: keep border visible against dark bg */
.theme--dark .desktop-search-field :deep(.v-input__slot),
.theme--dark .mobile-search-field :deep(.v-input__slot) {
    border-color: rgba(255, 255, 255, 0.35) !important;
}

@keyframes blink {
  0%, 50%, 100% { opacity: 1; }
  25%, 75% { opacity: 0.0; }
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
