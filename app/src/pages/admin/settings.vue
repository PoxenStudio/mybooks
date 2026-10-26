<template>
  <div class="settings-page-root">
    <div class="d-flex justify-end flex-wrap mb-2" style="gap: 8px">
      <v-btn
        class="settings-hint-btn"
        href="https://www.zhihu.com/ring/host/2091200432408376415"
        target="_blank"
        rel="noopener"
      >
        <v-icon left>mdi-forum-outline</v-icon>
        {{ $t('settings.community') }}
      </v-btn>
      <v-btn
        class="settings-hint-btn"
        href="https://www.mybooks.top/docs/manual/"
        target="_blank"
        rel="noopener"
      >
        <v-icon left>mdi-lightbulb-question-outline</v-icon>
        {{ $t('settings.hint') }}
      </v-btn>
    </div>

    <v-sheet elevation="2" class="settings-group-bar">
      <div class="settings-group-bar-row d-flex align-center">
        <div class="settings-seg" role="tablist">
          <span class="settings-seg-indicator" ref="segIndicator"></span>
          <button
            v-for="(g, gi) in groups"
            :key="g.id"
            :id="'group-tab-' + g.id"
            type="button"
            role="tab"
            class="settings-seg-btn"
            :class="{ 'is-active': activeGroup === g.id && !searchQuery }"
            :aria-selected="activeGroup === g.id && !searchQuery"
            aria-controls="settings-group-panel"
            :tabindex="activeGroup === g.id ? 0 : -1"
            @click="selectGroup(g.id)"
            @keydown.left.prevent="focusGroupTab(gi - 1)"
            @keydown.right.prevent="focusGroupTab(gi + 1)"
          >
            <v-icon small>{{ g.icon }}</v-icon>
            {{ $t(g.title) }}
            <span class="settings-seg-bar" :style="{ background: groupAccent(g.id) }"></span>
          </button>
        </div>
        <div class="settings-bar-right d-flex align-center">
          <!-- 稳定的 live region：chips 是 v-if/v-else 互换的节点，直接挂 aria-live 不保证播报 -->
          <span v-if="dirtyCount > 0" class="settings-status-chip-wrap" role="status" aria-live="polite">
            <v-chip
              color="orange"
              text-color="white"
              small
              class="settings-status-chip settings-status-chip-clickable"
              role="button"
              tabindex="0"
              :title="$t('settings.unsaved_jump_tip', { n: dirtyCount })"
              aria-describedby="settings-dirty-jump-tip"
              @click="jumpToNextDirty"
              @keydown.enter.prevent="jumpToNextDirty"
              @keydown.space.prevent="jumpToNextDirty"
            >
              {{ $t('settings.unsaved_changes', { n: dirtyCount }) }}
            </v-chip>
          </span>
          <!--
            跳转提示放这里而不是当 aria-label：
            1) 覆盖可见文本的话，读屏播报的是操作指引而不是「N 项未保存」这个数字；
            2) 它也不能落在上面那个 role="status" 里，否则每次计数变化都会重播一遍指引。
            只做描述，播报仍以 visible text（含计数）为准。
          -->
          <span
            v-if="dirtyCount > 0"
            id="settings-dirty-jump-tip"
            class="settings-sr-only"
          >{{ $t('settings.unsaved_jump_tip', { n: dirtyCount }) }}</span>
          <v-btn
            v-if="!searchOpen"
            icon
            class="settings-search-btn"
            :aria-label="$t('settings.search_placeholder')"
            @click="openSearch"
          >
            <v-icon>mdi-magnify</v-icon>
          </v-btn>
          <v-expand-x-transition>
            <v-text-field
              v-show="searchOpen"
              ref="searchField"
              v-model="searchQ"
              class="settings-search settings-search-expanded"
              dense
              outlined
              rounded
              hide-details
              prepend-inner-icon="mdi-magnify"
              append-icon="mdi-close"
              :placeholder="$t('settings.search_placeholder')"
              :aria-label="$t('settings.search_placeholder')"
              @click:append="closeSearch"
              @keydown.esc="closeSearch"
              @blur="onSearchBlur"
            ></v-text-field>
          </v-expand-x-transition>
        </div>
      </div>
    </v-sheet>

    <v-card v-if="searchQuery" class="my-2 elevation-4">
      <v-card-title>{{ $t('settings.search_results', { n: results.length }) }}</v-card-title>
      <v-card-text style="padding: 0 16px 16px">
        <p v-if="results.length === 0" class="grey--text">{{ $t('settings.search_no_results') }}</p>
        <template v-else>
          <div
            v-for="r in results"
            :key="r.key"
            class="settings-result d-flex align-center py-2"
            role="button"
            tabindex="0"
            @click="jumpTo(r)"
            @keydown.enter="jumpTo(r)"
            @keydown.space.prevent="jumpTo(r)"
          >
            <v-icon small class="mr-3" :color="r.red ? 'red' : 'grey'">{{ r.icon }}</v-icon>
            <div class="flex-grow-1">
              <div>{{ r.label }}</div>
              <div class="text-caption grey--text">{{ r.path }}</div>
            </div>
            <v-icon small color="grey">mdi-chevron-right</v-icon>
          </div>
        </template>
      </v-card-text>
    </v-card>

    <template v-else>
      <div
        v-for="g in currentGroups"
        :key="g.id"
        id="settings-group-panel"
        role="tabpanel"
        :aria-labelledby="'group-tab-' + g.id"
      >
        <v-card
          v-for="s in g.sections"
          :key="g.id + '-' + s.id"
          :id="'sec-' + g.id + '-' + s.id"
          class="my-2 elevation-4"
        >
          <v-card-title>
            <v-icon small color="primary" class="mr-2">{{ s.icon }}</v-icon>
            {{ $t(s.title) }}
          </v-card-title>
          <v-card-text style="padding: 8px 20px 20px">
            <p v-if="s.desc">{{ $t(s.desc) }}</p>
            <template v-if="s.tips">
              <p v-for="t in s.tips" :key="t.text">
                {{ $t(t.text) }}
                <a v-if="t.link" target="_blank" :href="t.link">{{
                  $t("settings.link")
                }}</a>
              </p>
            </template>

            <div class="pl-6" v-if="s.fields && s.fields.length" :class="{ 'settings-fields-2col': s.fields.some((x) => x.half) }">
            <template v-for="f in s.fields">
              <div :key="'w-' + f.key" :id="'f-' + f.key" :class="f.half ? 'settings-field-half' : 'settings-field-full'">
              <template v-if="f.type === 'checkbox'">
                <v-checkbox
                  small
                  hide-details
                  :input-value="isCheckboxInputValue(f)"
                  :disabled="isFieldLockedBy(f)"
                  :key="f.key + '-checkbox'"
                  :label="$t(f.label)"
                  @change="onCheckboxChange(f, $event)"
                >
                  <template v-if="f.icon" v-slot:prepend>
                    <v-icon :color="f.color">{{ f.icon }}</v-icon>
                  </template>
                </v-checkbox>
                <div v-if="f.tips" class="text-caption grey--text ml-8">{{ $t(f.tips) }}</div>
              </template>
              <div
                v-else-if="f.type === 'checkbox_list'"
                :key="f.key + '-checkbox_list'"
                class="mb-2"
              >
                <div class="d-flex align-center mt-2">
                  <v-icon class="mr-2" :color="f.color">{{ f.icon }}</v-icon>
                  <span class="text-body-1">{{ $t(f.label) }}</span>
                </div>
                <div v-if="f.tips" class="text-caption grey--text ml-8">{{ $t(f.tips) }}</div>
                <div class="pl-8">
                  <v-row dense>
                    <v-col
                      v-for="opt in f.items"
                      :key="f.key + '-' + opt.value"
                      cols="12"
                      sm="6"
                      md="4"
                    >
                      <v-checkbox
                        :input-value="checkboxListInputValue(f)"
                        :value="opt.value"
                        :disabled="isCheckboxOptionLocked(f, opt)"
                        :label="$t(opt.text)"
                        dense
                        hide-details
                        class="mt-0"
                        @change="onCheckboxListChange(f, $event)"
                      ></v-checkbox>
                    </v-col>
                  </v-row>
                </div>
              </div>
              <div
                v-else-if="f.type === 'subtitle'"
                :key="f.key + '-subtitle'"
                class="d-flex align-center mt-2 mb-1"
              >
                <v-icon small class="mr-2" :color="f.color">{{ f.icon }}</v-icon>
                <span class="text-body-1">{{ $t(f.label) }}</span>
              </div>
              <v-textarea
                outlined
                v-else-if="f.type === 'textarea'"
                v-model="settings[f.key]"
                :key="f.key + '-textarea'"
                :label="$t(f.label)"
              >
                <template v-if="f.icon" v-slot:prepend>
                  <v-icon :color="f.color">{{ f.icon }}</v-icon>
                </template>
              </v-textarea>
              <v-select
                small
                v-else-if="f.type === 'select'"
                v-model="settings[f.key]"
                :items="f.items"
                :key="f.key + '-select'"
                :label="$t(f.label)"
              >
                <template v-if="f.icon" v-slot:prepend>
                  <v-icon :color="f.color">{{ f.icon }}</v-icon>
                </template>
                <template v-slot:item="{ item, attrs, on }">
                  <v-list-item v-on="on" v-bind="attrs">
                    <v-list-item-icon v-if="item.icon">
                      <v-icon>{{ item.icon }}</v-icon>
                    </v-list-item-icon>
                    <v-list-item-content>
                      <v-list-item-title>{{ item.text }}</v-list-item-title>
                    </v-list-item-content>
                  </v-list-item>
                </template>
                <template v-slot:selection="{ item }">
                  <v-icon v-if="item.icon" left>{{ item.icon }}</v-icon>
                  {{ item.text }}
                </template>
              </v-select>
              <v-select
                small
                v-else-if="f.type === 'select_image'"
                v-model="settings[f.key]"
                :items="f.items"
                :key="f.key + '-select_image'"
                :label="$t(f.label)"
              >
                <template v-if="f.icon" v-slot:prepend>
                  <v-icon :color="f.color">{{ f.icon }}</v-icon>
                </template>
                <template #item="{ item }">
                  <v-img
                    :src="siteIconSrc(item)"
                    max-width="32"
                    max-height="32"
                  />
                </template>
                <template #selection="{ item }">
                  <v-img
                    :src="siteIconSrc(item)"
                    max-width="32"
                    max-height="32"
                  />
                </template>
              </v-select>
              <template v-else-if="f.type === 'meta_sources'">
                <v-select
                  :key="f.key + '-meta_sources'"
                  small
                  ref="metaSourceSelect"
                  v-model="settings['META_SELECTED_SOURCES']"
                  :items="metaSourceItems"
                  :label="$t(f.label)"
                  multiple
                  chips
                  small-chips
                >
                  <template v-slot:selection="{ item }">
                    <v-chip
                      small
                      @click.stop="
                        $refs.metaSourceSelect[0]
                          ? $refs.metaSourceSelect[0].activateMenu()
                          : $refs.metaSourceSelect.activateMenu()
                      "
                    >
                      {{ item.text }}
                    </v-chip>
                  </template>
                  <template v-slot:item="{ item, attrs, on }">
                    <v-list-item v-on="on" v-bind="attrs">
                      <v-list-item-action>
                        <v-checkbox
                          :input-value="attrs.inputValue"
                          color="primary"
                        ></v-checkbox>
                      </v-list-item-action>
                      <v-list-item-content>
                        <v-list-item-title>{{ item.text }}</v-list-item-title>
                      </v-list-item-content>
                    </v-list-item>
                  </template>
                  <template v-if="f.icon" v-slot:prepend>
                    <v-icon :color="f.color">{{ f.icon }}</v-icon>
                  </template>
                </v-select>
              </template>
              <book-nav-editor
                v-else-if="f.type === 'book_nav'"
                :key="f.key + '-book_nav'"
                v-model="bookNavList"
              ></book-nav-editor>
              <v-text-field
                v-else-if="f.type === 'number'"
                v-model.number="settings[f.key]"
                :key="f.key + '-number'"
                :label="$t(f.label)"
                type="number"
                min="0"
              >
                <template v-if="f.icon" v-slot:prepend>
                  <v-icon :color="f.color">{{ f.icon }}</v-icon>
                </template>
              </v-text-field>
              <v-text-field
                v-else
                v-model="settings[f.key]"
                :key="f.key + '-text'"
                :label="$t(f.label)"
                type="text"
                :hint="f.hint ? $t(f.hint) : undefined"
                :persistent-hint="!!f.hint"
              >
                <template v-if="f.icon" v-slot:prepend>
                  <v-icon :color="f.color">{{ f.icon }}</v-icon>
                </template>
              </v-text-field>
              </div>
            </template>
            </div>

            <template v-for="b in (s.actions || [])">
              <v-btn :key="b.label" @click="run(b.action)" color="primary"
                ><v-icon>{{ b.icon }}</v-icon
                >{{ $t(b.label) }}</v-btn
              >
            </template>

            <div class="pl-6" v-if="s.groups && s.groups.length">
            <template v-for="grp in s.groups">
              <!-- 父开关本身也能改脏，必须给出 f-<key> 锚点，否则逐项跳转会退回整张卡片 -->
              <div :key="'w-' + grp.key" :id="'f-' + grp.key">
              <v-checkbox
                small
                hide-details
                v-model="settings[grp.key]"
                :label="$t(grp.label)"
                :prepend-icon="grp.icon"
                @change="$delete(forceOpen, grp.key)"
              >
              </v-checkbox>
              </div>
              <template v-if="settings[grp.key] || forceOpen[grp.key]">
                <div class="pl-6" :key="grp.key + '-fields'">
                <template v-for="f in grp.fields">
                  <div :key="'w-' + f.key" :id="'f-' + f.key">
                  <v-checkbox
                    small
                    hide-details
                    v-if="f.type === 'checkbox'"
                    :prepend-icon="f.icon"
                    v-model="settings[f.key]"
                    :key="f.key + '-checkbox'"
                    :label="$t(f.label)"
                  ></v-checkbox>
                  <v-textarea
                    outlined
                    v-else-if="f.type === 'textarea'"
                    :prepend-icon="f.icon"
                    v-model="settings[f.key]"
                    :key="f.key"
                    :label="$t(f.label)"
                  ></v-textarea>
                  <div
                    v-else-if="f.type === 'reading_range'"
                    :key="f.key + '-reading_range'"
                  >
                    <p class="mb-2">{{ defaultReadRangeSummary }}</p>
                    <v-btn
                      color="primary"
                      @click="openDefaultReadRangeDialog"
                    >
                      <v-icon left>mdi-book-cog-outline</v-icon>
                      {{ $t(f.label) }}
                    </v-btn>
                  </div>
                  <v-text-field
                    v-else
                    :prepend-icon="f.icon"
                    v-model="settings[f.key]"
                    :key="f.key + '-text'"
                    :label="$t(f.label)"
                    type="text"
                  ></v-text-field>
                  </div>
                </template>
                </div>
              </template>
            </template>
            </div>

            <template v-if="s.special === 'homepage_cards'">
              <div id="f-HOMEPAGE_CONFIG">
                <homepage-cards-editor v-if="settingsLoaded" v-model="settings.HOMEPAGE_CONFIG"></homepage-cards-editor>
              </div>
            </template>

            <template v-if="s.special === 'friends'">
              <div id="f-FRIENDS" class="pl-6">
              <v-row
                v-for="(friend, idx) in settings.FRIENDS"
                :key="'friend-' + friend.href"
              >
                <v-col class="py-0" cols="3">
                  <v-text-field
                    flat
                    small
                    hide-details
                    single-line
                    v-model="friend.text"
                    :label="$t('settings.name')"
                    type="text"
                  ></v-text-field>
                </v-col>
                <v-col class="py-0" cols="9">
                  <v-text-field
                    flat
                    small
                    hide-details
                    single-line
                    v-model="friend.href"
                    :label="$t('settings.link')"
                    type="text"
                    append-outer-icon="mdi-delete"
                    @click:append-outer="settings.FRIENDS.splice(idx, 1)"
                  ></v-text-field>
                </v-col>
              </v-row>
              <v-row>
                <v-col align="center">
                  <v-btn
                    color="primary"
                    @click="settings.FRIENDS.push({ text: '', href: '' })"
                    ><v-icon>mdi-plus</v-icon>{{ $t("settings.add") }}</v-btn
                  >
                </v-col>
              </v-row>
              </div>
            </template>

            <template v-if="s.special === 'reader_dicts'">
              <div id="f-READER_MYDICTS">
                <reader-dict-editor
                  v-model="settings.READER_MYDICTS"
                  :mybooks-enabled.sync="settings.READER_DICT_MYBOOKS_ENABLED"
                  :baike-enabled.sync="settings.READER_DICT_BAIKE_ENABLED"
                ></reader-dict-editor>
              </div>
            </template>

            <template v-if="s.special === 'devices'">
              <div id="f-DEVICES" class="pl-6">
              <template v-for="(device, idx) in settings.DEVICES">
                <div :key="'device-' + idx" class="device-item mb-3">
                  <v-row>
                    <v-col class="py-1" cols="3">
                      <v-text-field
                        outlined
                        dense
                        hide-details="auto"
                        v-model="device.name"
                        :label="$t('settings.device_name')"
                        type="text"
                        maxlength="64"
                      ></v-text-field>
                    </v-col>
                    <v-col class="py-1" cols="2">
                      <v-select
                        outlined
                        dense
                        hide-details="auto"
                        v-model="device.type"
                        :items="deviceTypes"
                        :label="$t('settings.device_type')"
                      ></v-select>
                    </v-col>
                    <template v-if="device.type === 'kindle'">
                      <v-col class="py-1" cols="6">
                        <v-text-field
                          outlined
                          dense
                          hide-details="auto"
                          v-model="device.mailbox"
                          :label="$t('settings.device_mailbox')"
                          type="email"
                          placeholder="user@kindle.com"
                        ></v-text-field>
                      </v-col>
                    </template>
                    <template v-else-if="device.type === 'ftp'">
                      <v-col class="py-1" cols="3">
                        <v-text-field
                          outlined
                          dense
                          hide-details="auto"
                          v-model="device.ip"
                          :label="$t('settings.device_ip')"
                          type="text"
                          placeholder="192.168.1.100"
                        ></v-text-field>
                      </v-col>
                      <v-col class="py-1" cols="2">
                        <v-text-field
                          outlined
                          dense
                          hide-details="auto"
                          v-model.number="device.port"
                          :label="$t('settings.device_port')"
                          type="number"
                          placeholder="21"
                        ></v-text-field>
                      </v-col>
                    </template>
                    <template v-else>
                      <v-col class="py-1" cols="2">
                        <v-text-field
                          outlined
                          dense
                          hide-details="auto"
                          v-model="device.ip"
                          :label="$t('settings.device_ip')"
                          type="text"
                          placeholder="192.168.1.100"
                        ></v-text-field>
                      </v-col>
                      <v-col class="py-1" cols="2">
                        <v-text-field
                          outlined
                          dense
                          hide-details="auto"
                          v-model.number="device.port"
                          :label="$t('settings.device_port')"
                          type="number"
                          placeholder="8080"
                        ></v-text-field>
                      </v-col>
                      <v-col class="py-1" cols="2">
                        <v-select
                          outlined
                          dense
                          hide-details="auto"
                          v-model="device.schema"
                          :items="deviceSchemas"
                          :label="$t('settings.device_schema')"
                        ></v-select>
                      </v-col>
                    </template>
                    <v-col class="py-1" cols="auto" align-self="center">
                      <v-btn icon small @click="settings.DEVICES.splice(idx, 1)">
                        <v-icon>mdi-delete</v-icon>
                      </v-btn>
                    </v-col>
                  </v-row>
                  <v-row v-if="device.type === 'ftp'">
                    <v-col class="py-1" cols="3"></v-col>
                    <v-col class="py-1" cols="2">
                      <v-text-field
                        outlined
                        dense
                        hide-details="auto"
                        v-model="device.ftp_username"
                        :label="$t('settings.device_ftp_username')"
                        type="text"
                        autocomplete="off"
                        :placeholder="$t('book.ftpAnonymousHint')"
                      ></v-text-field>
                    </v-col>
                    <v-col class="py-1" cols="2">
                      <v-text-field
                        outlined
                        dense
                        hide-details="auto"
                        v-model="device.ftp_password"
                        :label="$t('settings.device_ftp_password')"
                        type="password"
                        autocomplete="new-password"
                      ></v-text-field>
                    </v-col>
                    <v-col class="py-1" cols="3">
                      <v-text-field
                        outlined
                        dense
                        hide-details="auto"
                        v-model="device.ftp_path"
                        :label="$t('settings.device_ftp_path')"
                        type="text"
                        placeholder="/books"
                      ></v-text-field>
                    </v-col>
                  </v-row>
                </div>
              </template>
              <v-row>
                <v-col align="center">
                  <v-btn
                    color="primary"
                    @click="
                      settings.DEVICES.push({
                        name: $t('settings.default_reader_name'),
                        type: 'duokan',
                        ip: '',
                        port: 12121,
                        schema: 'http',
                      })
                    "
                  >
                    <v-icon>mdi-plus</v-icon>{{ $t("settings.add") }}
                  </v-btn>
                </v-col>
              </v-row>
              </div>
            </template>

            <template v-if="s.special === 'bookbarn'">
              <p>{{ $t("settings.book_barn_description") }}</p>
              <div class="pl-6">
              <div id="f-ENABLE_BOOKBARN">
              <v-checkbox
                small
                hide-details
                v-model="settings['ENABLE_BOOKBARN']"
                :key="'ENABLE_BOOKBARN'"
                :label="$t('settings.bookbarn_enable')"
              ></v-checkbox>
              </div>
              <div id="f-BOOKBARN_TOKEN">
              <v-text-field
                flat
                small
                v-model="settings['BOOKBARN_TOKEN']"
                :label="$t('settings.bookbarn_token')"
                type="text"
                :disabled="true"
              ></v-text-field>
              </div>
              <v-btn
                color="primary"
                :disabled="!settings['ENABLE_BOOKBARN'] || appliedToken"
                style="margin-bottom: 24px"
                @click="applyBookbarnToken"
              >
                <v-icon>mdi-key</v-icon>{{ $t("settings.bookbarn_apply_token") }}
              </v-btn>
              </div>
            </template>

            <template v-if="s.special === 'ai_capabilities'">
              <p>{{ $t("settings.ai_capabilities_description") }}</p>
              <div class="pl-6">
              <div id="f-AI_ENABLED">
              <v-checkbox
                small
                hide-details
                v-model="settings['AI_ENABLED']"
                :key="'AI_ENABLED'"
                :label="$t('settings.ai_enabled')"
              ></v-checkbox>
              </div>
              <div id="f-AI_DEEPSEEK_API_KEY">
              <v-text-field
                :disabled="!settings['AI_ENABLED']"
                :prepend-icon="'mdi-key'"
                v-model="settings['AI_DEEPSEEK_API_KEY']"
                :label="$t('settings.ai_api_key')"
                :placeholder="$t('settings.ai_api_key_description')"
                type="text"
                :rules="apiKeyRules"
                :maxlength="128"
              ></v-text-field>
              </div>
              <div id="f-AI_API_URL">
              <v-text-field
                :disabled="!settings['AI_ENABLED']"
                :prepend-icon="'mdi-link'"
                v-model="settings['AI_API_URL']"
                :label="$t('settings.ai_api_url')"
                :placeholder="$t('settings.ai_api_url_description')"
                type="text"
                :rules="[urlRule]"
                :maxlength="512"
              ></v-text-field>
              </div>
              <div id="f-AI_MODEL">
              <v-text-field
                :disabled="!settings['AI_ENABLED']"
                :prepend-icon="'mdi-function'"
                v-model="settings['AI_MODEL']"
                :label="$t('settings.ai_model')"
                :placeholder="$t('settings.ai_model_description')"
                type="text"
                :rules="[modelNameRule]"
                :maxlength="128"
              ></v-text-field>
              </div>
              <div id="f-AI_MCP_TOKEN">
              <v-text-field
                :prepend-icon="'mdi-key'"
                v-model="settings['AI_MCP_TOKEN']"
                :label="$t('settings.ai_mcp_token')"
                type="text"
                :append-icon="'mdi-refresh'"
                @click:append="generateMCPToken"
                readonly
              ></v-text-field>
              </div>
              <v-btn
                :disabled="!settings['AI_ENABLED'] || testingAI"
                color="green"
                class="white--text mt-3"
                @click="testAISettings"
              >
                <span v-if="testingAI" class="flex items-center gap-2">
                  <img :src="site_url + '/icons/loading.svg'" width="20" height="20" />
                  {{ $t('settings.testing') }}
                </span>
                <span v-else>{{ $t('settings.test_ai_settings') }}</span>
              </v-btn>
              <v-divider class="my-4"></v-divider>
              <h3 class="text-subtitle-1 mb-2">{{ $t("settings.mynexus_title") }}</h3>
              <p class="text-caption">{{ $t("settings.mynexus_description") }}</p>
              <div id="f-ENABLE_MYNEXUS">
              <v-checkbox
                small
                hide-details
                v-model="settings['ENABLE_MYNEXUS']"
                :key="'ENABLE_MYNEXUS'"
                :label="$t('settings.mynexus_enabled')"
                class="mb-2"
              ></v-checkbox>
              </div>
              <div id="f-MYNEXUS_URL">
              <v-text-field
                :disabled="!settings['ENABLE_MYNEXUS']"
                v-model="settings['MYNEXUS_URL']"
                prepend-icon="mdi-link"
                :label="$t('settings.mynexus_url')"
                :placeholder="$t('settings.mynexus_url_hint')"
                type="url"
              ></v-text-field>
              </div>
              <div id="f-MYNEXUS_TOKEN">
              <v-text-field
                :disabled="!settings['ENABLE_MYNEXUS']"
                v-model="settings['MYNEXUS_TOKEN']"
                prepend-icon="mdi-key"
                :label="$t('settings.mynexus_token')"
                :placeholder="$t('settings.mynexus_token_hint')"
                type="text"
                autocomplete="new-password"
              ></v-text-field>
              </div>
              <v-btn
                :disabled="!settings['ENABLE_MYNEXUS'] || testingMynexus"
                color="primary"
                class="mt-2"
                @click="testMyNexusConnection"
              >
                <span v-if="testingMynexus">{{ $t("settings.testing") }}</span>
                <span v-else>{{ $t("settings.mynexus_test") }}</span>
              </v-btn>
              <v-divider class="my-2"></v-divider>
              <div id="f-AI_ALLOW_SET_CATEGORY">
              <v-checkbox
                small
                hide-details
                :disabled="!settings['AI_ENABLED']"
                v-model="settings['AI_ALLOW_SET_CATEGORY']"
                :key="'AI_ALLOW_SET_CATEGORY'"
                :label="$t('settings.ai_allow_set_category')"
                class="mb-3"
                prepend-icon="mdi-scatter-plot-outline"
              ></v-checkbox>
              </div>
              </div>
            </template>

            <template v-if="s.special === 'socials'">
              <div class="pl-6">
              <v-combobox
                v-model="settings.SOCIALS"
                :items="sns_items"
                :label="$t('settings.select_socials')"
                hide-selected
                multiple
                small-chips
                @change="ensureSettingKeysReactive"
              >
                <template v-slot:selection="{ attrs, item, parent, selected }">
                  <v-chip
                    v-bind="attrs"
                    color="green lighten-3"
                    :input-value="selected"
                    label
                    small
                  >
                    <span class="pr-2"> {{ item.text }} </span>
                    <v-icon small @click="parent.selectItem(item)"
                      >mdi-close</v-icon
                    >
                  </v-chip>
                </template>
              </v-combobox>
              <v-row v-for="s2 in settings.SOCIALS" :key="'social-' + s2.value">
                <v-col class="py-0" cols="12" sm="2">
                  <v-subheader
                    class="px-0 pt-4"
                    :class="$vuetify.breakpoint.smAndUp ? 'float-right' : ''"
                  >
                    {{ s2.text }} (<a @click="showSNSConfig(s2)">{{
                      $t("settings.description")
                    }}</a
                    >)
                  </v-subheader>
                </v-col>
                <v-col class="py-0" cols="12" sm="3">
                  <div :id="'f-SOCIAL_AUTH_' + s2.value.toUpperCase() + '_KEY'">
                  <v-text-field
                    small
                    hide-details
                    single-line
                    v-model="
                      settings['SOCIAL_AUTH_' + s2.value.toUpperCase() + '_KEY']
                    "
                    :label="Key"
                    placeholder="Key/AppID"
                    type="text"
                  ></v-text-field>
                  </div>
                </v-col>
                <v-col class="py-0" cols="12" sm="7">
                  <div :id="'f-SOCIAL_AUTH_' + s2.value.toUpperCase() + '_SECRET'">
                  <v-text-field
                    small
                    hide-details
                    single-line
                    v-model="
                      settings[
                        'SOCIAL_AUTH_' + s2.value.toUpperCase() + '_SECRET'
                      ]
                    "
                    :label="Secert"
                    placeholder="Secret"
                    type="text"
                  ></v-text-field>
                  </div>
                </v-col>
              </v-row>
              </div>
            </template>

            <template v-if="s.special === 'trash'">
              <div class="text-center">
                <p v-html="$t('settings.trash_description')"></p>
                <div style="font-size: 1.2em; margin-bottom: 8px">
                  {{ $t("settings.trash_calibre_size") }}
                  <span style="font-weight: bold; color: #1976d2">{{
                    trashSizeTexts.trash
                  }}</span>
                </div>
                <div style="font-size: 1.2em; margin-bottom: 16px">
                  {{ $t("settings.trash_upload_size") }}
                  <span style="font-weight: bold; color: #1976d2">{{
                    trashSizeTexts.upload
                  }}</span>
                </div>
                <v-btn
                  color="red"
                  dark
                  @click="trashConfirmDialog = true"
                  style="margin-bottom: 24px"
                  :disabled="
                    trashSizes.trash + trashSizes.upload <= 10 * 1048576
                  "
                >
                  <v-icon>mdi-delete</v-icon>{{ $t("settings.trash_clear_button") }}
                </v-btn>
                <p class="mt-2">
                  <nuxt-link to="/admin/trash">{{
                    $t("settings.trash_books_goto_management")
                  }}</nuxt-link>
                </p>
              </div>
            </template>

            <template v-if="s.special === 'perf'">
              <div class="pl-6">
                <div id="f-PERFORMANCE_MODE">
                <v-checkbox
                  small
                  v-model="liteMode"
                  prepend-icon="mdi-speedometer"
                  :label="$t('settings.perf_mode_lite')"
                  :hint="$t('settings.perf_mode_hint')"
                  persistent-hint
                  @change="forceLiteGroups = false"
                ></v-checkbox>
                </div>
                <div v-if="liteMode || forceLiteGroups" style="padding-left: 32px">
                  <div v-for="key in liteGroups" :key="key" :id="'f-' + key">
                    <v-checkbox
                      small
                      dense
                      v-model="settings[key]"
                      :label="$t('settings.' + key.toLowerCase())"
                      :hint="$t('settings.' + key.toLowerCase() + '_hint')"
                      persistent-hint
                    ></v-checkbox>
                  </div>
                </div>
                <div id="f-THUMB_CACHE">
                <v-checkbox
                  small
                  v-model="thumbCache"
                  prepend-icon="mdi-image-multiple-outline"
                  :label="$t('settings.thumb_cache')"
                  :hint="$t('settings.thumb_cache_hint')"
                  persistent-hint
                  @change="forceCacheSize = false"
                ></v-checkbox>
                </div>
                <div v-if="thumbCache || forceCacheSize" style="padding-left: 32px; padding-top: 14px">
                  <div id="f-CACHE_MAX_MB">
                  <v-select
                    v-model="cacheMaxMb"
                    :items="cacheSizeItems"
                    :label="$t('settings.thumb_cache_size')"
                    dense
                    style="max-width: 240px"
                  ></v-select>
                  </div>
                </div>
              </div>
            </template>

            <template v-if="s.special === 'stamp'">
              <div class="pl-6">
              <div id="f-ENABLE_STAMP_FEATURE">
              <v-checkbox
                small
                hide-details
                v-model="settings['ENABLE_STAMP_FEATURE']"
                :label="$t('settings.enable_stamp_feature')"
                prepend-icon="mdi-picture-in-picture-bottom-right-outline"
              ></v-checkbox>
              </div>
              <div v-if="settings['ENABLE_STAMP_FEATURE']" style="margin-top: 16px; margin-left: 16px;">
                <v-row align="top">
                  <v-col cols="12" sm="6">
                    <p class="mb-2">{{ $t('settings.stamp_image_label') }}</p>
                    <div style="position: relative; width: 200px; height: 200px;">
                      <v-img
                        :src="stampPreviewUrl"
                        width="200"
                        height="200"
                        style="border: 1px solid #ddd;"
                        contain
                      >
                        <template v-slot:placeholder>
                          <v-row
                            class="fill-height ma-0"
                            align="center"
                            justify="center"
                          >
                            <v-icon size="80" color="grey lighten-2">mdi-image</v-icon>
                          </v-row>
                        </template>
                      </v-img>
                      <v-btn
                        absolute
                        bottom
                        right
                        fab
                        small
                        color="primary"
                        @click="openStampFileDialog"
                        style="margin: 8px;"
                      >
                        <v-icon>mdi-upload</v-icon>
                      </v-btn>
                      <input
                        ref="stampFileInput"
                        type="file"
                        accept=".png"
                        style="display: none"
                        @change="uploadStampImage"
                      />
                    </div>
                    <p class="text-caption mt-2">
                      {{ $t('settings.stamp_image_hint') }}
                    </p>
                  </v-col>
                </v-row>
              </div>
              </div>
            </template>

            <template v-if="s.special === 'ssl'">
              <div class="pl-6">
              <ssl-manager />
              </div>
            </template>
          </v-card-text>
        </v-card>
      </div>
    </template>

    <v-card
      class="my-2 elevation-4"
      v-if="!searchQuery && activeGroup === 'ops' && thanksToNames.length > 0"
    >
      <v-card-title @click="thanksToShow = !thanksToShow">
        <v-btn @click.once="thanksToShow = !thanksToShow" icon>
          <v-icon>{{
            thanksToShow ? "mdi-chevron-down" : "mdi-chevron-up"
          }}</v-icon>
        </v-btn>
        <v-icon color="red" small class="thanks-heart-icon mr-1">mdi-heart</v-icon>
        {{ $t("settings.thanksTo") }}
        <v-icon color="red" small class="thanks-heart-icon ml-1">mdi-heart</v-icon>
      </v-card-title>
      <v-expand-transition>
        <v-card-text v-show="thanksToShow" style="padding: 0">
          <div style="padding: 0 16px 16px">
            <div class="thanks-to-section">
              <p class="thanks-to-desc">{{ $t("settings.thanksToDesc") }}</p>
              <div class="thanks-to-names">
                <span v-for="(name, idx) in thanksToNames" :key="idx" class="thanks-to-chip">{{ name }}</span>
              </div>
            </div>
          </div>
        </v-card-text>
      </v-expand-transition>
    </v-card>

    <AppDialog
      v-model="trashConfirmDialog"
      type="confirm"
      :title="$t('settings.trash_clear_confirm_title')"
      color="deep-orange"
      confirm-dark
      max-width="400"
      :confirm-text="$t('settings.trash_clear_confirm_button')"
      @confirm="clearTrash"
    >
      {{ $t("settings.trash_clear_confirm_message") }}
    </AppDialog>

    <AppDialog
      v-model="restartConfirmDialog"
      type="confirm"
      :title="$t('settings.restart_confirm_title')"
      color="orange darken-4"
      confirm-dark
      max-width="400"
      :confirm-text="$t('settings.restart_confirm_button')"
      @confirm="restartServer"
    >
      {{ $t("settings.restart_confirm_message") }}
    </AppDialog>

    <AppDialog
      v-model="unsavedLeaveDialog"
      type="confirm"
      :title="$t('settings.unsaved_leave_title')"
      color="orange darken-4"
      confirm-dark
      max-width="420"
      :confirm-text="$t('settings.unsaved_leave_confirm_button')"
      @confirm="confirmLeave"
      @dismiss="cancelLeave"
    >
      {{ $t("settings.unsaved_leave_confirm", { n: dirtyCount }) }}
    </AppDialog>

    <reading-range-dialog
      ref="defaultReadRangeDialog"
      :title="$t('settings.default_read_range_dialog_title')"
      :saving="savingDefaultReadRange"
      @save="saveDefaultReadRange"
    ></reading-range-dialog>

    <div class="settings-savebar">
      <button
        type="button"
        class="settings-savebar-status"
        :class="{ 'is-clickable': dirtyCount > 0 }"
        :tabindex="dirtyCount > 0 ? 0 : -1"
        :aria-disabled="dirtyCount > 0 ? null : 'true'"
        :title="dirtyCount > 0 ? $t('settings.unsaved_jump_tip', { n: dirtyCount }) : null"
        :aria-describedby="dirtyCount > 0 ? 'settings-dirty-jump-tip' : null"
        @click="jumpToNextDirty"
      >
        <v-icon small :color="dirtyCount > 0 ? 'orange' : 'green'" class="mr-2">
          {{ dirtyCount > 0 ? "mdi-pencil-box-outline" : "mdi-check-circle" }}
        </v-icon>
        <span
          class="text-caption"
          :class="dirtyCount > 0 ? 'orange--text font-weight-bold' : 'grey--text'"
        >
          {{
            dirtyCount > 0
              ? $t("settings.savebar_unsaved", { n: dirtyCount })
              : $t("settings.all_saved")
          }}
        </span>
      </button>
      <span class="text-caption grey--text ml-4 hidden-sm-and-down">{{ $t("settings.save_hints") }}</span>
      <div class="settings-savebar-actions">
        <v-btn
          color="primary"
          :disabled="dirtyCount === 0"
          @click="saveSettings"
        >
          <v-icon left>mdi-content-save</v-icon>{{ $t("settings.save") }}
        </v-btn>
        <v-btn color="orange darken-4" dark @click="restartConfirmDialog = true" class="ml-8">
          <v-icon left>mdi-restart</v-icon>{{ $t("settings.restart_server") }}
        </v-btn>
      </div>
    </div>
  </div>
</template>

<script>
import SSLManager from "~/components/SSLManager.vue";
import ReadingRangeDialog from "~/components/ReadingRangeDialog.vue";
import BookNavEditor, { createCategory } from "~/components/BookNavEditor.vue";
import ReaderDictEditor from "~/components/ReaderDictEditor.vue";
import HomepageCardsEditor from "~/components/HomepageCardsEditor.vue";
import { normalizeHomepageConfig } from "~/utils/homepage";
import { languageOptions } from "~/utils/languageCodes";
import { isHexColor, DEFAULT_ACCENT } from "~/utils/appearance";

const LITE_GROUPS = [
  "LITE_GROUP_LISTING",
  "LITE_GROUP_RECOMMEND",
  "LITE_GROUP_FILES",
  "LITE_GROUP_BACKGROUND",
  "LITE_GROUP_RESOURCES",
];

// 特殊块（动态列表/子组件）不在 groups.fields 里，搜索索引需在此手动注册
const SPECIAL_BLOCKS = [
  { key: "HOMEPAGE_CONFIG", label: "settings.sec_site_home_cards", icon: "mdi-view-grid-plus-outline", gid: "site", sid: "site-home-cards", al: ["首页卡片", "自定义卡片", "homepage cards", "首頁卡片"] },
  { key: "FRIENDS", label: "settings.friend_links", icon: "mdi-link-variant", gid: "site", sid: "site-friends" },
  { key: "READER_DICT_MYBOOKS_ENABLED", label: "settings.reader_dict_mybooks", icon: "mdi-book-alphabet", gid: "reading", sid: "reader-dict" },
  { key: "READER_DICT_BAIKE_ENABLED", label: "settings.reader_dict_baike", icon: "mdi-book-alphabet", gid: "reading", sid: "reader-dict" },
  { key: "READER_MYDICTS", label: "settings.sec_reader_dict", icon: "mdi-book-alphabet", gid: "reading", sid: "reader-dict", al: ["翻译"] },
  { key: "ENABLE_STAMP_FEATURE", label: "settings.enable_stamp_feature", icon: "mdi-picture-in-picture-bottom-right-outline", gid: "reading", sid: "reader-extended" },
  { key: "SOCIALS", label: "settings.select_socials", icon: "mdi-at", gid: "users", sid: "users-social", al: ["qq", "微信", "微博", "github", "oauth"] },
  { key: "DEVICES", label: "settings.device_mgt", icon: "mdi-tablet-cellphone", gid: "push", sid: "push-devices", al: ["kindle", "文石", "掌阅", "汉王", "当当", "koreader", "duokan", "ireader", "boox", "ftp"] },
  { key: "ENABLE_BOOKBARN", label: "settings.bookbarn_enable", icon: "mdi-key", gid: "services", sid: "svc-bookbarn" },
  { key: "BOOKBARN_TOKEN", label: "settings.bookbarn_token", icon: "mdi-key", gid: "services", sid: "svc-bookbarn" },
  { key: "AI_ENABLED", label: "settings.ai_enabled", icon: "mdi-scatter-plot-outline", gid: "services", sid: "svc-ai" },
  { key: "AI_DEEPSEEK_API_KEY", label: "settings.ai_api_key", icon: "mdi-key", gid: "services", sid: "svc-ai" },
  { key: "AI_API_URL", label: "settings.ai_api_url", icon: "mdi-link", gid: "services", sid: "svc-ai" },
  { key: "AI_MODEL", label: "settings.ai_model", icon: "mdi-function", gid: "services", sid: "svc-ai" },
  { key: "AI_MCP_TOKEN", label: "settings.ai_mcp_token", icon: "mdi-key", gid: "services", sid: "svc-ai" },
  { key: "ENABLE_MYNEXUS", label: "settings.mynexus_enabled", icon: "mdi-book-search", gid: "services", sid: "svc-ai", al: ["mynexus", "nexus"] },
  { key: "MYNEXUS_URL", label: "settings.mynexus_url", icon: "mdi-link", gid: "services", sid: "svc-ai", al: ["mynexus", "nexus"] },
  { key: "MYNEXUS_TOKEN", label: "settings.mynexus_token", icon: "mdi-key", gid: "services", sid: "svc-ai", al: ["mynexus", "nexus"] },
  { key: "AI_ALLOW_SET_CATEGORY", label: "settings.ai_allow_set_category", icon: "mdi-scatter-plot-outline", gid: "services", sid: "svc-ai" },
  { key: "SSL", label: "settings.ssl_certificate_management", icon: "mdi-lock", gid: "protocols", sid: "proto-net", al: ["证书", "https"] },
  { key: "PERFORMANCE_MODE", label: "settings.perf_mode_lite", icon: "mdi-speedometer", gid: "ops", sid: "ops-perf", al: ["性能", "速度"] },
  { key: "LITE_GROUP_LISTING", label: "settings.lite_group_listing", icon: "mdi-speedometer", gid: "ops", sid: "ops-perf" },
  { key: "LITE_GROUP_RECOMMEND", label: "settings.lite_group_recommend", icon: "mdi-speedometer", gid: "ops", sid: "ops-perf" },
  { key: "LITE_GROUP_FILES", label: "settings.lite_group_files", icon: "mdi-speedometer", gid: "ops", sid: "ops-perf" },
  { key: "LITE_GROUP_BACKGROUND", label: "settings.lite_group_background", icon: "mdi-speedometer", gid: "ops", sid: "ops-perf" },
  { key: "LITE_GROUP_RESOURCES", label: "settings.lite_group_resources", icon: "mdi-speedometer", gid: "ops", sid: "ops-perf" },
  { key: "THUMB_CACHE", label: "settings.thumb_cache", icon: "mdi-image-multiple-outline", gid: "ops", sid: "ops-perf" },
  { key: "CACHE_MAX_MB", label: "settings.thumb_cache_size", icon: "mdi-image-multiple-outline", gid: "ops", sid: "ops-perf" },
  { key: "TRASH", label: "settings.trash_clear_button", icon: "mdi-delete", gid: "ops", sid: "ops-trash", al: ["回收站", "磁盘", "清理"] },
];

// 值型字段（可安全用空串补默认值的那些；数组/特殊块类型不在此列，缺 key 时保持原样）
const SETTING_TEXT_TYPES = ["text", "textarea", "select", "number"];

// READER_MYDICTS 元素上的 showToken 只是显隐 token 的视图状态，
// 点眼睛图标不应算作未保存修改，比较前先剥掉
function settingsValueForCompare(key, value) {
  if (key !== "READER_MYDICTS" || !Array.isArray(value)) return value;
  return value.map((d) => {
    const e = { ...d };
    delete e.showToken;
    return e;
  });
}

// 由子组件统一渲染、没有各自独立 DOM 锚点的 key，跳转时落到同一个块
const ANCHOR_ALIASES = {
  READER_DICT_MYBOOKS_ENABLED: "READER_MYDICTS",
  READER_DICT_BAIKE_ENABLED: "READER_MYDICTS",
};

// 激活分组下色条 + 组标题竖条：默认跟随站点主色 accent（外观菜单里的「主色」），
// 换主色即时跟随
// （uiverse 分段 pill 的形态借鉴，样式为本仓 clean-room 实现）

// 用户口语搜索词 → 设置项 key。分简体(zh)/繁体(zh-TW)/英文(en)三层，下面 ALIAS_LOOKUP
// 会把三层并成一张查找表，因此与界面语言无关：简中界面能搜 "guest"，英文界面能搜「快取」，
// 繁中界面也能搜「缓存」。维护约定：
//   · 拉丁词条一律小写（查询串已 toLowerCase），只按整词命中；
//   · 中文词条会作为子串参与组合词匹配（「访客权限」⊃「访客」、「推送设备」⊃「推送」+「设备」），
//     所以组合词不必逐条登记；
//   · 值只能写本页真实存在的设置项 key（见 groups / SPECIAL_BLOCKS），写错等于白写。
const SEARCH_ALIASES = {
  zh: {
    // 站点与外观 · 站点标识
    站名: ["site_title"], 站点名称: ["site_title"], 网站标题: ["site_title"], 名称: ["site_title", "DEVICES"], 标题: ["site_title", "push_title"],
    图标: ["site_icon"], 网站图标: ["site_icon"], favicon: ["site_icon"], logo: ["site_icon"], 徽标: ["site_icon"],
    默认链接: ["SITE_URL"], 访问链接: ["SITE_URL"], 分享链接: ["SITE_URL", "ENABLE_SHARE_LINK"], 分享地址: ["SITE_URL"], 对外地址: ["SITE_URL"], 外网: ["SITE_URL"], 内网: ["SITE_URL"], 二维码: ["SITE_URL"],
    公告: ["HEADER"], 告示: ["HEADER"], 通知: ["HEADER", "SEND_MAIL_FOR_NEW_BOOKS"],
    脚注: ["FOOTER"], 页脚: ["FOOTER"], 页尾: ["FOOTER"], 底部: ["FOOTER"], 版权: ["FOOTER"],
    水印: ["FOOTER_WATERMARK"],
    语言: ["site_language", "DEFAULT_LANGUAGE"], 中文: ["site_language"], english: ["site_language"], 繁体: ["site_language"], 简体: ["site_language"], 简繁: ["site_language"], 多语言: ["site_language", "DEFAULT_LANGUAGE"], 切换: ["site_language"], 默认语言: ["DEFAULT_LANGUAGE"],
    时区: ["site_timezone"], 系统时区: ["site_timezone"], 时区设置: ["site_timezone"], 东八区: ["site_timezone"], 格林威治: ["site_timezone"], 跨天: ["site_timezone"], 统计口径: ["site_timezone"], utc: ["site_timezone"], timezone: ["site_timezone"],
    主页: ["INDEX_PAGE_TYPE", "MAIN_PAGE_RANDOM_COUNT", "MAIN_PAGE_RECENT_COUNT"], 默认页: ["INDEX_PAGE_TYPE"], 首页类型: ["INDEX_PAGE_TYPE"],
    首页卡片: ["HOMEPAGE_CONFIG"], 自定义卡片: ["HOMEPAGE_CONFIG"], 卡片: ["HOMEPAGE_CONFIG"], 作者卡片: ["HOMEPAGE_CONFIG"], 标签卡片: ["HOMEPAGE_CONFIG"], 丛书卡片: ["HOMEPAGE_CONFIG"], 语言卡片: ["HOMEPAGE_CONFIG"], 评分卡片: ["HOMEPAGE_CONFIG"],
    项目链接: ["HIDE_PROJECT_LINKS"], 隐藏链接: ["HIDE_PROJECT_LINKS"], 开源链接: ["HIDE_PROJECT_LINKS"],
    友情链接: ["FRIENDS"], 友链: ["FRIENDS"], 链接: ["FRIENDS", "HIDE_PROJECT_LINKS", "douban_baseurl", "AI_API_URL", "static_host", "SITE_URL"],
    网址: ["douban_baseurl", "AI_API_URL", "static_host", "SITE_URL"], 地址: ["douban_baseurl", "AI_API_URL", "static_host", "smtp_server", "SITE_URL"],
    // 站点与外观 · 首页与列表
    随机: ["MAIN_PAGE_RANDOM_COUNT"], 推荐: ["RECOMMEND_ENABLE", "RECOMMEND_USE_CROWD", "ENABLE_BOOK_RECOMMEND_TO_OTHERS", "MAIN_PAGE_RANDOM_COUNT"], 智能: ["RECOMMEND_ENABLE"],
    协同: ["RECOMMEND_USE_CROWD"], 协同过滤: ["RECOMMEND_USE_CROWD"], 参考他人: ["RECOMMEND_USE_CROWD"],
    新书: ["MAIN_PAGE_RECENT_COUNT", "SEND_MAIL_FOR_NEW_BOOKS"], 最新: ["MAIN_PAGE_RECENT_COUNT"], 最近更新: ["MAIN_PAGE_RECENT_COUNT"],
    分页: ["DEFAULT_PAGE_SIZE"], 每页: ["DEFAULT_PAGE_SIZE"], 每页数量: ["DEFAULT_PAGE_SIZE"],
    侧边栏: ["SIDEBAR_ITEMS"], 侧栏: ["SIDEBAR_ITEMS"], 菜单: ["SIDEBAR_ITEMS"], 导航栏: ["SIDEBAR_ITEMS"], 侧边导航: ["SIDEBAR_ITEMS"],
    首页显示: ["HOMEPAGE_CONFIG"],
    统计: ["HOMEPAGE_CONFIG", "ALLOW_USER_DISABLE_STATISTIC"], banner: ["HOMEPAGE_CONFIG"], 阅读统计: ["HOMEPAGE_CONFIG"],
    在读: ["HOMEPAGE_CONFIG"], 正在阅读: ["HOMEPAGE_CONFIG"],
    书单: ["HOMEPAGE_CONFIG", "BOOK_NAV"], 书单推荐: ["HOMEPAGE_CONFIG"],
    // 首页动效：用户通常按「动效/动画/减少动效」这类词找它（关闭后进场动画、
    // 封面淡入、书单封面自动滚动一并停用），而标签只有「首页动效」，
    // 不含这几个词，故显式登记
    动效: ["ENABLE_HOME_MOTION"], 减少动效: ["ENABLE_HOME_MOTION"], 减弱动态效果: ["ENABLE_HOME_MOTION"],
    动画: ["ENABLE_HOME_MOTION"], 轮播: ["ENABLE_HOME_MOTION"], 自动滚动: ["ENABLE_HOME_MOTION"],
    进场动画: ["ENABLE_HOME_MOTION"], 淡入: ["ENABLE_HOME_MOTION"], 书单滚动: ["ENABLE_HOME_MOTION"], 封面滚动: ["ENABLE_HOME_MOTION"],
    推荐给他人: ["ENABLE_BOOK_RECOMMEND_TO_OTHERS", "HOMEPAGE_CONFIG"], 他人推荐: ["ENABLE_BOOK_RECOMMEND_TO_OTHERS", "HOMEPAGE_CONFIG"], "留言": ["ENABLE_USER_MEMOS"],
    实体书: ["ENABLE_PHYSICAL_BOOKS", "ENABLE_BOOKS_TYPE_CONVERT_DIRECT"], 纸书: ["ENABLE_PHYSICAL_BOOKS"], 纸质书: ["ENABLE_PHYSICAL_BOOKS"], 书架: ["ENABLE_PHYSICAL_BOOKS"], 印刷: ["ENABLE_PHYSICAL_BOOKS"],
    类型转换: ["ENABLE_BOOKS_TYPE_CONVERT_DIRECT"], 直接转换: ["ENABLE_BOOKS_TYPE_CONVERT_DIRECT"],
    // 站点与外观 · 书籍分类
    分类: ["BOOK_NAV", "IMPORT_CATEGORY_WITH_FOLDER", "ENABLE_FOLDER_BROWSE", "AI_ALLOW_SET_CATEGORY"], 导航: ["BOOK_NAV"], 标签: ["BOOK_NAV"],
    分类导航: ["BOOK_NAV"], 分类管理: ["BOOK_NAV"], 分类树: ["BOOK_NAV"],
    // 阅读与内容 · 阅读器与同步
    阅读器: ["EPUB_VIEWER", "DEVICES"], epub: ["EPUB_VIEWER"], epubjs: ["EPUB_VIEWER"], myreader: ["EPUB_VIEWER", "ENABLE_DATA_SYNC"],
    阅读引擎: ["EPUB_VIEWER"],
    同步: ["ENABLE_DATA_SYNC", "ENABLE_WEBDAV_SERVICE", "WEBDAV_SYNC_FOLDER"], 进度: ["ENABLE_DATA_SYNC"], 阅读数据: ["ENABLE_DATA_SYNC"], 跨设备: ["ENABLE_DATA_SYNC", "DEVICES"],
    封面: ["USE_DYNAMIC_COVER", "ENABLE_STAMP_FEATURE", "THUMB_CACHE"], 动态封面: ["USE_DYNAMIC_COVER"], 书封: ["USE_DYNAMIC_COVER"],
    作者: ["ENABLE_AUTHOR_INFO"], 简介: ["ENABLE_AUTHOR_INFO"], 头像: ["ENABLE_AUTHOR_INFO"], 作者信息: ["ENABLE_AUTHOR_INFO"],
    隐私: ["ALLOW_USER_DISABLE_STATISTIC"], 采集: ["ALLOW_USER_DISABLE_STATISTIC"],
    笔记: ["ENABLE_SHARED_NOTES"], 划线: ["ENABLE_SHARED_NOTES"], 标注: ["ENABLE_SHARED_NOTES"], 分享笔记: ["ENABLE_SHARED_NOTES"],
    // 阅读与内容 · 词典
    词典: ["READER_MYDICTS", "READER_DICT_MYBOOKS_ENABLED", "READER_DICT_BAIKE_ENABLED"],
    字典: ["READER_MYDICTS", "READER_DICT_MYBOOKS_ENABLED", "READER_DICT_BAIKE_ENABLED"],
    翻译: ["READER_MYDICTS", "READER_DICT_MYBOOKS_ENABLED", "READER_DICT_BAIKE_ENABLED"],
    生词: ["READER_MYDICTS"], 划词: ["READER_MYDICTS"], 查词: ["READER_MYDICTS"], 取词: ["READER_MYDICTS"],
    百科: ["READER_DICT_BAIKE_ENABLED"], 百度百科: ["READER_DICT_BAIKE_ENABLED"],
    // 阅读与内容 · 书评与互动
    评论: ["ENABLE_BOOK_REVIEW", "REVIEW_REQUIRES_APPROVAL", "ENABLE_BOOK_RECOMMEND_TO_OTHERS"], 评分: ["ENABLE_BOOK_REVIEW"], 书评: ["ENABLE_BOOK_REVIEW"], 打分: ["ENABLE_BOOK_REVIEW"], 星级: ["ENABLE_BOOK_REVIEW"],
    审核: ["REVIEW_REQUIRES_APPROVAL", "ENABLE_AUTO_NEW_USER_APPROVAL"], 先审后发: ["REVIEW_REQUIRES_APPROVAL"],
    // 阅读与内容 · 扩展功能
    文件夹: ["ENABLE_FOLDER_BROWSE"], 层级: ["ENABLE_FOLDER_BROWSE"], 多级目录: ["ENABLE_FOLDER_BROWSE"], 多级分类: ["ENABLE_FOLDER_BROWSE"],
    图章: ["ENABLE_STAMP_FEATURE"], 盖章: ["ENABLE_STAMP_FEATURE"], 印章: ["ENABLE_STAMP_FEATURE"],
    // 用户与访问 · 访问权限
    访客: ["ALLOW_GUEST_READ", "ALLOW_GUEST_DOWNLOAD", "ALLOW_GUEST_UPLOAD", "ALLOW_GUEST_PUSH", "ENABLE_SHARE_LINK"],
    游客: ["ALLOW_GUEST_READ", "ALLOW_GUEST_DOWNLOAD", "ALLOW_GUEST_UPLOAD", "ALLOW_GUEST_PUSH", "ENABLE_SHARE_LINK"],
    匿名: ["ALLOW_GUEST_READ", "ALLOW_GUEST_DOWNLOAD"], 免登录: ["ALLOW_GUEST_READ", "ALLOW_GUEST_DOWNLOAD", "ALLOW_GUEST_UPLOAD", "ALLOW_GUEST_PUSH", "ENABLE_SHARE_LINK"], 未登录: ["ALLOW_GUEST_READ", "ALLOW_GUEST_DOWNLOAD"],
    在线阅读: ["ALLOW_GUEST_READ"], 试读: ["ALLOW_GUEST_READ"],
    分享: ["ENABLE_SHARE_LINK", "ENABLE_SHARED_NOTES"], 直链: ["ENABLE_SHARE_LINK"], 链接阅读: ["ENABLE_SHARE_LINK"], 分享阅读: ["ENABLE_SHARE_LINK"],
    // 用户与访问 · 注册与邀请
    邀请: ["INVITE_MODE", "INVITE_CODE"], 私人: ["INVITE_MODE"], 访问码: ["INVITE_MODE", "INVITE_CODE"], 注册码: ["INVITE_CODE", "INVITE_MODE"], 邀请码: ["INVITE_CODE", "INVITE_MODE"], 封闭: ["INVITE_MODE"],
    密码锁: ["INVITE_MODE", "INVITE_CODE"], 口令: ["INVITE_CODE"],
    提示语: ["INVITE_MESSAGE"], 欢迎语: ["INVITE_MESSAGE"], 邀请文案: ["INVITE_MESSAGE"],
    注册: ["ALLOW_REGISTER", "SIGNUP_MAIL_TITLE", "ENABLE_AUTO_NEW_USER_APPROVAL"], 开放注册: ["ALLOW_REGISTER"], 邮箱注册: ["ALLOW_REGISTER"], 自助注册: ["ALLOW_REGISTER"],
    激活: ["SIGNUP_MAIL_TITLE", "SIGNUP_MAIL_CONTENT"], 激活邮件: ["SIGNUP_MAIL_TITLE", "SIGNUP_MAIL_CONTENT"],
    重置: ["RESET_MAIL_TITLE", "RESET_MAIL_CONTENT"], 找回: ["RESET_MAIL_TITLE", "RESET_MAIL_CONTENT"], 重置密码: ["RESET_MAIL_TITLE", "RESET_MAIL_CONTENT"], 忘记密码: ["RESET_MAIL_TITLE", "RESET_MAIL_CONTENT"],
    主题: ["push_title", "RESET_MAIL_TITLE", "SIGNUP_MAIL_TITLE"], 正文: ["push_content", "RESET_MAIL_CONTENT", "SIGNUP_MAIL_CONTENT"], 内容: ["push_content", "RESET_MAIL_CONTENT", "SIGNUP_MAIL_CONTENT", "INVITE_MESSAGE"],
    // 用户与访问 · 默认权限与配额
    审批: ["ENABLE_AUTO_NEW_USER_APPROVAL", "REVIEW_REQUIRES_APPROVAL"], 自动审批: ["ENABLE_AUTO_NEW_USER_APPROVAL"],
    新用户: ["ALLOW_NEW_USER_MANAGE_BOOK", "ALLOW_NEW_USER_PUSH_BOOK", "ENABLE_AUTO_NEW_USER_APPROVAL", "DEFAULT_READ_RANGE"],
    权限: ["ALLOW_NEW_USER_MANAGE_BOOK", "ALLOW_NEW_USER_PUSH_BOOK", "ALLOW_READ_RANGE_SETTING"], 默认权限: ["ALLOW_NEW_USER_MANAGE_BOOK", "ALLOW_NEW_USER_PUSH_BOOK"], 管理权限: ["ALLOW_NEW_USER_MANAGE_BOOK"],
    白名单: ["ALLOW_READ_RANGE_SETTING", "DEFAULT_READ_RANGE"], 黑名单: ["ALLOW_READ_RANGE_SETTING", "DEFAULT_READ_RANGE"],
    可见: ["ALLOW_READ_RANGE_SETTING", "DEFAULT_READ_RANGE"], 屏蔽: ["ALLOW_READ_RANGE_SETTING", "DEFAULT_READ_RANGE"], 不可见: ["ALLOW_READ_RANGE_SETTING", "DEFAULT_READ_RANGE"],
    范围: ["ALLOW_READ_RANGE_SETTING", "DEFAULT_READ_RANGE"], 阅读范围: ["ALLOW_READ_RANGE_SETTING", "DEFAULT_READ_RANGE"],
    配额: ["ENABLE_DOWNLOAD_QUOTA", "GLOBAL_DOWNLOAD_QUOTA"], 下载: ["ENABLE_DOWNLOAD_QUOTA", "GLOBAL_DOWNLOAD_QUOTA", "ALLOW_GUEST_DOWNLOAD"], 每日: ["ENABLE_DOWNLOAD_QUOTA", "GLOBAL_DOWNLOAD_QUOTA"],
    下载限制: ["ENABLE_DOWNLOAD_QUOTA", "GLOBAL_DOWNLOAD_QUOTA"], 每日下载: ["ENABLE_DOWNLOAD_QUOTA", "GLOBAL_DOWNLOAD_QUOTA"],
    // 用户与访问 · 社交登录
    登录: ["SOCIALS", "ALLOW_REGISTER", "INVITE_MODE"], 第三方: ["SOCIALS"], 社交: ["SOCIALS"], oauth: ["SOCIALS"], qq: ["SOCIALS"], 微信: ["SOCIALS"], 微博: ["SOCIALS"], github: ["SOCIALS"],
    单点登录: ["SOCIALS"], 第三方登录: ["SOCIALS"],
    // 导入与存储 · 上传
    扫描: ["scan_upload_path", "PDF_TILE_WITH_FILE_NAME"], 批量: ["scan_upload_path", "BATCH_ADD_IN_FORCE"], 扫描目录: ["scan_upload_path"], 导入目录: ["scan_upload_path"],
    上传: ["MAX_UPLOAD_SIZE", "CHUNK_UPLOAD_SIZE", "scan_upload_path", "ALLOW_GUEST_UPLOAD", "KEEP_UPLOAD_SOURCE_FILE"],
    大小: ["MAX_UPLOAD_SIZE", "CACHE_MAX_MB"], 文件大小: ["MAX_UPLOAD_SIZE"], 上传限制: ["MAX_UPLOAD_SIZE", "CHUNK_UPLOAD_SIZE"],
    上限: ["MAX_UPLOAD_SIZE", "CHUNK_UPLOAD_SIZE", "ENABLE_DOWNLOAD_QUOTA", "GLOBAL_DOWNLOAD_QUOTA", "CACHE_MAX_MB"],
    分片: ["CHUNK_UPLOAD_SIZE"], 大文件: ["CHUNK_UPLOAD_SIZE"], 续传: ["CHUNK_UPLOAD_SIZE"],
    元数据: ["auto_fill_meta", "META_SELECTED_SOURCES", "DEFAULT_LANGUAGE"], 书籍信息: ["auto_fill_meta", "META_SELECTED_SOURCES"], 信息源: ["META_SELECTED_SOURCES", "douban_baseurl"],
    源文件: ["KEEP_UPLOAD_SOURCE_FILE", "REMOVE_IMPORTED_FILE"], 保留: ["KEEP_UPLOAD_SOURCE_FILE"], 临时文件: ["KEEP_UPLOAD_SOURCE_FILE", "REMOVE_IMPORTED_FILE"], 暂存文件: ["KEEP_UPLOAD_SOURCE_FILE"],
    删除源文件: ["REMOVE_IMPORTED_FILE"], 导入后删除: ["REMOVE_IMPORTED_FILE"],
    // 导入与存储 · 导入规则
    pdf: ["PDF_TILE_WITH_FILE_NAME"], 文件名: ["PDF_TILE_WITH_FILE_NAME", "BOOK_NAMES_FORMAT"], 书名: ["PDF_TILE_WITH_FILE_NAME"],
    txt: ["ENABLE_TXT_TO_TXTZ_PLUGIN"], txtz: ["ENABLE_TXT_TO_TXTZ_PLUGIN"], 转换: ["ENABLE_TXT_TO_TXTZ_PLUGIN", "convert_timeout", "ENABLE_BOOKS_TYPE_CONVERT_DIRECT"],
    服务端: ["ENABLE_SERVER_FILE_IMPORT"], 目录浏览: ["ENABLE_SERVER_FILE_IMPORT"], 服务器导入: ["ENABLE_SERVER_FILE_IMPORT"],
    isbn: ["BATCH_ADD_IN_FORCE"], 强制: ["BATCH_ADD_IN_FORCE"], 无效: ["BATCH_ADD_IN_FORCE"], 强制添加: ["BATCH_ADD_IN_FORCE"],
    一级目录: ["IMPORT_CATEGORY_WITH_FOLDER"], 目录分类: ["IMPORT_CATEGORY_WITH_FOLDER"], 自定义类别: ["IMPORT_CATEGORY_WITH_FOLDER"],
    限流: ["auto_fill_pause_on_throttle", "ENABLE_DOWNLOAD_QUOTA"], 暂停: ["auto_fill_pause_on_throttle"], 自动暂停: ["auto_fill_pause_on_throttle"], 节流: ["auto_fill_pause_on_throttle"],
    重复: ["UPLOAD_IGNORE_TITLE_CHECKING"], 同书: ["UPLOAD_IGNORE_TITLE_CHECKING"], 查重: ["UPLOAD_IGNORE_TITLE_CHECKING"], 同名书: ["UPLOAD_IGNORE_TITLE_CHECKING"],
    // 导入与存储 · 自动导入 / 存储布局
    监控: ["IMPORT_BY_INOTIFY", "UPDATE_CATEGORY_WITH_FOLDER_RENAME"], 自动导入: ["IMPORT_BY_INOTIFY"], inotify: ["IMPORT_BY_INOTIFY"], 监视: ["IMPORT_BY_INOTIFY"], 实时导入: ["IMPORT_BY_INOTIFY"],
    重命名: ["UPDATE_CATEGORY_WITH_FOLDER_RENAME"], 目录改名: ["UPDATE_CATEGORY_WITH_FOLDER_RENAME"],
    拼音: ["BOOK_NAMES_FORMAT"], utf8: ["BOOK_NAMES_FORMAT"], 存储: ["BOOK_NAMES_FORMAT", "TRASH"], 存储布局: ["BOOK_NAMES_FORMAT"], 编码: ["BOOK_NAMES_FORMAT"], 文件名模式: ["BOOK_NAMES_FORMAT"],
    // 推送与邮件 · 邮件服务
    smtp: ["smtp_server", "smtp_username", "smtp_password", "smtp_encryption"], 服务器: ["smtp_server"], 账号: ["smtp_username"], 用户名: ["smtp_username"], 发件: ["smtp_server", "smtp_username"],
    授权码: ["smtp_password"], 邮件密码: ["smtp_password"], 加密: ["smtp_encryption"], ssl: ["smtp_encryption", "SSL"], tls: ["smtp_encryption"], 端口: ["smtp_server", "smtp_encryption"],
    邮件: ["smtp_server", "smtp_username", "smtp_password", "smtp_encryption", "push_title", "push_content", "SEND_MAIL_FOR_NEW_BOOKS", "SIGNUP_MAIL_TITLE", "SIGNUP_MAIL_CONTENT", "RESET_MAIL_TITLE", "RESET_MAIL_CONTENT"],
    邮箱: ["smtp_server", "smtp_username", "smtp_password", "smtp_encryption", "push_title", "SEND_MAIL_FOR_NEW_BOOKS"],
    推送: ["DEVICES", "push_title", "push_content", "SEND_MAIL_FOR_NEW_BOOKS", "ALLOW_GUEST_PUSH", "ALLOW_NEW_USER_PUSH_BOOK", "smtp_server"],
    kindle: ["DEVICES", "push_title", "smtp_server"], 邮件主题: ["push_title"], 邮件正文: ["push_content"],
    提醒: ["SEND_MAIL_FOR_NEW_BOOKS"], 邮件提醒: ["SEND_MAIL_FOR_NEW_BOOKS"], 通知邮件: ["SEND_MAIL_FOR_NEW_BOOKS", "push_title"],
    // 推送与邮件 · 推送设备
    设备: ["DEVICES"], 推送设备: ["DEVICES"], 阅读设备: ["DEVICES"], 设备管理: ["DEVICES"],
    文石: ["DEVICES"], 掌阅: ["DEVICES"], 汉王: ["DEVICES"], 当当: ["DEVICES"], koreader: ["DEVICES"], duokan: ["DEVICES"], ireader: ["DEVICES"], boox: ["DEVICES"], purelibro: ["DEVICES"], ftp: ["DEVICES"],
    // 外部服务 · 信息源
    信息: ["auto_fill_meta"], 刮削: ["auto_fill_meta", "META_SELECTED_SOURCES"], 抓取: ["auto_fill_meta", "META_SELECTED_SOURCES"],
    频率: ["auto_fill_qpm"], 每分钟: ["auto_fill_qpm"], 填充频率: ["auto_fill_qpm"], 刮削频率: ["auto_fill_qpm"],
    豆瓣: ["auto_fill_meta", "META_SELECTED_SOURCES", "douban_baseurl", "douban_apikey", "douban_max_count", "douban_v2_max_per_hour"], 书源: ["META_SELECTED_SOURCES", "auto_fill_meta"], 来源: ["META_SELECTED_SOURCES"], 选择来源: ["META_SELECTED_SOURCES"],
    每小时: ["douban_v2_max_per_hour"], 每小时上限: ["douban_v2_max_per_hour"], 豆瓣频率: ["douban_v2_max_per_hour"],
    镜像: ["douban_baseurl"], api: ["AI_API_URL", "AI_DEEPSEEK_API_KEY", "douban_apikey", "douban_baseurl"],
    密钥: ["douban_apikey", "AI_DEEPSEEK_API_KEY", "cookie_secret", "AI_MCP_TOKEN", "BOOKBARN_TOKEN"],
    数量: ["douban_max_count", "MAIN_PAGE_RANDOM_COUNT", "MAIN_PAGE_RECENT_COUNT"],
    // 外部服务 · 书栈 / AI
    书栈: ["ENABLE_BOOKBARN", "BOOKBARN_TOKEN"], barn: ["ENABLE_BOOKBARN"], token: ["BOOKBARN_TOKEN", "AI_MCP_TOKEN"], 令牌: ["BOOKBARN_TOKEN", "AI_MCP_TOKEN"], 授权: ["BOOKBARN_TOKEN", "AI_MCP_TOKEN"],
    ai: ["AI_ENABLED", "AI_DEEPSEEK_API_KEY", "AI_API_URL", "AI_MODEL", "AI_MCP_TOKEN", "AI_ALLOW_SET_CATEGORY"],
    人工智能: ["AI_ENABLED"], 助手: ["AI_ENABLED"], deepseek: ["AI_ENABLED", "AI_DEEPSEEK_API_KEY", "AI_MODEL"],
    模型: ["AI_MODEL"], 接口: ["AI_API_URL"], url: ["AI_API_URL", "douban_baseurl"],
    mcp: ["AI_MCP_TOKEN"], 自动分类: ["AI_ALLOW_SET_CATEGORY"], 生成分类: ["AI_ALLOW_SET_CATEGORY"],
    // 服务与协议
    webdav: ["ENABLE_WEBDAV_SERVICE", "WEBDAV_SYNC_FOLDER"], 挂载: ["ENABLE_WEBDAV_SERVICE"], 可写: ["WEBDAV_SYNC_FOLDER"], 可写目录: ["WEBDAV_SYNC_FOLDER"], 读写: ["ENABLE_WEBDAV_SERVICE", "WEBDAV_SYNC_FOLDER"],
    opds: ["ENABLE_OPDS_SERVICE", "ENABLE_OPDS_AUTH"], 认证: ["ENABLE_OPDS_AUTH"], 目录服务: ["ENABLE_OPDS_SERVICE", "ENABLE_OPDS_AUTH"], 需要密码: ["ENABLE_OPDS_AUTH"],
    订阅: ["ENABLE_PODCAST_SERVICE", "ENABLE_OPDS_SERVICE"], 播客: ["ENABLE_PODCAST_SERVICE"], podcast: ["ENABLE_PODCAST_SERVICE"], 听书: ["ENABLE_PODCAST_SERVICE", "ALLOW_GUEST_READ"], 有声: ["ENABLE_AUDIO_CONVERSION_LOG", "ENABLE_AUDIO_SUBTITLE", "ENABLE_PODCAST_SERVICE"], 有声书: ["ENABLE_PODCAST_SERVICE", "ENABLE_AUDIO_CONVERSION_LOG", "ENABLE_AUDIO_SUBTITLE"],
    cdn: ["static_host"], 域名: ["static_host"], 加速: ["static_host", "PERFORMANCE_MODE"], 静态: ["static_host"], 静态资源: ["static_host"],
    cookie: ["cookie_secret"], 安全: ["cookie_secret", "INVITE_MODE", "ENABLE_OPDS_AUTH", "SSL", "AI_MCP_TOKEN"], 随机密钥: ["cookie_secret"],
    证书: ["SSL", "static_host"], https: ["SSL", "static_host"], ssl证书: ["SSL"], 凭据: ["SSL", "cookie_secret"],
    // 系统与性能 · 性能与缓存
    极速: ["PERFORMANCE_MODE"], 性能: ["PERFORMANCE_MODE", "THUMB_CACHE"], 低配: ["PERFORMANCE_MODE"], 卡: ["PERFORMANCE_MODE", "THUMB_CACHE"], 慢: ["PERFORMANCE_MODE", "THUMB_CACHE"], 速度: ["PERFORMANCE_MODE"], 卡顿: ["PERFORMANCE_MODE", "THUMB_CACHE"],
    缓存: ["THUMB_CACHE", "CACHE_MAX_MB"], 缩略图: ["THUMB_CACHE"], 容量: ["CACHE_MAX_MB"], mb: ["CACHE_MAX_MB"], 缓存清理: ["TRASH", "THUMB_CACHE"],
    内存: ["LITE_GROUP_RESOURCES"], cpu: ["LITE_GROUP_RESOURCES", "PERFORMANCE_MODE"], 资源: ["LITE_GROUP_RESOURCES"], 省资源: ["LITE_GROUP_RESOURCES"],
    精简: ["LITE_GROUP_RECOMMEND", "LITE_GROUP_FILES", "LITE_GROUP_BACKGROUND"], 后台: ["LITE_GROUP_BACKGROUND"], 后台任务: ["LITE_GROUP_BACKGROUND"],
    搜索加速: ["LITE_GROUP_LISTING"], 列表加速: ["LITE_GROUP_LISTING"], 图片处理: ["LITE_GROUP_FILES"],
    // 系统与性能 · 日志与调试
    日志: ["LOG_LEVEL_DEBUG", "ENABLE_AUDIO_CONVERSION_LOG"], 调试: ["LOG_LEVEL_DEBUG"], debug: ["LOG_LEVEL_DEBUG"], 排错: ["LOG_LEVEL_DEBUG"], 转换日志: ["ENABLE_AUDIO_CONVERSION_LOG"],
    字幕: ["ENABLE_AUDIO_SUBTITLE"], srt: ["ENABLE_AUDIO_SUBTITLE"],
    重启: ["autoreload"], 生效: ["autoreload"], 超时: ["convert_timeout"], 时间: ["convert_timeout"], 转换超时: ["convert_timeout"],
    // 系统与性能 · 更新与工具箱
    更新: ["AUTO_CHECKING_NEW_VERSION", "ENABLE_TOOLBOX_STORE"], 版本: ["AUTO_CHECKING_NEW_VERSION"], 升级: ["AUTO_CHECKING_NEW_VERSION"], 检查: ["AUTO_CHECKING_NEW_VERSION"], 检查更新: ["AUTO_CHECKING_NEW_VERSION"],
    工具箱: ["ENABLE_TOOLBOX_DEV_MODE", "ENABLE_TOOLBOX_STORE"], 开发者: ["ENABLE_TOOLBOX_DEV_MODE"], 商店: ["ENABLE_TOOLBOX_STORE"], 插件: ["ENABLE_TOOLBOX_STORE", "ENABLE_TXT_TO_TXTZ_PLUGIN"],
    插件市场: ["ENABLE_TOOLBOX_STORE"], 上传zip: ["ENABLE_TOOLBOX_DEV_MODE"],
    // 系统与性能 · 维护与清理
    回收站: ["TRASH"], 清理: ["TRASH", "REMOVE_IMPORTED_FILE"], 磁盘: ["TRASH"], 空间: ["TRASH", "CACHE_MAX_MB"], 删除: ["TRASH", "REMOVE_IMPORTED_FILE"], 垃圾桶: ["TRASH"],
  },
  "zh-TW": {
    // 網站與外觀 · 網站標識
    站名: ["site_title"], 網站標題: ["site_title"], 網站名稱: ["site_title"], 名稱: ["site_title", "DEVICES"], 標題: ["site_title", "push_title"],
    圖示: ["site_icon"], 網站圖示: ["site_icon"], favicon: ["site_icon"], logo: ["site_icon"], 徽標: ["site_icon"],
    公告: ["HEADER"], 告示: ["HEADER"], 通知: ["HEADER", "SEND_MAIL_FOR_NEW_BOOKS"],
    頁尾: ["FOOTER"], 頁腳: ["FOOTER"], 腳註: ["FOOTER"], 底部: ["FOOTER"], 版權: ["FOOTER"],
    浮水印: ["FOOTER_WATERMARK"], 水印: ["FOOTER_WATERMARK"],
    預設連結: ["SITE_URL"], 存取連結: ["SITE_URL"], 分享連結: ["SITE_URL", "ENABLE_SHARE_LINK"], 分享網址: ["SITE_URL"], 對外網址: ["SITE_URL"], 外網: ["SITE_URL"], 內網: ["SITE_URL"], 二維碼: ["SITE_URL"],
    語言: ["site_language", "DEFAULT_LANGUAGE"], 語系: ["site_language"], 中文: ["site_language"], english: ["site_language"], 繁體: ["site_language"], 簡體: ["site_language"], 多語言: ["site_language", "DEFAULT_LANGUAGE"], 切換: ["site_language"], 預設語言: ["DEFAULT_LANGUAGE"],
    時區: ["site_timezone"], 系統時區: ["site_timezone"], 時區設定: ["site_timezone"], 東八區: ["site_timezone"], 格林威治: ["site_timezone"], 跨天: ["site_timezone"], 統計口徑: ["site_timezone"], utc: ["site_timezone"], timezone: ["site_timezone"],
    首頁: ["INDEX_PAGE_TYPE", "MAIN_PAGE_RANDOM_COUNT", "MAIN_PAGE_RECENT_COUNT"], 首頁類型: ["INDEX_PAGE_TYPE"],
    首頁卡片: ["HOMEPAGE_CONFIG"], 自訂卡片: ["HOMEPAGE_CONFIG"], 卡片: ["HOMEPAGE_CONFIG"], 作者卡片: ["HOMEPAGE_CONFIG"], 標籤卡片: ["HOMEPAGE_CONFIG"], 叢書卡片: ["HOMEPAGE_CONFIG"], 語言卡片: ["HOMEPAGE_CONFIG"], 評分卡片: ["HOMEPAGE_CONFIG"], 主頁: ["INDEX_PAGE_TYPE"],
    項目連結: ["HIDE_PROJECT_LINKS"], 隱藏連結: ["HIDE_PROJECT_LINKS"], 開源連結: ["HIDE_PROJECT_LINKS"],
    友情連結: ["FRIENDS"], 友鏈: ["FRIENDS"], 連結: ["FRIENDS", "HIDE_PROJECT_LINKS", "douban_baseurl", "AI_API_URL", "static_host", "SITE_URL"],
    網址: ["douban_baseurl", "AI_API_URL", "static_host", "SITE_URL"], 位址: ["douban_baseurl", "AI_API_URL", "static_host", "smtp_server", "SITE_URL"],
    // 網站與外觀 · 首頁與列表
    隨機: ["MAIN_PAGE_RANDOM_COUNT"], 推薦: ["RECOMMEND_ENABLE", "RECOMMEND_USE_CROWD", "ENABLE_BOOK_RECOMMEND_TO_OTHERS", "MAIN_PAGE_RANDOM_COUNT"], 智慧: ["RECOMMEND_ENABLE"], 智慧推薦: ["RECOMMEND_ENABLE"],
    協同: ["RECOMMEND_USE_CROWD"], 協同過濾: ["RECOMMEND_USE_CROWD"], 參考他人: ["RECOMMEND_USE_CROWD"],
    新書: ["MAIN_PAGE_RECENT_COUNT", "SEND_MAIL_FOR_NEW_BOOKS"], 最新: ["MAIN_PAGE_RECENT_COUNT"], 最近更新: ["MAIN_PAGE_RECENT_COUNT"], 新書推薦: ["MAIN_PAGE_RECENT_COUNT"],
    分頁: ["DEFAULT_PAGE_SIZE"], 每頁: ["DEFAULT_PAGE_SIZE"], 每頁數量: ["DEFAULT_PAGE_SIZE"],
    側邊欄: ["SIDEBAR_ITEMS"], 側欄: ["SIDEBAR_ITEMS"], 選單: ["SIDEBAR_ITEMS"], 導覽列: ["SIDEBAR_ITEMS"], 側邊導覽: ["SIDEBAR_ITEMS"],
    首頁顯示: ["HOMEPAGE_CONFIG"], 首頁模組: ["HOMEPAGE_CONFIG"],
    統計: ["HOMEPAGE_CONFIG", "ALLOW_USER_DISABLE_STATISTIC"], banner: ["HOMEPAGE_CONFIG"], 閱讀統計: ["HOMEPAGE_CONFIG"],
    在讀: ["HOMEPAGE_CONFIG"], 正在閱讀: ["HOMEPAGE_CONFIG"],
    書單: ["HOMEPAGE_CONFIG", "BOOK_NAV"], 書單推薦: ["HOMEPAGE_CONFIG"], 推薦書單: ["HOMEPAGE_CONFIG"],
    動效: ["ENABLE_HOME_MOTION"], 減少動效: ["ENABLE_HOME_MOTION"], 減弱動態效果: ["ENABLE_HOME_MOTION"],
    動畫: ["ENABLE_HOME_MOTION"], 輪播: ["ENABLE_HOME_MOTION"], 自動捲動: ["ENABLE_HOME_MOTION"],
    進場動畫: ["ENABLE_HOME_MOTION"], 淡入: ["ENABLE_HOME_MOTION"], 書單捲動: ["ENABLE_HOME_MOTION"], 封面捲動: ["ENABLE_HOME_MOTION"],
    推薦給他人: ["ENABLE_BOOK_RECOMMEND_TO_OTHERS", "HOMEPAGE_CONFIG"], 他人推薦: ["ENABLE_BOOK_RECOMMEND_TO_OTHERS", "HOMEPAGE_CONFIG"], "留言": ["ENABLE_USER_MEMOS"],
    實體書: ["ENABLE_PHYSICAL_BOOKS", "ENABLE_BOOKS_TYPE_CONVERT_DIRECT"], 紙書: ["ENABLE_PHYSICAL_BOOKS"], 紙本書: ["ENABLE_PHYSICAL_BOOKS"], 書架: ["ENABLE_PHYSICAL_BOOKS"], 印刷: ["ENABLE_PHYSICAL_BOOKS"],
    類型轉換: ["ENABLE_BOOKS_TYPE_CONVERT_DIRECT"], 直接轉換: ["ENABLE_BOOKS_TYPE_CONVERT_DIRECT"], 格式轉換: ["ENABLE_BOOKS_TYPE_CONVERT_DIRECT", "ENABLE_TXT_TO_TXTZ_PLUGIN"],
    // 網站與外觀 · 書籍分類
    分類: ["BOOK_NAV", "IMPORT_CATEGORY_WITH_FOLDER", "ENABLE_FOLDER_BROWSE", "AI_ALLOW_SET_CATEGORY"], 導覽: ["BOOK_NAV"], 標籤: ["BOOK_NAV"],
    分類導覽: ["BOOK_NAV"], 分類管理: ["BOOK_NAV"], 分類樹: ["BOOK_NAV"],
    // 閱讀與內容 · 閱讀器與同步
    閱讀器: ["EPUB_VIEWER", "DEVICES"], epub: ["EPUB_VIEWER"], epubjs: ["EPUB_VIEWER"], myreader: ["EPUB_VIEWER", "ENABLE_DATA_SYNC"], 閱讀引擎: ["EPUB_VIEWER"],
    同步: ["ENABLE_DATA_SYNC", "ENABLE_WEBDAV_SERVICE", "WEBDAV_SYNC_FOLDER"], 進度: ["ENABLE_DATA_SYNC"], 閱讀資料: ["ENABLE_DATA_SYNC"], 跨裝置: ["ENABLE_DATA_SYNC", "DEVICES"],
    封面: ["USE_DYNAMIC_COVER", "ENABLE_STAMP_FEATURE", "THUMB_CACHE"], 動態封面: ["USE_DYNAMIC_COVER"], 書封: ["USE_DYNAMIC_COVER"],
    作者: ["ENABLE_AUTHOR_INFO"], 簡介: ["ENABLE_AUTHOR_INFO"], 頭像: ["ENABLE_AUTHOR_INFO"], 作者資訊: ["ENABLE_AUTHOR_INFO"],
    隱私: ["ALLOW_USER_DISABLE_STATISTIC"], 採集: ["ALLOW_USER_DISABLE_STATISTIC"], 資料採集: ["ALLOW_USER_DISABLE_STATISTIC"],
    筆記: ["ENABLE_SHARED_NOTES"], 劃線: ["ENABLE_SHARED_NOTES"], 標註: ["ENABLE_SHARED_NOTES"], 分享筆記: ["ENABLE_SHARED_NOTES"],
    // 閱讀與內容 · 詞典
    詞典: ["READER_MYDICTS", "READER_DICT_MYBOOKS_ENABLED", "READER_DICT_BAIKE_ENABLED"],
    字典: ["READER_MYDICTS", "READER_DICT_MYBOOKS_ENABLED", "READER_DICT_BAIKE_ENABLED"],
    翻譯: ["READER_MYDICTS", "READER_DICT_MYBOOKS_ENABLED", "READER_DICT_BAIKE_ENABLED"],
    生詞: ["READER_MYDICTS"], 查詞: ["READER_MYDICTS"], 劃詞: ["READER_MYDICTS"],
    百科: ["READER_DICT_BAIKE_ENABLED"], 百度百科: ["READER_DICT_BAIKE_ENABLED"],
    // 閱讀與內容 · 書評與互動
    評論: ["ENABLE_BOOK_REVIEW", "REVIEW_REQUIRES_APPROVAL", "ENABLE_BOOK_RECOMMEND_TO_OTHERS"], 評分: ["ENABLE_BOOK_REVIEW"], 書評: ["ENABLE_BOOK_REVIEW"], 打分: ["ENABLE_BOOK_REVIEW"], 星等: ["ENABLE_BOOK_REVIEW"],
    審核: ["REVIEW_REQUIRES_APPROVAL", "ENABLE_AUTO_NEW_USER_APPROVAL"], 先審後發: ["REVIEW_REQUIRES_APPROVAL"],
    // 閱讀與內容 · 實體書與圖章
    資料夾: ["ENABLE_FOLDER_BROWSE"], 層級: ["ENABLE_FOLDER_BROWSE"], 多層目錄: ["ENABLE_FOLDER_BROWSE"], 多級分類: ["ENABLE_FOLDER_BROWSE"],
    圖章: ["ENABLE_STAMP_FEATURE"], 蓋章: ["ENABLE_STAMP_FEATURE"], 印章: ["ENABLE_STAMP_FEATURE"],
    // 用戶與訪問 · 存取權限
    訪客: ["ALLOW_GUEST_READ", "ALLOW_GUEST_DOWNLOAD", "ALLOW_GUEST_UPLOAD", "ALLOW_GUEST_PUSH", "ENABLE_SHARE_LINK"],
    遊客: ["ALLOW_GUEST_READ", "ALLOW_GUEST_DOWNLOAD", "ALLOW_GUEST_UPLOAD", "ALLOW_GUEST_PUSH", "ENABLE_SHARE_LINK"],
    匿名: ["ALLOW_GUEST_READ", "ALLOW_GUEST_DOWNLOAD"], 免登入: ["ALLOW_GUEST_READ", "ALLOW_GUEST_DOWNLOAD", "ALLOW_GUEST_UPLOAD", "ALLOW_GUEST_PUSH", "ENABLE_SHARE_LINK"], 未登入: ["ALLOW_GUEST_READ", "ALLOW_GUEST_DOWNLOAD"],
    線上閱讀: ["ALLOW_GUEST_READ"], 試閱: ["ALLOW_GUEST_READ"],
    分享: ["ENABLE_SHARE_LINK", "ENABLE_SHARED_NOTES"], 直連: ["ENABLE_SHARE_LINK"], 連結閱讀: ["ENABLE_SHARE_LINK"], 分享閱讀: ["ENABLE_SHARE_LINK"],
    // 用戶與訪問 · 註冊與邀請
    邀請: ["INVITE_MODE", "INVITE_CODE"], 私人: ["INVITE_MODE"], 私人圖書館: ["INVITE_MODE"], 私密: ["INVITE_MODE"], 存取碼: ["INVITE_MODE", "INVITE_CODE"], 註冊碼: ["INVITE_CODE", "INVITE_MODE"], 邀請碼: ["INVITE_CODE", "INVITE_MODE"], 封閉: ["INVITE_MODE"],
    密碼鎖: ["INVITE_MODE", "INVITE_CODE"], 通關密語: ["INVITE_CODE"],
    提示語: ["INVITE_MESSAGE"], 歡迎詞: ["INVITE_MESSAGE"], 邀請訊息: ["INVITE_MESSAGE"],
    註冊: ["ALLOW_REGISTER", "SIGNUP_MAIL_TITLE", "ENABLE_AUTO_NEW_USER_APPROVAL"], 開放註冊: ["ALLOW_REGISTER"], 信箱註冊: ["ALLOW_REGISTER"],
    啟用: ["SIGNUP_MAIL_TITLE", "SIGNUP_MAIL_CONTENT"], 啟用信: ["SIGNUP_MAIL_TITLE", "SIGNUP_MAIL_CONTENT"], 驗證信: ["SIGNUP_MAIL_TITLE", "SIGNUP_MAIL_CONTENT"],
    重設: ["RESET_MAIL_TITLE", "RESET_MAIL_CONTENT"], 找回: ["RESET_MAIL_TITLE", "RESET_MAIL_CONTENT"], 重設密碼: ["RESET_MAIL_TITLE", "RESET_MAIL_CONTENT"], 忘記密碼: ["RESET_MAIL_TITLE", "RESET_MAIL_CONTENT"],
    主旨: ["push_title", "RESET_MAIL_TITLE", "SIGNUP_MAIL_TITLE"], 主題: ["push_title", "RESET_MAIL_TITLE", "SIGNUP_MAIL_TITLE"], 內文: ["push_content", "RESET_MAIL_CONTENT", "SIGNUP_MAIL_CONTENT"], 內容: ["push_content", "RESET_MAIL_CONTENT", "SIGNUP_MAIL_CONTENT", "INVITE_MESSAGE"],
    // 用戶與訪問 · 預設權限與配額
    審批: ["ENABLE_AUTO_NEW_USER_APPROVAL", "REVIEW_REQUIRES_APPROVAL"], 自動審批: ["ENABLE_AUTO_NEW_USER_APPROVAL"],
    新使用者: ["ALLOW_NEW_USER_MANAGE_BOOK", "ALLOW_NEW_USER_PUSH_BOOK", "ENABLE_AUTO_NEW_USER_APPROVAL", "DEFAULT_READ_RANGE"],
    權限: ["ALLOW_NEW_USER_MANAGE_BOOK", "ALLOW_NEW_USER_PUSH_BOOK", "ALLOW_READ_RANGE_SETTING"], 預設權限: ["ALLOW_NEW_USER_MANAGE_BOOK", "ALLOW_NEW_USER_PUSH_BOOK"], 管理權限: ["ALLOW_NEW_USER_MANAGE_BOOK"],
    白名單: ["ALLOW_READ_RANGE_SETTING", "DEFAULT_READ_RANGE"], 黑名單: ["ALLOW_READ_RANGE_SETTING", "DEFAULT_READ_RANGE"],
    可見: ["ALLOW_READ_RANGE_SETTING", "DEFAULT_READ_RANGE"], 封鎖: ["ALLOW_READ_RANGE_SETTING", "DEFAULT_READ_RANGE"], 不可見: ["ALLOW_READ_RANGE_SETTING", "DEFAULT_READ_RANGE"],
    範圍: ["ALLOW_READ_RANGE_SETTING", "DEFAULT_READ_RANGE"], 閱讀範圍: ["ALLOW_READ_RANGE_SETTING", "DEFAULT_READ_RANGE"],
    配額: ["ENABLE_DOWNLOAD_QUOTA", "GLOBAL_DOWNLOAD_QUOTA"], 下載: ["ENABLE_DOWNLOAD_QUOTA", "GLOBAL_DOWNLOAD_QUOTA", "ALLOW_GUEST_DOWNLOAD"], 每日: ["ENABLE_DOWNLOAD_QUOTA", "GLOBAL_DOWNLOAD_QUOTA"],
    下載限制: ["ENABLE_DOWNLOAD_QUOTA", "GLOBAL_DOWNLOAD_QUOTA"], 每日下載: ["ENABLE_DOWNLOAD_QUOTA", "GLOBAL_DOWNLOAD_QUOTA"],
    // 用戶與訪問 · 社群登入
    登入: ["SOCIALS", "ALLOW_REGISTER", "INVITE_MODE"], 第三方: ["SOCIALS"], 社群: ["SOCIALS"], 社群網路: ["SOCIALS"], oauth: ["SOCIALS"], qq: ["SOCIALS"], 微信: ["SOCIALS"], 微博: ["SOCIALS"], github: ["SOCIALS"],
    單一登入: ["SOCIALS"], 第三方登入: ["SOCIALS"],
    // 匯入與儲存 · 上傳
    掃描: ["scan_upload_path", "PDF_TILE_WITH_FILE_NAME"], 批次: ["scan_upload_path", "BATCH_ADD_IN_FORCE"], 掃描目錄: ["scan_upload_path"], 匯入目錄: ["scan_upload_path"],
    上傳: ["MAX_UPLOAD_SIZE", "CHUNK_UPLOAD_SIZE", "scan_upload_path", "ALLOW_GUEST_UPLOAD", "KEEP_UPLOAD_SOURCE_FILE"],
    大小: ["MAX_UPLOAD_SIZE", "CACHE_MAX_MB"], 檔案大小: ["MAX_UPLOAD_SIZE"], 上傳限制: ["MAX_UPLOAD_SIZE", "CHUNK_UPLOAD_SIZE"],
    上限: ["MAX_UPLOAD_SIZE", "CHUNK_UPLOAD_SIZE", "ENABLE_DOWNLOAD_QUOTA", "GLOBAL_DOWNLOAD_QUOTA", "CACHE_MAX_MB"],
    分片: ["CHUNK_UPLOAD_SIZE"], 大檔案: ["CHUNK_UPLOAD_SIZE"], 續傳: ["CHUNK_UPLOAD_SIZE"],
    詮釋資料: ["auto_fill_meta", "META_SELECTED_SOURCES", "DEFAULT_LANGUAGE"], 中介資料: ["auto_fill_meta", "META_SELECTED_SOURCES", "DEFAULT_LANGUAGE"], 書籍資訊: ["auto_fill_meta", "META_SELECTED_SOURCES"], 資訊來源: ["META_SELECTED_SOURCES", "douban_baseurl"],
    來源檔案: ["KEEP_UPLOAD_SOURCE_FILE", "REMOVE_IMPORTED_FILE"], 保留: ["KEEP_UPLOAD_SOURCE_FILE"], 暫存檔案: ["KEEP_UPLOAD_SOURCE_FILE"], 原始檔: ["KEEP_UPLOAD_SOURCE_FILE", "REMOVE_IMPORTED_FILE"],
    刪除原始檔: ["REMOVE_IMPORTED_FILE"], 匯入後刪除: ["REMOVE_IMPORTED_FILE"],
    // 匯入與儲存 · 匯入規則
    pdf: ["PDF_TILE_WITH_FILE_NAME"], 檔名: ["PDF_TILE_WITH_FILE_NAME", "BOOK_NAMES_FORMAT"], 書名: ["PDF_TILE_WITH_FILE_NAME"],
    txt: ["ENABLE_TXT_TO_TXTZ_PLUGIN"], txtz: ["ENABLE_TXT_TO_TXTZ_PLUGIN"], 轉換: ["ENABLE_TXT_TO_TXTZ_PLUGIN", "convert_timeout", "ENABLE_BOOKS_TYPE_CONVERT_DIRECT"],
    伺服器: ["ENABLE_SERVER_FILE_IMPORT", "smtp_server"], 目錄瀏覽: ["ENABLE_SERVER_FILE_IMPORT"], 伺服器匯入: ["ENABLE_SERVER_FILE_IMPORT"],
    isbn: ["BATCH_ADD_IN_FORCE"], 強制: ["BATCH_ADD_IN_FORCE"], 無效: ["BATCH_ADD_IN_FORCE"], 強制加入: ["BATCH_ADD_IN_FORCE"],
    第一層目錄: ["IMPORT_CATEGORY_WITH_FOLDER"], 目錄分類: ["IMPORT_CATEGORY_WITH_FOLDER"], 自訂類別: ["IMPORT_CATEGORY_WITH_FOLDER"],
    限流: ["auto_fill_pause_on_throttle", "ENABLE_DOWNLOAD_QUOTA"], 暫停: ["auto_fill_pause_on_throttle"], 自動暫停: ["auto_fill_pause_on_throttle"], 節流: ["auto_fill_pause_on_throttle"],
    重複: ["UPLOAD_IGNORE_TITLE_CHECKING"], 同書: ["UPLOAD_IGNORE_TITLE_CHECKING"], 重複檢查: ["UPLOAD_IGNORE_TITLE_CHECKING"], 同名書: ["UPLOAD_IGNORE_TITLE_CHECKING"],
    // 匯入與儲存 · 自動匯入 / 儲存布局
    監控: ["IMPORT_BY_INOTIFY", "UPDATE_CATEGORY_WITH_FOLDER_RENAME"], 自動匯入: ["IMPORT_BY_INOTIFY"], inotify: ["IMPORT_BY_INOTIFY"], 監視: ["IMPORT_BY_INOTIFY"], 即時匯入: ["IMPORT_BY_INOTIFY"],
    重新命名: ["UPDATE_CATEGORY_WITH_FOLDER_RENAME"], 目錄改名: ["UPDATE_CATEGORY_WITH_FOLDER_RENAME"],
    拼音: ["BOOK_NAMES_FORMAT"], utf8: ["BOOK_NAMES_FORMAT"], 儲存: ["BOOK_NAMES_FORMAT", "TRASH"], 儲存布局: ["BOOK_NAMES_FORMAT"], 編碼: ["BOOK_NAMES_FORMAT"], 亂碼: ["BOOK_NAMES_FORMAT"], 檔名模式: ["BOOK_NAMES_FORMAT"],
    // 推送與郵件 · 郵件服務
    smtp: ["smtp_server", "smtp_username", "smtp_password", "smtp_encryption"], 郵件伺服器: ["smtp_server"], 帳號: ["smtp_username"], 使用者名稱: ["smtp_username"], 寄件: ["smtp_server", "smtp_username"],
    授權碼: ["smtp_password"], 郵件密碼: ["smtp_password"], 加密: ["smtp_encryption"], ssl: ["smtp_encryption", "SSL"], tls: ["smtp_encryption"], 連接埠: ["smtp_server", "smtp_encryption"], 埠: ["smtp_encryption"],
    郵件: ["smtp_server", "smtp_username", "smtp_password", "smtp_encryption", "push_title", "push_content", "SEND_MAIL_FOR_NEW_BOOKS", "SIGNUP_MAIL_TITLE", "SIGNUP_MAIL_CONTENT", "RESET_MAIL_TITLE", "RESET_MAIL_CONTENT"],
    信箱: ["smtp_server", "smtp_username", "smtp_password", "smtp_encryption", "push_title", "SEND_MAIL_FOR_NEW_BOOKS"],
    推送: ["DEVICES", "push_title", "push_content", "SEND_MAIL_FOR_NEW_BOOKS", "ALLOW_GUEST_PUSH", "ALLOW_NEW_USER_PUSH_BOOK", "smtp_server"],
    kindle: ["DEVICES", "push_title", "smtp_server"], 郵件主旨: ["push_title"], 郵件內文: ["push_content"],
    提醒: ["SEND_MAIL_FOR_NEW_BOOKS"], 郵件提醒: ["SEND_MAIL_FOR_NEW_BOOKS"], 通知信: ["SEND_MAIL_FOR_NEW_BOOKS", "push_title"], 發送: ["SEND_MAIL_FOR_NEW_BOOKS", "smtp_server"], 寄送: ["SEND_MAIL_FOR_NEW_BOOKS"],
    // 推送與郵件 · 推送裝置
    裝置: ["DEVICES"], 設備: ["DEVICES"], 推送裝置: ["DEVICES"], 推送設備: ["DEVICES"], 閱讀裝置: ["DEVICES"], 裝置管理: ["DEVICES"], 绑定裝置: ["DEVICES"],
    文石: ["DEVICES"], 掌閱: ["DEVICES"], 漢王: ["DEVICES"], 當當: ["DEVICES"], koreader: ["DEVICES"], duokan: ["DEVICES"], ireader: ["DEVICES"], boox: ["DEVICES"], purelibro: ["DEVICES"], ftp: ["DEVICES"],
    // 外部服務 · 資訊來源
    資訊: ["auto_fill_meta"], 擷取: ["auto_fill_meta", "META_SELECTED_SOURCES"], 網路擷取: ["auto_fill_meta"],
    頻率: ["auto_fill_qpm"], 每分鐘: ["auto_fill_qpm"], 填充頻率: ["auto_fill_qpm"], 擷取頻率: ["auto_fill_qpm"],
    豆瓣: ["auto_fill_meta", "META_SELECTED_SOURCES", "douban_baseurl", "douban_apikey", "douban_max_count", "douban_v2_max_per_hour"], 書源: ["META_SELECTED_SOURCES", "auto_fill_meta"], 來源: ["META_SELECTED_SOURCES"], 選擇來源: ["META_SELECTED_SOURCES"],
    每小時: ["douban_v2_max_per_hour"], 每小時上限: ["douban_v2_max_per_hour"], 豆瓣頻率: ["douban_v2_max_per_hour"],
    鏡像: ["douban_baseurl"], api: ["AI_API_URL", "AI_DEEPSEEK_API_KEY", "douban_apikey", "douban_baseurl"],
    金鑰: ["douban_apikey", "AI_DEEPSEEK_API_KEY", "cookie_secret", "AI_MCP_TOKEN", "BOOKBARN_TOKEN"],
    數量: ["douban_max_count", "MAIN_PAGE_RANDOM_COUNT", "MAIN_PAGE_RECENT_COUNT"],
    // 外部服務 · 書棧 / AI
    書棧: ["ENABLE_BOOKBARN", "BOOKBARN_TOKEN"], barn: ["ENABLE_BOOKBARN"], token: ["BOOKBARN_TOKEN", "AI_MCP_TOKEN"], 權杖: ["BOOKBARN_TOKEN", "AI_MCP_TOKEN"], 授權: ["BOOKBARN_TOKEN", "AI_MCP_TOKEN"],
    ai: ["AI_ENABLED", "AI_DEEPSEEK_API_KEY", "AI_API_URL", "AI_MODEL", "AI_MCP_TOKEN", "AI_ALLOW_SET_CATEGORY"],
    人工智慧: ["AI_ENABLED"], 助手: ["AI_ENABLED"], deepseek: ["AI_ENABLED", "AI_DEEPSEEK_API_KEY", "AI_MODEL"],
    模型: ["AI_MODEL"], 介面: ["AI_API_URL"], url: ["AI_API_URL", "douban_baseurl"], 鏈接: ["AI_API_URL", "douban_baseurl", "static_host", "FRIENDS"],
    mcp: ["AI_MCP_TOKEN"], 自動分類: ["AI_ALLOW_SET_CATEGORY"], 產生分類: ["AI_ALLOW_SET_CATEGORY"],
    // 服務與協議
    webdav: ["ENABLE_WEBDAV_SERVICE", "WEBDAV_SYNC_FOLDER"], 掛載: ["ENABLE_WEBDAV_SERVICE"], 可寫: ["WEBDAV_SYNC_FOLDER"], 可寫目錄: ["WEBDAV_SYNC_FOLDER"], 讀寫: ["ENABLE_WEBDAV_SERVICE", "WEBDAV_SYNC_FOLDER"],
    opds: ["ENABLE_OPDS_SERVICE", "ENABLE_OPDS_AUTH"], 認證: ["ENABLE_OPDS_AUTH"], 目錄服務: ["ENABLE_OPDS_SERVICE", "ENABLE_OPDS_AUTH"], 需要密碼: ["ENABLE_OPDS_AUTH"],
    訂閱: ["ENABLE_PODCAST_SERVICE", "ENABLE_OPDS_SERVICE"], 播客: ["ENABLE_PODCAST_SERVICE"], podcast: ["ENABLE_PODCAST_SERVICE"], 聽書: ["ENABLE_PODCAST_SERVICE", "ALLOW_GUEST_READ"], 有聲: ["ENABLE_AUDIO_CONVERSION_LOG", "ENABLE_AUDIO_SUBTITLE", "ENABLE_PODCAST_SERVICE"], 有聲書: ["ENABLE_PODCAST_SERVICE", "ENABLE_AUDIO_CONVERSION_LOG", "ENABLE_AUDIO_SUBTITLE"],
    cdn: ["static_host"], 網域: ["static_host"], 加速: ["static_host", "PERFORMANCE_MODE"], 靜態: ["static_host"], 靜態資源: ["static_host"],
    cookie: ["cookie_secret"], 安全: ["cookie_secret", "INVITE_MODE", "ENABLE_OPDS_AUTH", "SSL", "AI_MCP_TOKEN"], 隨機金鑰: ["cookie_secret"],
    憑證: ["SSL", "static_host"], https: ["SSL", "static_host"], ssl憑證: ["SSL"],
    // 系統與效能 · 效能與快取
    極速: ["PERFORMANCE_MODE"], 效能: ["PERFORMANCE_MODE", "THUMB_CACHE"], 低階: ["PERFORMANCE_MODE"], 卡: ["PERFORMANCE_MODE", "THUMB_CACHE"], 慢: ["PERFORMANCE_MODE", "THUMB_CACHE"], 速度: ["PERFORMANCE_MODE"], 卡頓: ["PERFORMANCE_MODE", "THUMB_CACHE"],
    快取: ["THUMB_CACHE", "CACHE_MAX_MB"], 縮圖: ["THUMB_CACHE"], 容量: ["CACHE_MAX_MB"], mb: ["CACHE_MAX_MB"], 快取清理: ["TRASH", "THUMB_CACHE"],
    記憶體: ["LITE_GROUP_RESOURCES"], cpu: ["LITE_GROUP_RESOURCES", "PERFORMANCE_MODE"], 資源: ["LITE_GROUP_RESOURCES"], 省資源: ["LITE_GROUP_RESOURCES"],
    精簡: ["LITE_GROUP_RECOMMEND", "LITE_GROUP_FILES", "LITE_GROUP_BACKGROUND"], 背景: ["LITE_GROUP_BACKGROUND"], 背景工作: ["LITE_GROUP_BACKGROUND"],
    搜尋加速: ["LITE_GROUP_LISTING"], 清單加速: ["LITE_GROUP_LISTING"], 圖片處理: ["LITE_GROUP_FILES"],
    // 系統與效能 · 日誌與除錯
    日誌: ["LOG_LEVEL_DEBUG", "ENABLE_AUDIO_CONVERSION_LOG"], 除錯: ["LOG_LEVEL_DEBUG"], 偵錯: ["LOG_LEVEL_DEBUG"], debug: ["LOG_LEVEL_DEBUG"], 轉換日誌: ["ENABLE_AUDIO_CONVERSION_LOG"],
    字幕: ["ENABLE_AUDIO_SUBTITLE"], srt: ["ENABLE_AUDIO_SUBTITLE"],
    重新啟動: ["autoreload"], 重啟: ["autoreload"], 生效: ["autoreload"], 逾時: ["convert_timeout"], 超時: ["convert_timeout"], 時間: ["convert_timeout"],
    // 系統與效能 · 更新與工具箱
    更新: ["AUTO_CHECKING_NEW_VERSION", "ENABLE_TOOLBOX_STORE"], 版本: ["AUTO_CHECKING_NEW_VERSION"], 升級: ["AUTO_CHECKING_NEW_VERSION"], 檢查: ["AUTO_CHECKING_NEW_VERSION"], 檢查更新: ["AUTO_CHECKING_NEW_VERSION"],
    工具箱: ["ENABLE_TOOLBOX_DEV_MODE", "ENABLE_TOOLBOX_STORE"], 開發者: ["ENABLE_TOOLBOX_DEV_MODE"], 商店: ["ENABLE_TOOLBOX_STORE"], 外掛: ["ENABLE_TOOLBOX_STORE", "ENABLE_TXT_TO_TXTZ_PLUGIN"],
    外掛商店: ["ENABLE_TOOLBOX_STORE"], 上傳zip: ["ENABLE_TOOLBOX_DEV_MODE"],
    // 系統與效能 · 檔案清理
    回收筒: ["TRASH"], 回收桶: ["TRASH"], 垃圾桶: ["TRASH"], 清理: ["TRASH", "REMOVE_IMPORTED_FILE"], 磁碟: ["TRASH"], 硬碟: ["TRASH"], 空間: ["TRASH", "CACHE_MAX_MB"], 刪除: ["TRASH", "REMOVE_IMPORTED_FILE"],
  },
  en: {
    // Site & Appearance · site identity
    "site name": ["site_title"], "site title": ["site_title"], "website name": ["site_title"], name: ["site_title", "DEVICES"], title: ["site_title", "push_title"], subject: ["push_title", "RESET_MAIL_TITLE", "SIGNUP_MAIL_TITLE"],
    icon: ["site_icon"], favicon: ["site_icon"], logo: ["site_icon"], brand: ["site_icon"],
    "default url": ["SITE_URL"], "site url": ["SITE_URL"], "share link": ["SITE_URL", "ENABLE_SHARE_LINK"], "share url": ["SITE_URL"], "external url": ["SITE_URL"], "public url": ["SITE_URL"], "base url": ["SITE_URL"], qrcode: ["SITE_URL"], "qr code": ["SITE_URL"], lan: ["SITE_URL"],
    header: ["HEADER"], announcement: ["HEADER"], notice: ["HEADER"], "site header": ["HEADER"],
    footer: ["FOOTER"], copyright: ["FOOTER"], watermark: ["FOOTER_WATERMARK"],
    language: ["site_language", "DEFAULT_LANGUAGE"], languages: ["site_language"], locale: ["site_language"], i18n: ["site_language"], multilingual: ["site_language"], english: ["site_language"], chinese: ["site_language"], traditional: ["site_language"], simplified: ["site_language"], "default language": ["DEFAULT_LANGUAGE"],
    timezone: ["site_timezone"], "time zone": ["site_timezone"], tz: ["site_timezone"], utc: ["site_timezone"], gmt: ["site_timezone"], offset: ["site_timezone"], "day boundary": ["site_timezone"], streak: ["site_timezone", "HOMEPAGE_CONFIG"],
    homepage: ["INDEX_PAGE_TYPE", "MAIN_PAGE_RANDOM_COUNT", "MAIN_PAGE_RECENT_COUNT", "HOMEPAGE_CONFIG"], "index page": ["INDEX_PAGE_TYPE"], "page type": ["INDEX_PAGE_TYPE"], landing: ["INDEX_PAGE_TYPE"],
    "homepage cards": ["HOMEPAGE_CONFIG"], "custom cards": ["HOMEPAGE_CONFIG"], "home cards": ["HOMEPAGE_CONFIG"], "author card": ["HOMEPAGE_CONFIG"], "tag card": ["HOMEPAGE_CONFIG"], "series card": ["HOMEPAGE_CONFIG"], "language card": ["HOMEPAGE_CONFIG"], "rating card": ["HOMEPAGE_CONFIG"],
    links: ["FRIENDS", "HIDE_PROJECT_LINKS", "douban_baseurl", "AI_API_URL", "static_host"], link: ["FRIENDS", "HIDE_PROJECT_LINKS", "douban_baseurl", "AI_API_URL", "static_host", "SITE_URL"], "friend links": ["FRIENDS"], friends: ["FRIENDS"], "project links": ["HIDE_PROJECT_LINKS"], "hide links": ["HIDE_PROJECT_LINKS"],
    url: ["AI_API_URL", "douban_baseurl", "static_host", "SITE_URL"], address: ["douban_baseurl", "AI_API_URL", "static_host", "smtp_server", "SITE_URL"], endpoint: ["AI_API_URL", "douban_baseurl"],
    // Site & Appearance · home & listing
    random: ["MAIN_PAGE_RANDOM_COUNT"], shuffle: ["MAIN_PAGE_RANDOM_COUNT"],
    recommend: ["RECOMMEND_ENABLE", "RECOMMEND_USE_CROWD", "ENABLE_BOOK_RECOMMEND_TO_OTHERS", "MAIN_PAGE_RANDOM_COUNT", "HOMEPAGE_CONFIG"], recommendation: ["RECOMMEND_ENABLE"], recommendations: ["RECOMMEND_ENABLE"], smart: ["RECOMMEND_ENABLE"], recommender: ["RECOMMEND_ENABLE"],
    crowd: ["RECOMMEND_USE_CROWD"], collaborative: ["RECOMMEND_USE_CROWD"], "other users": ["RECOMMEND_USE_CROWD"], community: ["RECOMMEND_USE_CROWD"],
    recent: ["MAIN_PAGE_RECENT_COUNT"], latest: ["MAIN_PAGE_RECENT_COUNT"], newest: ["MAIN_PAGE_RECENT_COUNT"], "new books": ["MAIN_PAGE_RECENT_COUNT", "SEND_MAIL_FOR_NEW_BOOKS"],
    pagination: ["DEFAULT_PAGE_SIZE"], "page size": ["DEFAULT_PAGE_SIZE"], "per page": ["DEFAULT_PAGE_SIZE"], "items per page": ["DEFAULT_PAGE_SIZE"],
    sidebar: ["SIDEBAR_ITEMS"], menu: ["SIDEBAR_ITEMS"], navigation: ["SIDEBAR_ITEMS"], nav: ["SIDEBAR_ITEMS", "BOOK_NAV"],
    "homepage display": ["HOMEPAGE_CONFIG"], widgets: ["HOMEPAGE_CONFIG"],
    stats: ["HOMEPAGE_CONFIG", "ALLOW_USER_DISABLE_STATISTIC"], statistics: ["HOMEPAGE_CONFIG", "ALLOW_USER_DISABLE_STATISTIC"], "reading stats": ["HOMEPAGE_CONFIG"], banner: ["HOMEPAGE_CONFIG"],
    "currently reading": ["HOMEPAGE_CONFIG"], "reading now": ["HOMEPAGE_CONFIG"], "in progress": ["HOMEPAGE_CONFIG"],
    booklist: ["HOMEPAGE_CONFIG", "BOOK_NAV"], "book list": ["HOMEPAGE_CONFIG", "BOOK_NAV"], collections: ["HOMEPAGE_CONFIG"], featured: ["HOMEPAGE_CONFIG"],
    // People look for this switch with words like "motion" / "animation" (turning it off
    // stops entrance animations, cover fade-ins and the booklist cover auto-scroll),
    // while the label only says "Homepage animations"
    motion: ["ENABLE_HOME_MOTION"], "reduced motion": ["ENABLE_HOME_MOTION"], animation: ["ENABLE_HOME_MOTION"], animations: ["ENABLE_HOME_MOTION"], animate: ["ENABLE_HOME_MOTION"],
    marquee: ["ENABLE_HOME_MOTION"], carousel: ["ENABLE_HOME_MOTION"], autoscroll: ["ENABLE_HOME_MOTION"], "auto scroll": ["ENABLE_HOME_MOTION"], "cover scroll": ["ENABLE_HOME_MOTION"], "entrance animation": ["ENABLE_HOME_MOTION"], "fade in": ["ENABLE_HOME_MOTION"],
    "recommend to others": ["ENABLE_BOOK_RECOMMEND_TO_OTHERS", "HOMEPAGE_CONFIG"], "share books": ["ENABLE_BOOK_RECOMMEND_TO_OTHERS", "HOMEPAGE_CONFIG"], "memo": ["ENABLE_USER_MEMOS"],
    physical: ["ENABLE_PHYSICAL_BOOKS", "ENABLE_BOOKS_TYPE_CONVERT_DIRECT"], hardcopy: ["ENABLE_PHYSICAL_BOOKS"], print: ["ENABLE_PHYSICAL_BOOKS"], printed: ["ENABLE_PHYSICAL_BOOKS"], "paper books": ["ENABLE_PHYSICAL_BOOKS"], shelf: ["ENABLE_PHYSICAL_BOOKS"], bookshelf: ["ENABLE_PHYSICAL_BOOKS"],
    convert: ["ENABLE_BOOKS_TYPE_CONVERT_DIRECT", "ENABLE_TXT_TO_TXTZ_PLUGIN"], conversion: ["ENABLE_BOOKS_TYPE_CONVERT_DIRECT", "ENABLE_TXT_TO_TXTZ_PLUGIN"],
    // Site & Appearance · categories
    category: ["BOOK_NAV", "IMPORT_CATEGORY_WITH_FOLDER", "AI_ALLOW_SET_CATEGORY"], categories: ["BOOK_NAV", "IMPORT_CATEGORY_WITH_FOLDER"], categorize: ["AI_ALLOW_SET_CATEGORY"], tag: ["BOOK_NAV"], tags: ["BOOK_NAV"],
    // Reading & Content · reader & sync
    reader: ["EPUB_VIEWER", "DEVICES"], epub: ["EPUB_VIEWER"], epubjs: ["EPUB_VIEWER"], myreader: ["EPUB_VIEWER", "ENABLE_DATA_SYNC"], viewer: ["EPUB_VIEWER"], engine: ["EPUB_VIEWER"],
    sync: ["ENABLE_DATA_SYNC", "ENABLE_WEBDAV_SERVICE", "WEBDAV_SYNC_FOLDER"], progress: ["ENABLE_DATA_SYNC"], "data sync": ["ENABLE_DATA_SYNC"], "cross device": ["ENABLE_DATA_SYNC", "DEVICES"],
    cover: ["USE_DYNAMIC_COVER", "ENABLE_STAMP_FEATURE", "THUMB_CACHE"], "dynamic cover": ["USE_DYNAMIC_COVER"], "book cover": ["USE_DYNAMIC_COVER"],
    author: ["ENABLE_AUTHOR_INFO"], bio: ["ENABLE_AUTHOR_INFO"], biography: ["ENABLE_AUTHOR_INFO"], avatar: ["ENABLE_AUTHOR_INFO"],
    privacy: ["ALLOW_USER_DISABLE_STATISTIC"], "opt out": ["ALLOW_USER_DISABLE_STATISTIC"], telemetry: ["ALLOW_USER_DISABLE_STATISTIC"], tracking: ["ALLOW_USER_DISABLE_STATISTIC"],
    notes: ["ENABLE_SHARED_NOTES"], highlight: ["ENABLE_SHARED_NOTES"], highlights: ["ENABLE_SHARED_NOTES"], annotation: ["ENABLE_SHARED_NOTES"], annotations: ["ENABLE_SHARED_NOTES"], underline: ["ENABLE_SHARED_NOTES"],
    // Reading & Content · dictionaries
    dictionary: ["READER_MYDICTS", "READER_DICT_MYBOOKS_ENABLED", "READER_DICT_BAIKE_ENABLED"], dictionaries: ["READER_MYDICTS", "READER_DICT_MYBOOKS_ENABLED", "READER_DICT_BAIKE_ENABLED"], dict: ["READER_MYDICTS", "READER_DICT_MYBOOKS_ENABLED", "READER_DICT_BAIKE_ENABLED"],
    translate: ["READER_MYDICTS", "READER_DICT_MYBOOKS_ENABLED", "READER_DICT_BAIKE_ENABLED"], translation: ["READER_MYDICTS", "READER_DICT_MYBOOKS_ENABLED", "READER_DICT_BAIKE_ENABLED"], vocabulary: ["READER_MYDICTS"], "word lookup": ["READER_MYDICTS"], lookup: ["READER_MYDICTS"],
    encyclopedia: ["READER_DICT_BAIKE_ENABLED"], baike: ["READER_DICT_BAIKE_ENABLED"], baidu: ["READER_DICT_BAIKE_ENABLED"], wiki: ["READER_DICT_BAIKE_ENABLED"],
    // Reading & Content · reviews
    review: ["ENABLE_BOOK_REVIEW", "REVIEW_REQUIRES_APPROVAL", "ENABLE_BOOK_RECOMMEND_TO_OTHERS"], reviews: ["ENABLE_BOOK_REVIEW", "REVIEW_REQUIRES_APPROVAL"], rating: ["ENABLE_BOOK_REVIEW"], rate: ["ENABLE_BOOK_REVIEW"], comment: ["ENABLE_BOOK_REVIEW"], comments: ["ENABLE_BOOK_REVIEW"], stars: ["ENABLE_BOOK_REVIEW"],
    approve: ["REVIEW_REQUIRES_APPROVAL", "ENABLE_AUTO_NEW_USER_APPROVAL"], moderate: ["REVIEW_REQUIRES_APPROVAL"], moderation: ["REVIEW_REQUIRES_APPROVAL"],
    // Reading & Content · physical books & stamp
    folder: ["ENABLE_FOLDER_BROWSE"], folders: ["ENABLE_FOLDER_BROWSE"], directory: ["ENABLE_FOLDER_BROWSE", "scan_upload_path"], hierarchy: ["ENABLE_FOLDER_BROWSE"], "multi-level": ["ENABLE_FOLDER_BROWSE"],
    stamp: ["ENABLE_STAMP_FEATURE"], seal: ["ENABLE_STAMP_FEATURE"],
    // Users & Access · access permissions
    guest: ["ALLOW_GUEST_READ", "ALLOW_GUEST_DOWNLOAD", "ALLOW_GUEST_UPLOAD", "ALLOW_GUEST_PUSH", "ENABLE_SHARE_LINK"], guests: ["ALLOW_GUEST_READ", "ALLOW_GUEST_DOWNLOAD", "ALLOW_GUEST_UPLOAD", "ALLOW_GUEST_PUSH", "ENABLE_SHARE_LINK"],
    anonymous: ["ALLOW_GUEST_READ", "ALLOW_GUEST_DOWNLOAD"], "not logged in": ["ALLOW_GUEST_READ", "ALLOW_GUEST_DOWNLOAD"], "public access": ["ALLOW_GUEST_READ", "ALLOW_GUEST_DOWNLOAD", "ALLOW_GUEST_UPLOAD", "ALLOW_GUEST_PUSH", "ENABLE_SHARE_LINK"],
    "read online": ["ALLOW_GUEST_READ"], browse: ["ALLOW_GUEST_READ"], download: ["ALLOW_GUEST_DOWNLOAD", "ENABLE_DOWNLOAD_QUOTA", "GLOBAL_DOWNLOAD_QUOTA"], downloads: ["ALLOW_GUEST_DOWNLOAD"], upload: ["ALLOW_GUEST_UPLOAD", "MAX_UPLOAD_SIZE", "CHUNK_UPLOAD_SIZE"], push: ["ALLOW_GUEST_PUSH", "DEVICES", "push_title", "push_content", "SEND_MAIL_FOR_NEW_BOOKS"],
    share: ["ENABLE_SHARE_LINK", "ENABLE_SHARED_NOTES"], "share links": ["ENABLE_SHARE_LINK"], "public link": ["ENABLE_SHARE_LINK"], "read by link": ["ENABLE_SHARE_LINK"],
    // Users & Access · registration & invitation
    register: ["ALLOW_REGISTER", "SIGNUP_MAIL_TITLE", "ENABLE_AUTO_NEW_USER_APPROVAL"], registration: ["ALLOW_REGISTER"], signup: ["ALLOW_REGISTER"], "sign up": ["ALLOW_REGISTER"], "create account": ["ALLOW_REGISTER"],
    invite: ["INVITE_MODE", "INVITE_CODE"], invitation: ["INVITE_MODE", "INVITE_CODE"], "invite code": ["INVITE_CODE", "INVITE_MODE"], "access code": ["INVITE_CODE", "INVITE_MODE"], "private library": ["INVITE_MODE"], "private mode": ["INVITE_MODE"], passcode: ["INVITE_MODE", "INVITE_CODE"], closed: ["INVITE_MODE"],
    "invite message": ["INVITE_MESSAGE"], "welcome message": ["INVITE_MESSAGE"],
    activation: ["SIGNUP_MAIL_TITLE", "SIGNUP_MAIL_CONTENT"], "activation email": ["SIGNUP_MAIL_TITLE", "SIGNUP_MAIL_CONTENT"], "verify email": ["SIGNUP_MAIL_TITLE", "SIGNUP_MAIL_CONTENT"], confirmation: ["SIGNUP_MAIL_TITLE", "SIGNUP_MAIL_CONTENT"],
    "reset password": ["RESET_MAIL_TITLE", "RESET_MAIL_CONTENT"], "forgot password": ["RESET_MAIL_TITLE", "RESET_MAIL_CONTENT"], "password reset": ["RESET_MAIL_TITLE", "RESET_MAIL_CONTENT"],
    body: ["push_content", "RESET_MAIL_CONTENT", "SIGNUP_MAIL_CONTENT"], content: ["push_content", "RESET_MAIL_CONTENT", "SIGNUP_MAIL_CONTENT", "INVITE_MESSAGE"],
    // Users & Access · default permissions & quota
    approval: ["ENABLE_AUTO_NEW_USER_APPROVAL", "REVIEW_REQUIRES_APPROVAL"], "auto approve": ["ENABLE_AUTO_NEW_USER_APPROVAL"],
    "new user": ["ALLOW_NEW_USER_MANAGE_BOOK", "ALLOW_NEW_USER_PUSH_BOOK", "ENABLE_AUTO_NEW_USER_APPROVAL", "DEFAULT_READ_RANGE"], "new users": ["ALLOW_NEW_USER_MANAGE_BOOK", "ALLOW_NEW_USER_PUSH_BOOK", "ENABLE_AUTO_NEW_USER_APPROVAL"],
    permission: ["ALLOW_NEW_USER_MANAGE_BOOK", "ALLOW_NEW_USER_PUSH_BOOK", "ALLOW_READ_RANGE_SETTING"], permissions: ["ALLOW_NEW_USER_MANAGE_BOOK", "ALLOW_NEW_USER_PUSH_BOOK", "ALLOW_READ_RANGE_SETTING"],
    whitelist: ["ALLOW_READ_RANGE_SETTING", "DEFAULT_READ_RANGE"], blacklist: ["ALLOW_READ_RANGE_SETTING", "DEFAULT_READ_RANGE"], visible: ["ALLOW_READ_RANGE_SETTING", "DEFAULT_READ_RANGE"], hidden: ["ALLOW_READ_RANGE_SETTING", "DEFAULT_READ_RANGE"], restrict: ["ALLOW_READ_RANGE_SETTING", "DEFAULT_READ_RANGE"],
    "read range": ["ALLOW_READ_RANGE_SETTING", "DEFAULT_READ_RANGE"], "reading range": ["ALLOW_READ_RANGE_SETTING", "DEFAULT_READ_RANGE"],
    quota: ["ENABLE_DOWNLOAD_QUOTA", "GLOBAL_DOWNLOAD_QUOTA"], quotas: ["ENABLE_DOWNLOAD_QUOTA", "GLOBAL_DOWNLOAD_QUOTA"], "daily limit": ["ENABLE_DOWNLOAD_QUOTA", "GLOBAL_DOWNLOAD_QUOTA"], "download limit": ["ENABLE_DOWNLOAD_QUOTA", "GLOBAL_DOWNLOAD_QUOTA"],
    // Users & Access · social login
    login: ["SOCIALS", "ALLOW_REGISTER", "INVITE_MODE", "REQUIRE_LOGIN"], social: ["SOCIALS"], "social login": ["SOCIALS"], oauth: ["SOCIALS"], "third party": ["SOCIALS"], sso: ["SOCIALS"], qq: ["SOCIALS"], wechat: ["SOCIALS"], weibo: ["SOCIALS"], github: ["SOCIALS"],
    // Import & Storage · upload
    "upload limit": ["MAX_UPLOAD_SIZE", "CHUNK_UPLOAD_SIZE"], "file size": ["MAX_UPLOAD_SIZE"], "max upload": ["MAX_UPLOAD_SIZE"], size: ["MAX_UPLOAD_SIZE", "CACHE_MAX_MB"], limit: ["MAX_UPLOAD_SIZE", "CHUNK_UPLOAD_SIZE", "ENABLE_DOWNLOAD_QUOTA", "GLOBAL_DOWNLOAD_QUOTA", "CACHE_MAX_MB"],
    chunk: ["CHUNK_UPLOAD_SIZE"], chunks: ["CHUNK_UPLOAD_SIZE"], "chunked upload": ["CHUNK_UPLOAD_SIZE"], "large file": ["CHUNK_UPLOAD_SIZE"], resume: ["CHUNK_UPLOAD_SIZE"],
    scan: ["scan_upload_path", "PDF_TILE_WITH_FILE_NAME"], batch: ["scan_upload_path", "BATCH_ADD_IN_FORCE"], "scan directory": ["scan_upload_path"], "import directory": ["scan_upload_path"], "batch import": ["scan_upload_path"],
    metadata: ["auto_fill_meta", "META_SELECTED_SOURCES", "DEFAULT_LANGUAGE"], "book info": ["auto_fill_meta", "META_SELECTED_SOURCES"], "source file": ["KEEP_UPLOAD_SOURCE_FILE", "REMOVE_IMPORTED_FILE"], "keep source": ["KEEP_UPLOAD_SOURCE_FILE"], "temp file": ["KEEP_UPLOAD_SOURCE_FILE"], staged: ["KEEP_UPLOAD_SOURCE_FILE"],
    "delete source": ["REMOVE_IMPORTED_FILE"], "remove original": ["REMOVE_IMPORTED_FILE"],
    // Import & Storage · import rules
    pdf: ["PDF_TILE_WITH_FILE_NAME"], filename: ["PDF_TILE_WITH_FILE_NAME", "BOOK_NAMES_FORMAT"], "file name": ["PDF_TILE_WITH_FILE_NAME", "BOOK_NAMES_FORMAT"],
    txt: ["ENABLE_TXT_TO_TXTZ_PLUGIN"], txtz: ["ENABLE_TXT_TO_TXTZ_PLUGIN"], server: ["ENABLE_SERVER_FILE_IMPORT"], "bind directory": ["ENABLE_SERVER_FILE_IMPORT"], "browse server": ["ENABLE_SERVER_FILE_IMPORT"],
    isbn: ["BATCH_ADD_IN_FORCE"], force: ["BATCH_ADD_IN_FORCE"], invalid: ["BATCH_ADD_IN_FORCE"],
    "top folder": ["IMPORT_CATEGORY_WITH_FOLDER"], "first level folder": ["IMPORT_CATEGORY_WITH_FOLDER"], "custom category": ["IMPORT_CATEGORY_WITH_FOLDER"], "folder category": ["IMPORT_CATEGORY_WITH_FOLDER"],
    throttle: ["auto_fill_pause_on_throttle", "ENABLE_DOWNLOAD_QUOTA"], "rate limit": ["auto_fill_pause_on_throttle", "ENABLE_DOWNLOAD_QUOTA"], cooldown: ["auto_fill_pause_on_throttle"], pause: ["auto_fill_pause_on_throttle"],
    duplicate: ["UPLOAD_IGNORE_TITLE_CHECKING"], duplicated: ["UPLOAD_IGNORE_TITLE_CHECKING"], duplicates: ["UPLOAD_IGNORE_TITLE_CHECKING"], "same book": ["UPLOAD_IGNORE_TITLE_CHECKING"], "title check": ["UPLOAD_IGNORE_TITLE_CHECKING"],
    // Import & Storage · auto import & storage layout
    "auto import": ["IMPORT_BY_INOTIFY"], watch: ["IMPORT_BY_INOTIFY"], monitor: ["IMPORT_BY_INOTIFY"], monitoring: ["IMPORT_BY_INOTIFY"], inotify: ["IMPORT_BY_INOTIFY"], realtime: ["IMPORT_BY_INOTIFY"],
    rename: ["UPDATE_CATEGORY_WITH_FOLDER_RENAME"], "folder rename": ["UPDATE_CATEGORY_WITH_FOLDER_RENAME"], "move folder": ["UPDATE_CATEGORY_WITH_FOLDER_RENAME"],
    storage: ["BOOK_NAMES_FORMAT", "TRASH"], layout: ["BOOK_NAMES_FORMAT"], pinyin: ["BOOK_NAMES_FORMAT"], utf8: ["BOOK_NAMES_FORMAT"], encoding: ["BOOK_NAMES_FORMAT"], "file naming": ["BOOK_NAMES_FORMAT"],
    // Push & Email · smtp
    smtp: ["smtp_server", "smtp_username", "smtp_password", "smtp_encryption"], "mail server": ["smtp_server"], sender: ["smtp_server", "smtp_username"], username: ["smtp_username"], account: ["smtp_username"],
    password: ["smtp_password", "cookie_secret", "INVITE_CODE", "AI_DEEPSEEK_API_KEY", "BOOKBARN_TOKEN", "RESET_MAIL_TITLE"], "app password": ["smtp_password"], "auth code": ["smtp_password"],
    encryption: ["smtp_encryption"], ssl: ["smtp_encryption", "SSL"], tls: ["smtp_encryption"], port: ["smtp_server", "smtp_encryption"],
    email: ["smtp_server", "smtp_username", "smtp_password", "smtp_encryption", "push_title", "push_content", "SEND_MAIL_FOR_NEW_BOOKS", "SIGNUP_MAIL_TITLE", "SIGNUP_MAIL_CONTENT", "RESET_MAIL_TITLE", "RESET_MAIL_CONTENT"], mail: ["smtp_server", "smtp_username", "smtp_password", "push_title", "SEND_MAIL_FOR_NEW_BOOKS"],
    kindle: ["DEVICES", "push_title", "smtp_server"], reminder: ["SEND_MAIL_FOR_NEW_BOOKS"], notify: ["SEND_MAIL_FOR_NEW_BOOKS"], notification: ["SEND_MAIL_FOR_NEW_BOOKS", "push_title"],
    // Push & Email · devices
    device: ["DEVICES"], devices: ["DEVICES"], ereader: ["DEVICES"], "e-reader": ["DEVICES"], boox: ["DEVICES"], koreader: ["DEVICES"], duokan: ["DEVICES"], ireader: ["DEVICES"], hanwang: ["DEVICES"], dangdang: ["DEVICES"], purelibro: ["DEVICES"], ftp: ["DEVICES"],
    // External Services · book info sources
    source: ["META_SELECTED_SOURCES", "auto_fill_meta"], sources: ["META_SELECTED_SOURCES", "auto_fill_meta"], scrape: ["auto_fill_meta", "META_SELECTED_SOURCES"], scraping: ["auto_fill_meta", "META_SELECTED_SOURCES"], douban: ["auto_fill_meta", "META_SELECTED_SOURCES", "douban_baseurl", "douban_apikey", "douban_max_count", "douban_v2_max_per_hour"], mirror: ["douban_baseurl"],
    frequency: ["auto_fill_qpm"], "per minute": ["auto_fill_qpm"], qpm: ["auto_fill_qpm"], pace: ["auto_fill_qpm"],
    "per hour": ["douban_v2_max_per_hour"], hourly: ["douban_v2_max_per_hour"], "hourly limit": ["douban_v2_max_per_hour"],
    api: ["AI_API_URL", "AI_DEEPSEEK_API_KEY", "douban_apikey", "douban_baseurl"], "api key": ["douban_apikey", "AI_DEEPSEEK_API_KEY", "AI_MCP_TOKEN", "BOOKBARN_TOKEN"], key: ["douban_apikey", "AI_DEEPSEEK_API_KEY", "cookie_secret", "AI_MCP_TOKEN", "BOOKBARN_TOKEN"], count: ["douban_max_count", "MAIN_PAGE_RANDOM_COUNT", "MAIN_PAGE_RECENT_COUNT"], results: ["douban_max_count"],
    // External Services · bookbarn & AI
    bookbarn: ["ENABLE_BOOKBARN", "BOOKBARN_TOKEN"], token: ["BOOKBARN_TOKEN", "AI_MCP_TOKEN"], "auth token": ["BOOKBARN_TOKEN", "AI_MCP_TOKEN"],
    ai: ["AI_ENABLED", "AI_DEEPSEEK_API_KEY", "AI_API_URL", "AI_MODEL", "AI_MCP_TOKEN", "AI_ALLOW_SET_CATEGORY"], assistant: ["AI_ENABLED"], "artificial intelligence": ["AI_ENABLED"], deepseek: ["AI_ENABLED", "AI_DEEPSEEK_API_KEY", "AI_MODEL"], model: ["AI_MODEL"], mcp: ["AI_MCP_TOKEN"], "auto category": ["AI_ALLOW_SET_CATEGORY"], generate: ["AI_ALLOW_SET_CATEGORY"],
    // Services & Protocols
    webdav: ["ENABLE_WEBDAV_SERVICE", "WEBDAV_SYNC_FOLDER"], mount: ["ENABLE_WEBDAV_SERVICE"], writable: ["WEBDAV_SYNC_FOLDER"], "read write": ["ENABLE_WEBDAV_SERVICE", "WEBDAV_SYNC_FOLDER"],
    opds: ["ENABLE_OPDS_SERVICE", "ENABLE_OPDS_AUTH"], auth: ["ENABLE_OPDS_AUTH"], authentication: ["ENABLE_OPDS_AUTH"], catalog: ["ENABLE_OPDS_SERVICE", "ENABLE_OPDS_AUTH"],
    podcast: ["ENABLE_PODCAST_SERVICE"], podcasts: ["ENABLE_PODCAST_SERVICE"], subscribe: ["ENABLE_PODCAST_SERVICE", "ENABLE_OPDS_SERVICE"], subscription: ["ENABLE_PODCAST_SERVICE", "ENABLE_OPDS_SERVICE"], audiobook: ["ENABLE_PODCAST_SERVICE", "ENABLE_AUDIO_CONVERSION_LOG", "ENABLE_AUDIO_SUBTITLE"], audiobooks: ["ENABLE_PODCAST_SERVICE", "ENABLE_AUDIO_CONVERSION_LOG", "ENABLE_AUDIO_SUBTITLE"],
    cdn: ["static_host"], domain: ["static_host"], acceleration: ["static_host", "PERFORMANCE_MODE"], "static assets": ["static_host"], "static host": ["static_host"],
    cookie: ["cookie_secret"], secret: ["cookie_secret", "AI_MCP_TOKEN", "BOOKBARN_TOKEN"], security: ["cookie_secret", "INVITE_MODE", "ENABLE_OPDS_AUTH", "SSL"], certificate: ["SSL", "static_host"], cert: ["SSL", "static_host"], https: ["SSL", "static_host"],
    // System & Performance · performance & cache
    lite: ["PERFORMANCE_MODE"], performance: ["PERFORMANCE_MODE", "THUMB_CACHE"], "low-end": ["PERFORMANCE_MODE"], "low spec": ["PERFORMANCE_MODE"], slow: ["PERFORMANCE_MODE", "THUMB_CACHE"], speed: ["PERFORMANCE_MODE"], lag: ["PERFORMANCE_MODE", "THUMB_CACHE"], laggy: ["PERFORMANCE_MODE", "THUMB_CACHE"],
    cache: ["THUMB_CACHE", "CACHE_MAX_MB"], thumbnail: ["THUMB_CACHE"], thumbnails: ["THUMB_CACHE"], thumbs: ["THUMB_CACHE"], "cache size": ["CACHE_MAX_MB"], mb: ["CACHE_MAX_MB"],
    memory: ["LITE_GROUP_RESOURCES"], ram: ["LITE_GROUP_RESOURCES"], cpu: ["LITE_GROUP_RESOURCES", "PERFORMANCE_MODE"], resources: ["LITE_GROUP_RESOURCES"], "save resources": ["LITE_GROUP_RESOURCES"],
    simplify: ["LITE_GROUP_RECOMMEND", "LITE_GROUP_FILES", "LITE_GROUP_BACKGROUND"], lighter: ["LITE_GROUP_RECOMMEND", "LITE_GROUP_FILES", "LITE_GROUP_BACKGROUND", "LITE_GROUP_RESOURCES"], background: ["LITE_GROUP_BACKGROUND"], "background tasks": ["LITE_GROUP_BACKGROUND"],
    "faster search": ["LITE_GROUP_LISTING"], "list speed": ["LITE_GROUP_LISTING"], "image processing": ["LITE_GROUP_FILES"], "image handling": ["LITE_GROUP_FILES"],
    // System & Performance · logs & debug
    log: ["LOG_LEVEL_DEBUG", "ENABLE_AUDIO_CONVERSION_LOG"], logs: ["LOG_LEVEL_DEBUG", "ENABLE_AUDIO_CONVERSION_LOG"], logging: ["LOG_LEVEL_DEBUG", "ENABLE_AUDIO_CONVERSION_LOG"], debug: ["LOG_LEVEL_DEBUG"], debugging: ["LOG_LEVEL_DEBUG"], troubleshoot: ["LOG_LEVEL_DEBUG"],
    subtitle: ["ENABLE_AUDIO_SUBTITLE"], subtitles: ["ENABLE_AUDIO_SUBTITLE"], srt: ["ENABLE_AUDIO_SUBTITLE"],
    restart: ["autoreload"], reboot: ["autoreload"], reload: ["autoreload"], "take effect": ["autoreload"], timeout: ["convert_timeout"], "conversion timeout": ["convert_timeout"],
    // System & Performance · updates & toolbox
    update: ["AUTO_CHECKING_NEW_VERSION", "ENABLE_TOOLBOX_STORE"], updates: ["AUTO_CHECKING_NEW_VERSION", "ENABLE_TOOLBOX_STORE", "MAIN_PAGE_RECENT_COUNT"], version: ["AUTO_CHECKING_NEW_VERSION"], upgrade: ["AUTO_CHECKING_NEW_VERSION"], "check update": ["AUTO_CHECKING_NEW_VERSION"],
    toolbox: ["ENABLE_TOOLBOX_DEV_MODE", "ENABLE_TOOLBOX_STORE"], tools: ["ENABLE_TOOLBOX_DEV_MODE", "ENABLE_TOOLBOX_STORE"], developer: ["ENABLE_TOOLBOX_DEV_MODE"], "dev mode": ["ENABLE_TOOLBOX_DEV_MODE"], store: ["ENABLE_TOOLBOX_STORE"], marketplace: ["ENABLE_TOOLBOX_STORE"], plugin: ["ENABLE_TOOLBOX_STORE", "ENABLE_TXT_TO_TXTZ_PLUGIN"], plugins: ["ENABLE_TOOLBOX_STORE", "ENABLE_TXT_TO_TXTZ_PLUGIN"], extension: ["ENABLE_TOOLBOX_STORE"], zip: ["ENABLE_TOOLBOX_DEV_MODE"],
    // System & Performance · cleanup
    "recycle bin": ["TRASH"], trash: ["TRASH"], "trash bin": ["TRASH"], cleanup: ["TRASH", "REMOVE_IMPORTED_FILE"], "clean up": ["TRASH", "REMOVE_IMPORTED_FILE"], disk: ["TRASH"], space: ["TRASH", "CACHE_MAX_MB"], delete: ["TRASH", "REMOVE_IMPORTED_FILE"],
  },
};

// 三层词典合并成一张查找表：同名词条按并集合并（zh 的「登录」与 en 的 "login" 互不覆盖）；
// 多词词条（"recycle bin"）额外登记每个 ≥3 字母的单字，因为查询串是按空格切词的
const ALIAS_LOOKUP = Object.keys(SEARCH_ALIASES).reduce((lookup, lang) => {
  const layer = SEARCH_ALIASES[lang];
  const add = (word, keys) => {
    const list = lookup[word] || (lookup[word] = []);
    keys.forEach((key) => {
      if (list.indexOf(key) < 0) list.push(key);
    });
  };
  Object.keys(layer).forEach((word) => {
    add(word, layer[word]);
    if (/\s/.test(word)) {
      word.split(/\s+/).forEach((piece) => {
        if (piece.length >= 3) add(piece, layer[word]);
      });
    }
  });
  return lookup;
}, {});

const HAS_CJK = /[\u3400-\u9fff]/;
// 命中分数：整词命中词典时，词条列表里排第一的关键项 82、其余 80（词条顺序即相关度）；
// 中文组合词按命中的词条数累加（74 起，每词条 +2），封顶 79——始终排在整词命中之后
const ALIAS_SCORE_EXACT = 82;
const ALIAS_SCORE_SECOND = 80;
const ALIAS_SCORE_PARTIAL = 74;
const ALIAS_SCORE_PARTIAL_STEP = 2;
const ALIAS_SCORE_PARTIAL_MAX = 79;

// 单个查询词命中的设置项 key → 分数
function aliasScoresFor(token) {
  const scores = {};
  const exact = ALIAS_LOOKUP[token];
  if (exact) {
    exact.forEach((key, i) => {
      scores[key] = i === 0 ? ALIAS_SCORE_EXACT : ALIAS_SCORE_SECOND;
    });
  }
  // 含中文的查询词再走一遍子串匹配（拉丁词条只按整词，避免 "catalog" 命中 "log"）
  if (token.length < 2 || !HAS_CJK.test(token)) return scores;
  Object.keys(ALIAS_LOOKUP).forEach((word) => {
    if (word === token || word.length < 2) return;
    if (token.indexOf(word) < 0 && word.indexOf(token) < 0) return;
    ALIAS_LOOKUP[word].forEach((key) => {
      const partial = Math.min(ALIAS_SCORE_PARTIAL_MAX, (scores[key] || ALIAS_SCORE_PARTIAL) + ALIAS_SCORE_PARTIAL_STEP);
      scores[key] = Math.max(scores[key] || 0, partial);
    });
  });
  return scores;
}

export default {
  components: {
    "ssl-manager": SSLManager,
    "reading-range-dialog": ReadingRangeDialog,
    "book-nav-editor": BookNavEditor,
    "reader-dict-editor": ReaderDictEditor,
    "homepage-cards-editor": HomepageCardsEditor,
  },
  created() {
    // 为body添加settings-page类名，应用背景图样式
    if (process.client) {
      document.body.classList.add("settings-page");
    }

    // 初始化设备类型选项
    this.deviceTypes = [
      { text: this.$t("settings.device_type_duokan"), value: "duokan" },
      { text: this.$t("settings.device_type_ireader"), value: "ireader" },
      { text: this.$t("settings.device_type_hanwang"), value: "hanwang" },
      { text: this.$t("settings.device_type_boox"), value: "boox" },
      { text: this.$t("settings.device_type_koreader"), value: "koreader" },
      { text: this.$t("settings.device_type_dangdang"), value: "dangdang" },
      { text: "Kindle", value: "kindle" },
      { text: "PureLibro", value: "purelibro" },
      { text: this.$t("settings.device_type_ftp"), value: "ftp" },
    ];

    // al = 搜索别名，供搜索匹配用
    this.groups = [
      {
        id: "site",
        icon: "mdi-web",
        title: "settings.group_site",
        sections: [
          {
            id: "site-id",
            icon: "mdi-home",
            title: "settings.sec_site_id",
            fields: [
              { icon: "mdi-home", key: "site_title", label: "settings.site_title" },
              {
                icon: "mdi-link-variant",
                key: "SITE_URL",
                label: "settings.site_default_url",
              },
              {
                icon: "mdi-information",
                key: "site_icon",
                label: "settings.site_icon",
                type: "select_image",
                items: Array.from({ length: 9 }, (_, i) => ({
                  image_file: "favicon_" + i.toString(),
                  value: "favicon_" + i.toString(),
                  // favicon_0 表示「沿用当前图标」：预览读取站点当前的 favicon.ico，
                  // 而不是自带的默认 favicon_0.ico（后者不会随选择更新）
                  is_current: i === 0,
                })),
              },
              { icon: "mdi-copyright", key: "HEADER", label: "settings.site_header", type: "textarea" },
              { icon: "mdi-copyright", key: "FOOTER", label: "settings.site_footer", type: "textarea" },
              { icon: "mdi-closed-caption-outline", key: "FOOTER_WATERMARK", label: "settings.footer_watermark" },
              {
                icon: "mdi-web",
                key: "site_language",
                label: "settings.language_switch",
                type: "select",
                al: ["中文", "english", "繁體"],
                items: [
                  { text: this.$t('language.zh'), value: "zh" },
                  { text: this.$t('language.zh_TW'), value: "zh-TW" },
                  { text: this.$t('language.en'), value: "en" },
                ],
              },
              {
                icon: "mdi-clock-outline",
                key: "site_timezone",
                label: "settings.site_timezone",
                type: "select",
                items: [
                  { text: this.$t("settings.tz_auto"), value: "auto" },
                  { text: this.$t("settings.tz_utc"), value: "UTC" },
                  { text: this.$t("settings.tz_shanghai"), value: "Asia/Shanghai" },
                  { text: this.$t("settings.tz_hongkong"), value: "Asia/Hong_Kong" },
                  { text: this.$t("settings.tz_taipei"), value: "Asia/Taipei" },
                  { text: this.$t("settings.tz_tokyo"), value: "Asia/Tokyo" },
                  { text: this.$t("settings.tz_seoul"), value: "Asia/Seoul" },
                  { text: this.$t("settings.tz_bangkok"), value: "Asia/Bangkok" },
                  { text: this.$t("settings.tz_kolkata"), value: "Asia/Kolkata" },
                  { text: this.$t("settings.tz_berlin"), value: "Europe/Berlin" },
                  { text: this.$t("settings.tz_london"), value: "Europe/London" },
                  { text: this.$t("settings.tz_saopaulo"), value: "America/Sao_Paulo" },
                  { text: this.$t("settings.tz_newyork"), value: "America/New_York" },
                  { text: this.$t("settings.tz_losangeles"), value: "America/Los_Angeles" },
                  { text: this.$t("settings.tz_sydney"), value: "Australia/Sydney" },
                ],
              },
              {
                icon: "mdi-home",
                key: "INDEX_PAGE_TYPE",
                label: "settings.index_page_type",
                type: "select",
                items: [
                  {
                    text: this.$t("settings.index_page_type_index"),
                    value: "index",
                  },
                  { text: this.$t("settings.index_page_type_all"), value: "all" },
                  {
                    text: this.$t("settings.index_page_type_categories"),
                    value: "categories",
                  },
                ],
              },
              {
                icon: "mdi-star-off-outline",
                key: "HIDE_PROJECT_LINKS",
                label: "settings.hide_project_link_in_footer",
                type: "checkbox",
              },
            ],
          },
          {
            id: "site-home",
            icon: "mdi-view-dashboard-outline",
            title: "settings.sec_site_home",
            fields: [
              {
                icon: "mdi-shuffle",
                key: "MAIN_PAGE_RANDOM_COUNT",
                label: "settings.main_page_random_count",
                type: "select",
                items: [0, 12, 24, 48, 96, 192, 768].map((v) => ({
                  text: String(v),
                  value: v,
                })),
              },
              {
                icon: "mdi-book-multiple",
                key: "MAIN_PAGE_RECENT_COUNT",
                label: "settings.main_page_recent_count",
                type: "select",
                items: [12, 24, 48, 96, 192].map((v) => ({
                  text: String(v),
                  value: v,
                })),
              },
              { icon: "mdi-auto-fix", key: "RECOMMEND_ENABLE", label: "settings.recommend_enable", type: "checkbox" },
              { icon: "mdi-account-group-outline", key: "RECOMMEND_USE_CROWD", label: "settings.recommend_use_crowd", type: "checkbox" },
              {
                icon: "mdi-animation",
                key: "ENABLE_HOME_MOTION",
                label: "settings.home_motion",
                type: "checkbox",
                tips: "settings.home_motion_tips",
              },
              {
                icon: "mdi-book-multiple",
                key: "DEFAULT_PAGE_SIZE",
                label: "settings.default_page_size",
                type: "select",
                items: [60, 100, 200, 500, 1000].map((v) => ({
                  text: String(v),
                  value: v,
                })),
              },
              {
                icon: "mdi-message-text-outline",
                key: "ENABLE_USER_MEMOS",
                label: "settings.enable_user_memos",
                type: "checkbox",
                tips: "settings.enable_user_memos_tips",
              },
              {
                icon: "mdi-bookshelf",
                key: "ENABLE_PHYSICAL_BOOKS",
                label: "settings.enable_physical_books",
                type: "checkbox",
                tips: "settings.enable_physical_books_tips",
                fields: [
                  {
                    icon: "mdi-swap-horizontal",
                    key: "ENABLE_BOOKS_TYPE_CONVERT_DIRECT",
                    label: "settings.enable_book_type_convert_directly",
                    type: "checkbox",
                  }
                ]
              },
              {
                icon: "mdi-page-layout-sidebar-left",
                key: "SIDEBAR_ITEMS",
                label: "settings.sidebar_items",
                type: "checkbox_list",
                tips: "settings.sidebar_items_tips",
                // 全不勾选时写入 "none"：空数组表示「全部显示」，无法表达「全部隐藏」
                emptyValue: "none",
                items: [
                  { value: "audiobooks", text: "appHeader.audioBooks" },
                  { value: "authors", text: "appHeader.authors" },
                  { value: "publishers", text: "appHeader.publishers" },
                  { value: "folders", text: "appHeader.folders", requires: "ENABLE_FOLDER_BROWSE" },
                  { value: "categories", text: "nav.categories" },
                  { value: "tags", text: "appHeader.tags" },
                  { value: "series", text: "appHeader.series" },
                  { value: "languages", text: "appHeader.languages" },
                  { value: "rating", text: "appHeader.rating" },
                  { value: "booklists", text: "appHeader.booklists" },
                  { value: "friends", text: "appHeader.friendLinks" },
                ],
              },
            ],
          },
          {
            id: "site-home-cards",
            icon: "mdi-view-grid-plus-outline",
            title: "settings.sec_site_home_cards",
            desc: "settings.sec_site_home_cards_desc",
            special: "homepage_cards",
          },
          {
            id: "site-friends",
            icon: "mdi-link-variant",
            title: "settings.friend_links",
            special: "friends",
          },
        ],
      },
      {
        id: "reading",
        icon: "mdi-book-open-page-variant",
        title: "settings.group_reading",
        sections: [
          {
            id: "reader-core",
            icon: "mdi-book-open",
            title: "settings.sec_reader_core",
            fields: [
              {
                icon: "mdi-book-open",
                key: "EPUB_VIEWER",
                label: "settings.epub_viewer",
                type: "select",
                items: [
                  { text: this.$t("settings.epubjs"), value: "epubjs.html", icon: "mdi-alpha-e-circle-outline" },
                  { text: this.$t("settings.myreader"), value: "MyReader", icon: "mdi-water-outline" }
                ],
              },
              { icon: "mdi-sync", key: "ENABLE_DATA_SYNC", label: "settings.enable_data_sync", type: "checkbox" },
              { icon: "mdi-image-sync-outline", key: "USE_DYNAMIC_COVER", label: "settings.use_dynamic_cover", type: "checkbox" },
              { icon: "mdi-face-man-outline", key: "ENABLE_AUTHOR_INFO", label: "settings.enable_author_info", type: "checkbox" },
              { icon: "mdi-chart-line", key: "ALLOW_USER_DISABLE_STATISTIC", label: "settings.allow_user_disable_statistic", type: "checkbox" },
              { icon: "mdi-note-multiple-outline", key: "ENABLE_SHARED_NOTES", label: "settings.enable_shared_notes", type: "checkbox" },
            ],
          },
          {
            id: "site-cats",
            icon: "mdi-tag-outline",
            title: "settings.book_tags",
            desc: "settings.book_tags_description",
            fields: [
              { icon: "mdi-tag-outline", key: "BOOK_NAV", type: "book_nav", label: "settings.book_nav", al: ["书单", "分类", "导航"] },
            ],
          },
          {
            id: "reader-review",
            icon: "mdi-forum-outline",
            title: "settings.sec_reader_review",
            fields: [
              { icon: "mdi-star-outline", key: "ENABLE_BOOK_REVIEW", label: "settings.enable_book_review", type: "checkbox" },
              { icon: "mdi-shield-check-outline", key: "REVIEW_REQUIRES_APPROVAL", label: "settings.review_requires_approval", type: "checkbox" },
              { icon: "mdi-thumb-up-outline", key: "ENABLE_BOOK_RECOMMEND_TO_OTHERS", label: "settings.enable_book_recommend_to_others", type: "checkbox" },
            ],
          },
          {
            id: "reader-extended",
            icon: "mdi-bookshelf",
            title: "settings.sec_reader_extended",
            groups: [
              {
                icon: "mdi-folder-multiple-outline",
                key: "ENABLE_FOLDER_BROWSE",
                label: "settings.enable_folder_browse",
                type: "checkbox",
              },
            ],
            special: "stamp",
          },
          {
            id: "reader-dict",
            icon: "mdi-book-alphabet",
            title: "settings.sec_reader_dict",
            special: "reader_dicts",
          },
        ],
      },
      {
        id: "users",
        icon: "mdi-account-group-outline",
        title: "settings.group_users",
        sections: [
          {
            id: "users-guest",
            icon: "mdi-account",
            title: "settings.sec_users_guest",
            fields: [
              // 私人图书馆标准模式：开启后所有页面与接口都要求登录，下面各项访问权限随之失效
              { icon: "mdi-login-variant", key: "REQUIRE_LOGIN", label: "settings.require_login", type: "checkbox", al: ["必须登录", "私人图书馆", "需登录", "login required"] },
              { icon: "mdi-read", key: "ALLOW_GUEST_READ", label: "settings.allow_guest_read", type: "checkbox", lockOn: "REQUIRE_LOGIN" },
              { icon: "mdi-download", key: "ALLOW_GUEST_DOWNLOAD", label: "settings.allow_guest_download", type: "checkbox", lockOn: "REQUIRE_LOGIN" },
              { icon: "mdi-upload", key: "ALLOW_GUEST_UPLOAD", label: "settings.allow_guest_upload", type: "checkbox", lockOn: "REQUIRE_LOGIN" },
              { icon: "mdi-send", key: "ALLOW_GUEST_PUSH", label: "settings.allow_guest_push", type: "checkbox", lockOn: "REQUIRE_LOGIN" },
              { icon: "mdi-link-variant", key: "ENABLE_SHARE_LINK", label: "settings.allow_share_link", type: "checkbox" },
            ],
          },
          {
            id: "users-reg",
            icon: "mdi-at",
            title: "settings.sec_users_reg",
            fields: [
              { icon: "mdi-subtitles-outline", key: "reset-mail-heading", label: "settings.sec_reset_mail", type: "subtitle" },
              {
                icon: "mdi-format-title",
                key: "RESET_MAIL_TITLE",
                label: "settings.reset_mail_title",
              },
              {
                icon: "mdi-subtitles-outline",
                key: "RESET_MAIL_CONTENT",
                label: "settings.reset_mail_content",
                type: "textarea",
              },
            ],
            groups: [
              {
                icon: "mdi-security",
                key: "INVITE_MODE",
                label: "settings.private_library_mode",
                al: ["访问码", "私人"],
                fields: [
                  {
                    icon: "mdi-lock",
                    key: "INVITE_CODE",
                    label: "settings.access_code",
                  },
                  {
                    icon: "mdi-account",
                    key: "INVITE_MESSAGE",
                    type: "textarea",
                    label: "settings.invite_message",
                  },
                ],
              },
              {
                icon: "mdi-at",
                key: "ALLOW_REGISTER",
                label: "settings.allow_guest_register",
                al: ["注册"],
                fields: [
                  {
                    icon: "mdi-format-title",
                    key: "SIGNUP_MAIL_TITLE",
                    label: "settings.signup_mail_title",
                  },
                  {
                    icon: "mdi-subtitles-outline",
                    key: "SIGNUP_MAIL_CONTENT",
                    label: "settings.signup_mail_content",
                    type: "textarea",
                  },
                  {
                    icon: "mdi-account-check-outline",
                    key: "ENABLE_AUTO_NEW_USER_APPROVAL",
                    label: "settings.enable_auto_new_user_approval",
                    type: "checkbox",
                  }
                ],
              },
            ],
          },
          {
            id: "users-default",
            icon: "mdi-download-lock-outline",
            title: "settings.sec_users_default",
            fields: [
              { icon: "mdi-book-multiple", key: "ALLOW_NEW_USER_MANAGE_BOOK", label: "settings.allow_new_user_manage_book", type: "checkbox" },
              { icon: "mdi-tablet-cellphone", key: "ALLOW_NEW_USER_PUSH_BOOK", label: "settings.allow_new_user_push_book", type: "checkbox" },
            ],
            groups: [
              {
                icon: "mdi-book-lock-outline",
                key: "ALLOW_READ_RANGE_SETTING",
                label: "settings.allow_read_range_setting",
                al: ["白名单", "黑名单"],
                fields: [
                  {
                    key: "DEFAULT_READ_RANGE",
                    type: "reading_range",
                    label: "settings.default_read_range",
                  },
                ],
              },
              {
                key: "ENABLE_DOWNLOAD_QUOTA",
                icon: "mdi-download-lock-outline",
                label: "settings.enable_download_quota",
                al: ["配额", "下载"],
                fields: [
                  {
                    icon: "mdi-counter",
                    key: "GLOBAL_DOWNLOAD_QUOTA",
                    label: "settings.global_download_quota",
                    type: "number",
                  }
                ],
              },
            ],
          },
          {
            id: "users-social",
            icon: "mdi-at",
            title: "settings.social_network_login",
            desc: "settings.socials_description",
            special: "socials",
          },
        ],
      },
      {
        id: "import",
        icon: "mdi-import",
        title: "settings.group_import",
        sections: [
          {
            // 只放「把文件送进服务器」这一层：体积/分片、暂存、入库前的同书校验、实体书清单
            id: "imp-upload",
            icon: "mdi-upload",
            title: "settings.sec_imp_upload",
            fields: [
              {
                icon: "mdi-information",
                color: "red",
                key: "MAX_UPLOAD_SIZE",
                label: "settings.max_upload_size",
                al: ["上传"],
              },
              {
                icon: "mdi-information",
                key: "CHUNK_UPLOAD_SIZE",
                label: "settings.chunk_upload_size",
              },
              {
                icon: "mdi-file-lock-outline",
                key: "KEEP_UPLOAD_SOURCE_FILE",
                label: "settings.keep_upload_source_file",
                type: "checkbox",
              },
              {
                icon: "mdi-file-document-outline",
                key: "UPLOAD_IGNORE_TITLE_CHECKING",
                label: "settings.upload_ignore_title_checking",
                type: "checkbox",
              },
              {
                icon: "mdi-checkbox-marked-circle-plus-outline",
                key: "BATCH_ADD_IN_FORCE",
                label: "settings.batch_add_in_force",
                type: "checkbox",
              },
            ],
          },
          {
            // 扫描目录 → 解析规则 → 收尾（删源文件、补默认语言）→ 自动导入（压最下方）
            id: "imp-rules",
            icon: "mdi-import",
            title: "settings.sec_imp_rules",
            fields: [
              { icon: "mdi-import", key: "scan_upload_path", label: "settings.scan_upload_path" },
              {
                icon: "mdi-server",
                key: "ENABLE_SERVER_FILE_IMPORT",
                label: "settings.enable_server_file_import",
                type: "checkbox",
              },
              {
                icon: "mdi-file-pdf-box",
                key: "PDF_TILE_WITH_FILE_NAME",
                label: "settings.pdf_tile_with_file_name",
                type: "checkbox",
              },
              {
                icon: "mdi-format-text",
                color: "red",
                key: "ENABLE_TXT_TO_TXTZ_PLUGIN",
                label: "settings.enable_txt_to_txtz_plugin",
                type: "checkbox",
              },
              {
                icon: "mdi-shape-plus",
                key: "IMPORT_CATEGORY_WITH_FOLDER",
                label: "settings.category_with_folder",
                type: "checkbox",
              },
              {
                icon: "mdi-delete-circle-outline",
                key: "REMOVE_IMPORTED_FILE",
                label: "settings.remove_imported_file",
                type: "checkbox",
              },
              {
                icon: "mdi-translate",
                key: "DEFAULT_LANGUAGE",
                label: "settings.default_language",
                type: "select",
                items: languageOptions.map((lang) => ({
                  text: lang.name,
                  value: lang.code,
                })),
              },
              // 小标题：把下面的目录监控和上面的单次导入规则分开（subtitle 不是真设置，
              // 键名带连字符，不会被 ensureSettingKeysReactive 当成可保存项）
              {
                icon: "mdi-crosshairs-gps",
                key: "imp-auto-heading",
                label: "settings.sec_imp_auto",
                type: "subtitle",
              },
            ],
            groups: [
              {
                icon: "mdi-crosshairs-gps",
                key: "IMPORT_BY_INOTIFY",
                label: "settings.auto_importing",
                al: ["监控"],
                fields: [
                  {
                    icon: "mdi-swap-horizontal",
                    key: "UPDATE_CATEGORY_WITH_FOLDER_RENAME",
                    label: "settings.update_category_with_folder_rename",
                    type: "checkbox",
                  },
                ],
              },
            ],
          },
          {
            id: "imp-store",
            icon: "mdi-folder-multiple-outline",
            title: "settings.sec_imp_store",
            fields: [
              {
                icon: "mdi-information",
                color: "red",
                key: "BOOK_NAMES_FORMAT",
                label: "settings.book_names_format",
                type: "select",
                al: ["拼音", "utf8", "pinyin"],
                items: [
                  { text: this.$t("settings.pinyin_directory"), value: "en" },
                  { text: this.$t("settings.utf8_directory"), value: "utf8" },
                ],
              },
            ],
          },
        ],
      },
      {
        id: "services",
        icon: "mdi-source-branch",
        title: "settings.group_services",
        sections: [
          {
            id: "svc-meta",
            icon: "mdi-web-sync",
            title: "settings.internet_book_sources",
            tips: [
              {
                text: "settings.douban_plugin_description",
              },
            ],
            fields: [
              {
                icon: "mdi-web-sync",
                key: "auto_fill_meta",
                label: "settings.auto_fill_meta",
                type: "checkbox",
              },
              {
                icon: "mdi-timer-sand",
                key: "auto_fill_qpm",
                label: "settings.auto_fill_qpm",
              },
              {
                icon: "mdi-pause-octagon",
                key: "auto_fill_pause_on_throttle",
                label: "settings.auto_fill_pause_on_throttle",
                type: "checkbox",
              },
              {
                icon: "mdi-source-branch",
                key: "META_SELECTED_SOURCES",
                label: "settings.meta_selected_source",
                type: "meta_sources",
                al: ["豆瓣", "书源"],
              },
              {
                icon: "mdi-information",
                key: "douban_baseurl",
                label: "settings.douban_baseurl",
              },
              {
                icon: "mdi-information",
                key: "douban_apikey",
                label: "settings.douban_api_key",
              },
              {
                icon: "mdi-information",
                key: "douban_max_count",
                label: "settings.douban_max_count",
              },
              {
                icon: "mdi-speedometer",
                key: "douban_v2_max_per_hour",
                label: "settings.douban_v2_max_per_hour",
              }
            ],
          },
          {
            id: "svc-ai",
            icon: "mdi-scatter-plot-outline",
            title: "settings.ai_capability",
            special: "ai_capabilities",
          },
          {
            id: "svc-bookbarn",
            icon: "mdi-key",
            title: "settings.book_barn_service",
            special: "bookbarn",
          },
        ],
      },
      {
        id: "protocols",
        icon: "mdi-cloud-outline",
        title: "settings.group_protocols",
        sections: [
          {
            id: "proto-webdav",
            icon: "mdi-cloud-check-outline",
            title: "settings.sec_proto_webdav",
            fields: [
              {
                icon: "mdi-cloud-check-outline",
                key: "ENABLE_WEBDAV_SERVICE",
                label: "settings.enable_webdav_service",
                type: "checkbox",
              },
              {
                icon: "mdi-cloud-sync-outline",
                key: "WEBDAV_SYNC_FOLDER",
                label: "settings.enable_webdav_sync",
                type: "checkbox",
              },
            ],
          },
          {
            id: "proto-opds",
            icon: "mdi-cloud-print-outline",
            title: "settings.sec_proto_opds",
            fields: [
              {
                icon: "mdi-cloud-print-outline",
                key: "ENABLE_OPDS_SERVICE",
                label: "settings.enable_opds_service",
                type: "checkbox",
              },
              {
                icon: "mdi-lock",
                key: "ENABLE_OPDS_AUTH",
                label: "settings.enable_opds_auth",
                type: "checkbox",
              },
            ],
          },
          {
            id: "proto-koreader",
            icon: "mdi-book-open-page-variant-outline",
            title: "settings.sec_proto_koreader",
            fields: [
              {
                icon: "mdi-book-open-page-variant-outline",
                key: "ENABLE_KOREADER_SERVICE",
                label: "settings.enable_koreader_service",
                type: "checkbox",
              },
            ],
          },
          {
            id: "proto-podcast",
            icon: "mdi-podcast",
            title: "settings.sec_proto_podcast",
            fields: [
              {
                icon: "mdi-podcast",
                key: "ENABLE_PODCAST_SERVICE",
                label: "settings.enable_podcast_service",
                type: "checkbox",
              },
            ],
          },
          {
            id: "proto-net",
            icon: "mdi-lock",
            title: "settings.sec_proto_net",
            fields: [
              { icon: "mdi-home", color: "red", key: "static_host", label: "settings.cdn_domain" },
              {
                icon: "mdi-lock",
                color: "red",
                key: "cookie_secret",
                label: "settings.cookie_secret",
              },
            ],
            special: "ssl",
          },
        ],
      },
      {
        id: "push",
        icon: "mdi-email-send",
        title: "settings.group_push",
        sections: [
          {
            id: "push-smtp",
            icon: "mdi-email",
            title: "settings.email_service",
            desc: "settings.email_service_description",
            fields: [
              { icon: "mdi-email", key: "smtp_server", label: "settings.smtp_server" },
              {
                icon: "mdi-account",
                key: "smtp_username",
                label: "settings.smtp_username",
              },
              {
                icon: "mdi-lock",
                key: "smtp_password",
                label: "settings.smtp_password",
              },
              {
                icon: "mdi-information",
                key: "smtp_encryption",
                label: "settings.smtp_encryption",
                type: "select",
                items: [
                  { text: "SSL", value: "SSL" },
                  { text: "TLS", value: "TLS" },
                ],
              },
            ],
            actions: [
              { icon: "mdi-email", label: "settings.test_email", action: "testEmail" },
            ],
          },
          {
            id: "push-tpl",
            icon: "mdi-email-send",
            title: "settings.sec_push_tpl",
            fields: [
              { icon: "mdi-information", key: "push_title", label: "settings.push_title" },
              { icon: "mdi-information", key: "push_content", label: "settings.push_content" },
              {
                icon: "mdi-email-send",
                key: "SEND_MAIL_FOR_NEW_BOOKS",
                label: "settings.send_mail_for_new_books",
                type: "checkbox",
              },
            ],
          },
          {
            id: "push-devices",
            icon: "mdi-tablet-cellphone",
            title: "settings.device_mgt",
            desc: "settings.device_mgt_description",
            special: "devices",
          },
        ],
      },
      {
        id: "ops",
        icon: "mdi-cog-outline",
        title: "settings.group_ops",
        sections: [
          {
            id: "ops-perf",
            icon: "mdi-speedometer",
            title: "settings.sec_ops_perf",
            special: "perf",
          },
          {
            id: "ops-log",
            icon: "mdi-math-log",
            title: "settings.sec_ops_log",
            fields: [
              {
                icon: "mdi-archive-cog-outline",
                color: "red",
                key: "LOG_LEVEL_DEBUG",
                label: "settings.enable_debug_logging",
                type: "checkbox",
              },
              {
                icon: "mdi-math-log",
                key: "ENABLE_AUDIO_CONVERSION_LOG",
                label: "settings.enable_audio_conversion_log",
                type: "checkbox",
              },
              {
                icon: "mdi-closed-caption-outline",
                key: "ENABLE_AUDIO_SUBTITLE",
                label: "settings.enable_audio_subtitle",
                type: "checkbox",
              },
              {
                icon: "mdi-restart",
                key: "autoreload",
                label: "settings.autoreload",
                type: "checkbox",
              },
              {
                icon: "mdi-information",
                key: "convert_timeout",
                label: "settings.convert_timeout",
              },
            ],
          },
          {
            id: "ops-update",
            icon: "mdi-update",
            title: "settings.sec_ops_update",
            fields: [
              {
                icon: "mdi-update",
                key: "AUTO_CHECKING_NEW_VERSION",
                label: "settings.auto_checking_new_version",
                type: "checkbox",
              },
              {
                icon: "mdi-toolbox-outline",
                key: "ENABLE_TOOLBOX_DEV_MODE",
                label: "settings.enable_toolbox_dev_mode",
                type: "checkbox",
              },
              {
                icon: "mdi-storefront-outline",
                key: "ENABLE_TOOLBOX_STORE",
                label: "settings.enable_toolbox_store",
                type: "checkbox",
              },
            ],
          },
          {
            id: "ops-trash",
            icon: "mdi-delete",
            title: "settings.trash_management",
            special: "trash",
          },
        ],
      },
    ];

    this.$backend("/admin/settings").then((rsp) => {
      this.sns_items = rsp.sns;
      this.settings = rsp.settings;
      this.site_url = rsp.site_url;
      // 当前图标的预览要绕过浏览器缓存，否则保存过新图标后仍显示旧图
      this.siteIconStamp = Date.now();

      if (this.settings) {
        this.$set(
          this.settings,
          "HOMEPAGE_CONFIG",
          normalizeHomepageConfig(this.settings["HOMEPAGE_CONFIG"])
        );
        if (this.settings["site_language"] === "") {
          this.$set(this.settings, "site_language", this.$i18n.locale);
        }
        // 老 auto.py 里没有这一项：空值等于「跟随站点语言」，落到 select 上会显示空白
        if (!this.settings["site_timezone"]) {
          this.$set(this.settings, "site_timezone", "auto");
        }
        if (
          !("site_icon" in this.settings) ||
          this.settings["site_icon"] === ""
        ) {
          this.$set(this.settings, "site_icon", "favicon_0");
        }
        if (!Array.isArray(this.settings["READER_MYDICTS"])) {
          this.$set(this.settings, "READER_MYDICTS", []);
        }
        for (const key of ["READER_DICT_MYBOOKS_ENABLED", "READER_DICT_BAIKE_ENABLED"]) {
          if (typeof this.settings[key] !== "boolean") this.$set(this.settings, key, true);
        }
        if (
          !("DEVICES" in this.settings) ||
          !Array.isArray(this.settings["DEVICES"])
        ) {
          this.$set(this.settings, "DEVICES", []);
        }
        if (
          !("META_SELECTED_SOURCES" in this.settings) ||
          !Array.isArray(this.settings["META_SELECTED_SOURCES"])
        ) {
          this.$set(
            this.settings,
            "META_SELECTED_SOURCES",
            (
              this.settings["META_ALL_SOURCES"] || [
                "douban",
                "baidu",
                "google",
                "amazon",
                "xinhua",
                "youshu",
                "ujxsw"
              ]
            ).slice()
          );
        }
        if (process.client && this.settings["MAX_UPLOAD_SIZE"] !== "") {
          localStorage.setItem(
            "max_upload_size",
            this.settings["MAX_UPLOAD_SIZE"]
          );
        }
        if (process.client && this.settings["CHUNK_UPLOAD_SIZE"] !== "") {
          localStorage.setItem(
            "chunk_upload_size",
            this.settings["CHUNK_UPLOAD_SIZE"]
          );
        }
        var m = {};
        rsp.sns.forEach(function (ele) {
          m[ele.value] = ele;
        });
        this.settings.SOCIALS.forEach(function (ele) {
          ele.help = false;
          ele.link = m[ele.value].link;
        });

        this.ensureSettingKeysReactive();
        this.bookNavList = this.parseBookNav(this.settings["BOOK_NAV"] || "");
        this.snapshot = JSON.parse(JSON.stringify(this.settings));
        this.bookNavSnapshot = JSON.parse(JSON.stringify(this.bookNavList));
        this.settingsLoaded = true;
      }
    });
  },
  data: () => ({
    combo_input: "",
    sns: {},
    sns_items: [],
    settings: {},
    settingsLoaded: false,
    snapshot: {},
    bookNavSnapshot: [],
    savingDefaultReadRange: false,
    site_url: "",
    // 读取设置时的时间戳，用于给「当前图标」预览做缓存失效（favicon.ico 会被覆盖）
    siteIconStamp: 0,
    groups: [],
    activeGroup: "site",
    searchQ: "",
    // 搜索框是否展开（收起态只显示放大镜图标，点开才出现输入框）
    searchOpen: false,
    // 搜索跳转的视图层展开状态（key = 嵌套开关 grp.key），不触碰真实设置值
    forceOpen: {},
    // 上一次「跳转到未保存项」的目标 key，供多次点击循环推进
    dirtyJumpKey: "",
    // 跳转到被模式开关隐藏的性能子项时只做视图层展开，不改真实设置值
    forceLiteGroups: false,
    forceCacheSize: false,
    bookNavList: [],
    thanksToNames: [],
    thanksToShow: false,
    appliedToken: false,
    testingConnection: false,
    testingAI: false,
    testingMynexus: false,
    mynexusToken: "",
    deviceTypes: [],
    deviceSchemas: [
      { text: "HTTP", value: "http" },
      { text: "HTTPS", value: "https" },
    ],
    trashSizes: { trash: 0, upload: 0 },
    trashSizeTexts: { trash: "", upload: "" },
    trashLoading: false,
    trashConfirmDialog: false,
    saveConfirmDialog: false,
    restartConfirmDialog: false,
    unsavedLeaveDialog: false,
    pendingLeave: null,
    stampPreviewUrl: "",
    stampPositions: [
      { value: "top-left", icon: "mdi-format-align-top" },
      { value: "top-center", icon: "mdi-format-align-top" },
      { value: "top-right", icon: "mdi-format-align-top" },
      { value: "center-left", icon: "mdi-format-align-middle" },
      { value: "center", icon: "mdi-format-align-middle" },
      { value: "center-right", icon: "mdi-format-align-middle" },
      { value: "bottom-left", icon: "mdi-format-align-bottom" },
      { value: "bottom-center", icon: "mdi-format-align-bottom" },
      { value: "bottom-right", icon: "mdi-format-align-bottom" },
    ],
  }),
  computed: {
    currentGroups() {
      return this.groups.filter((g) => g.id === this.activeGroup);
    },
    searchQuery() {
      return (this.searchQ || "").trim();
    },
    dirtyCount() {
      if (!this.settingsLoaded) return 0;
      const before = this.snapshot;
      const now = this.settings;
      let n = 0;
      Object.keys(now).forEach((k) => {
        if (
          JSON.stringify(settingsValueForCompare(k, before[k])) !==
          JSON.stringify(settingsValueForCompare(k, now[k]))
        ) {
          n++;
        }
      });
      if (JSON.stringify(this.bookNavSnapshot) !== JSON.stringify(this.bookNavList)) n++;
      return n;
    },
    // 未保存项按页面出现顺序排列，供顶栏 chip / 保存栏状态逐项跳转。
    // flatIndex 里特殊块统一追加在末尾，这里按 gid/sid 重新归位到它所在的小节。
    dirtyItems() {
      if (!this.settingsLoaded) return [];
      const before = this.snapshot;
      const now = this.settings;
      const dirtyKeys = {};
      Object.keys(now).forEach((k) => {
        if (
          JSON.stringify(settingsValueForCompare(k, before[k])) !==
          JSON.stringify(settingsValueForCompare(k, now[k]))
        ) {
          dirtyKeys[k] = true;
        }
      });
      const items = [];
      const seen = {};
      this.flatIndex.forEach((r) => {
        if (dirtyKeys[r.key] && !seen[r.key]) {
          items.push(r);
          seen[r.key] = true;
        }
      });
      // 社交登录的 KEY/SECRET 是 SOCIALS 动态拼键，不在 flatIndex 里；
      // 逐个补目标，否则改了凭据后计数会增加但点跳转没有落点
      (this.settings.SOCIALS || []).forEach((s) => {
        const value = String(s.value || "").toUpperCase();
        if (!value) return;
        const provider = s.text || value;
        ["KEY", "SECRET"].forEach((field) => {
          const key = "SOCIAL_AUTH_" + value + "_" + field;
          if (!dirtyKeys[key] || seen[key]) return;
          items.push({
            key,
            label: provider + " " + field,
            icon: "mdi-at",
            red: false,
            gid: "users",
            sid: "users-social",
            path: "",
            al: [],
            parentKey: "",
          });
          seen[key] = true;
        });
      });
      // 已从 SOCIALS 移除的 provider 仍可能留下脏 key（保存时仍会提交），
      // 没有独立控件可定位，至少落到社交登录卡片
      Object.keys(dirtyKeys).forEach((k) => {
        if (seen[k] || k.indexOf("SOCIAL_AUTH_") !== 0) return;
        const matched = k.match(/^SOCIAL_AUTH_(.+)_(KEY|SECRET)$/);
        if (!matched) return;
        items.push({
          key: k,
          label: matched[1] + " " + matched[2],
          icon: "mdi-at",
          red: false,
          gid: "users",
          sid: "users-social",
          path: "",
          al: [],
          parentKey: "",
        });
        seen[k] = true;
      });
      // BookNavEditor 改的是 bookNavList，settings.BOOK_NAV 要到保存时才序列化回去，
      // 所以分类编辑不体现在上面的 key 对比里，单独补到「书籍分类」卡片
      if (
        JSON.stringify(this.bookNavSnapshot) !== JSON.stringify(this.bookNavList) &&
        !seen["BOOK_NAV"]
      ) {
        const nav = this.flatIndex.find((r) => r.key === "BOOK_NAV");
        if (nav) items.push(nav);
      }
      const order = {};
      this.groups.forEach((g, gi) => {
        g.sections.forEach((s, si) => {
          order[g.id + "/" + s.id] = gi * 1000 + si;
        });
      });
      items.sort(
        (a, b) =>
          (order[a.gid + "/" + a.sid] || 0) - (order[b.gid + "/" + b.sid] || 0)
      );
      return items;
    },
    flatIndex() {
      const idx = [];
      const pathOf = {};
      this.groups.forEach((g) => {
        g.sections.forEach((s) => {
          pathOf[g.id + "/" + s.id] =
            this.$t(g.title) + " / " + this.$t(s.title);
        });
      });
      const push = (entry, gid, sid, extraPath, parentKey) => {
        idx.push({
          key: entry.key,
          label: this.$t(entry.label),
          icon: entry.icon || "",
          red: entry.color === "red",
          gid,
          sid,
          path: pathOf[gid + "/" + sid] + (extraPath ? " / " + extraPath : ""),
          al: entry.al || [],
          parentKey: parentKey || "",
        });
      };
      this.groups.forEach((g) => {
        g.sections.forEach((s) => {
          (s.fields || []).forEach((f) => push(f, g.id, s.id, ""));
          (s.groups || []).forEach((grp) => {
            push(grp, g.id, s.id, "");
            (grp.fields || []).forEach((f) =>
              push(f, g.id, s.id, this.$t(grp.label), grp.key)
            );
          });
        });
      });
      SPECIAL_BLOCKS.forEach((b) => {
        idx.push({
          key: b.key,
          label: this.$t(b.label),
          icon: b.icon,
          red: false,
          gid: b.gid,
          sid: b.sid,
          path: pathOf[b.gid + "/" + b.sid],
          al: b.al || [],
        });
      });
      return idx;
    },
    results() {
      const q = (this.searchQ || "").trim().toLowerCase();
      if (!q) return [];
      const tokens = q.split(/\s+/);
      const aliasSets = tokens.map((t) => aliasScoresFor(t));
      const out = [];
      this.flatIndex.forEach((r) => {
        const label = r.label.toLowerCase();
        const key = r.key.toLowerCase();
        const aliasText = r.al.join(" ").toLowerCase();
        // 分组/小节/嵌套开关名也参与匹配（「外部服务」这类标签页名字是用户第一眼看到的），
        // 打分低于字段标签命中，保证按名字找字段时排序仍以精确项在前
        const scope = (r.path || "").toLowerCase();
        let total = 0;
        for (let i = 0; i < tokens.length; i++) {
          const t = tokens[i];
          let best = aliasSets[i][r.key] || 0;
          if (label.indexOf(t) >= 0) best = Math.max(best, t.length >= 2 ? 76 : 55);
          if (key.indexOf(t) >= 0) best = Math.max(best, 60);
          if (aliasText.indexOf(t) >= 0) best = Math.max(best, 64);
          if (scope.indexOf(t) >= 0) best = Math.max(best, 50);
          if (best === 0) {
            total = 0;
            break;
          }
          total += best;
        }
        if (total > 0) out.push(Object.assign({ score: total }, r));
      });
      out.sort((a, b) => b.score - a.score);
      return out;
    },
    liteGroups() {
      return LITE_GROUPS;
    },
    thumbCache: {
      get() {
        return this.settings["THUMB_CACHE"] !== false;
      },
      set(value) {
        this.$set(this.settings, "THUMB_CACHE", value);
      },
    },
    cacheMaxMb: {
      get() {
        return Number(this.settings["CACHE_MAX_MB"]) || 200;
      },
      set(value) {
        this.$set(this.settings, "CACHE_MAX_MB", value);
      },
    },
    cacheSizeItems() {
      return [50, 100, 200, 300].map((v) => ({ text: v + " MB", value: v }));
    },
    liteMode: {
      get() {
        return this.settings["PERFORMANCE_MODE"] === "lite";
      },
      set(value) {
        this.$set(this.settings, "PERFORMANCE_MODE", value ? "lite" : "normal");
      },
    },
    urlRule() {
      return (v) => {
        if (!v) return true;
        const pattern = /^https?:\/\/.+/;
        return pattern.test(v) || this.$t('settings.url_rule_error');
      };
    },
    modelNameRule() {
      return (v) => {
        if (!v) return true;
        const pattern = /^(?![.\-/:])[a-zA-Z0-9]+(?:[_.\-/:][a-zA-Z0-9]+)*$/;
        return pattern.test(v) || this.$t('settings.model_name_rule_error');
      };
    },
    apiKeyRules() {
      return [
        (v) => !v || /^[a-zA-Z0-9-._]*$/.test(v) || this.$t('settings.api_key_rule_error'),
        (v) => !v || (v.length >= 16 && v.length <= 128) || this.$t('settings.api_key_length_error'),
      ];
    },
    metaSourceItems() {
      const allSources = this.settings["META_ALL_SOURCES"] || [
        "douban",
        "baidu",
        "google",
        "amazon",
        "xinhua",
        "youshu",
        "douban_v2",
        "ujxsw"
      ];
      return allSources.map((source) => ({
        text: this.$t("settings.meta_source_" + source),
        value: source,
      }));
    },
    saveConfirmMessage() {
      return this.settings["autoreload"]
        ? this.$t("settings.save_confirm_message_autoreload")
        : this.$t("settings.save_confirm_message_no_autoreload");
    },
    bookNavDuplicateNames() {
      const counts = {};
      this.bookNavList.forEach((cat) => {
        const name = (cat.name || "").trim();
        if (!name) return;
        counts[name] = (counts[name] || 0) + 1;
      });
      return Object.keys(counts).filter((name) => counts[name] > 1);
    },
    defaultReadRangeSummary() {
      const range = this.settings["DEFAULT_READ_RANGE"] || {};
      const mode = range.mode || 0;
      if (mode === 0) {
        return this.$t("settings.default_read_range_all");
      }
      const categories = range.categories ? range.categories.split(",").filter(Boolean) : [];
      const tags = range.tags ? range.tags.split(",").filter(Boolean) : [];
      const parts = [];
      if (categories.length) {
        parts.push(this.$t("settings.default_read_range_categories_part", { value: categories.join("、") }));
      }
      if (tags.length) {
        parts.push(this.$t("settings.default_read_range_tags_part", { value: tags.join("、") }));
      }
      const list = parts.length ? parts.join("，") : this.$t("settings.default_read_range_unset");
      return mode === 1
        ? this.$t("settings.default_read_range_whitelist", { list })
        : this.$t("settings.default_read_range_blacklist", { list });
    },
  },
  beforeRouteLeave(_to, _from, next) {
    if (this.dirtyCount > 0) {
      this.pendingLeave = { to: _to, next };
      this.unsavedLeaveDialog = true;
      next(false);
      return;
    }
    next();
  },
  watch: {
    activeGroup() {
      this.$nextTick(() => this.positionSegIndicator());
    },
    searchQuery() {
      this.$nextTick(() => this.positionSegIndicator());
    },
    searchOpen(val) {
      const run = () => this.positionSegIndicator();
      this.$nextTick(() => { run(); setTimeout(run, 260); });
    },
  },
  mounted() {
    this.fetchTrashSize();
    this.loadStampImage();
    this.loadThanksTo();
    this.updateBarOffset();
    this.$nextTick(() => {
      this.positionSegIndicator();
      if (process.client) {
        const seg = this.$el && this.$el.querySelector(".settings-seg");
        if (seg) {
          this._segObserver = new ResizeObserver(() => this.positionSegIndicator());
          this._segObserver.observe(seg);
        }
      }
    });
    if (process.client) {
      window.addEventListener("resize", this.updateBarOffset);
      window.addEventListener("resize", this.positionSegIndicator);
      window.addEventListener("beforeunload", this.handleBeforeUnload);
      this.watchAppBar();
      this.$nextTick(() => this.scrollToRouteHash());
    }
  },
  beforeDestroy() {
    // 页面销毁时移除settings-page类名
    if (process.client) {
      document.body.classList.remove("settings-page");
      window.removeEventListener("resize", this.updateBarOffset);
      window.removeEventListener("resize", this.positionSegIndicator);
      window.removeEventListener("beforeunload", this.handleBeforeUnload);
      // 清掉 documentElement 上的全局 CSS 变量，避免残留值影响其他页面
      document.documentElement.style.removeProperty("--settings-bar-top");
      if (this._segObserver) {
        this._segObserver.disconnect();
        this._segObserver = null;
      }
      if (this._barObserver) {
        this._barObserver.disconnect();
        this._barObserver = null;
      }
      if (this._barWatcher) {
        this._barWatcher.disconnect();
        this._barWatcher = null;
      }
      if (this._jumpTimer) {
        clearTimeout(this._jumpTimer);
        this._jumpTimer = null;
      }
    }
  },
  methods: {
    // 网站图标下拉的预览地址。favicon_0 表示「沿用当前图标」，要展示站点此刻真正
    // 生效的 /logo/favicon.ico（保存其它图标时它会被覆盖），因此带时间戳绕过缓存；
    // 其余选项展示随附的 favicon_N.ico。
    siteIconSrc(item) {
      if (item && item.is_current) {
        return `${this.site_url}/logo/favicon.ico?t=${this.siteIconStamp}`;
      }
      return `${this.site_url}/logo/${item.image_file}.ico`;
    },
    // lockOn 指定的总开关开启后，该字段失去意义：置灰显示为未勾选且不可点选
    // （与后端一致——REQUIRE_LOGIN 下各项访客权限恒按 False 处理），
    // 但不回写 settings，保留用户原先保存的访客权限值，关掉总开关后原样恢复。
    isFieldLockedBy(f) {
      return !!(f && f.lockOn && this.settings && this.settings[f.lockOn]);
    },
    isCheckboxInputValue(f) {
      return this.isFieldLockedBy(f) ? false : this.settings[f.key];
    },
    onCheckboxChange(f, value) {
      if (this.isFieldLockedBy(f)) return;
      this.$set(this.settings, f.key, value);
    },
    // checkbox_list 里带 requires 的选项：依赖的总开关关闭时置灰且显示为未勾选。
    // 锁定只是显示层的判断，不改写 settings[f.key]：checkboxListInputValue 把锁定项从
    // 展示数组里滤掉（所以它呈现为未勾选、也点不动），而 onCheckboxListChange 保存时会把
    // 「已存储但当前锁定」的值补回去。于是重新打开总开关后原勾选照旧恢复，用户在锁定期间
    // 改动其它选项也不会把该值永久删掉。
    isCheckboxOptionLocked(f, opt) {
      return !!(opt && opt.requires && this.settings && !this.settings[opt.requires]);
    },
    checkboxListInputValue(f) {
      const stored = Array.isArray(this.settings[f.key]) ? this.settings[f.key] : [];
      return stored.filter(
        (value) => !(f.items || []).some((opt) => opt.value === value && this.isCheckboxOptionLocked(f, opt))
      );
    },
    onCheckboxListChange(f, value) {
      // Vuetify 2 的 Selectable 用 input-value 播种 internalValue，勾选框 change 抛出的数组
      // 必然不含当前锁定项，直接照原样保存就会永久删掉它（如关掉「文件夹浏览」期间改一次
      // 列表就再也回不来）。所以先把「已存储且此刻锁定」的值按存储顺序补回，再落库。
      // 补回必须在空值哨兵判断之前：只剩锁定项的列表不是「全不勾选」，不该写 "none"。
      // SIDEBAR_ITEMS 的空数组历史上表示「全部显示」，全不勾选时写 emptyValue 哨兵，
      // 让「全部隐藏」也能保存生效，同时不影响旧配置的空数组语义。
      const sentinel = f.emptyValue;
      const emitted = (Array.isArray(value) ? value : []).filter((item) => item !== sentinel);
      const stored = Array.isArray(this.settings[f.key]) ? this.settings[f.key] : [];
      const locked = stored.filter(
        (item) => item !== sentinel && (f.items || []).some((opt) => opt.value === item && this.isCheckboxOptionLocked(f, opt))
      );
      const missing = locked.filter((item) => emitted.indexOf(item) < 0);
      let next = emitted.concat(missing);
      if (sentinel && next.length === 0) next = [sentinel];
      this.$set(this.settings, f.key, next);
    },
    // rsp.settings 里没有的 key 拿不到响应式 getter（服务端 CONF 没给默认值的项，
    // 如 ENABLE_BOOKS_TYPE_CONVERT_DIRECT、微信的 SOCIAL_AUTH_*_KEY/_SECRET）。
    // Vue 2 下 v-model 的普通赋值不走 setter，dirtyCount 不会重算，「保存设置」就一直是
    // 禁用态、离开守卫也不提示——单改这一项会被静默丢弃。这里按字段类型补默认值并 $set，
    // 让它与其它项一样可以被单独修改和计数。
    ensureSettingKeysReactive() {
      const seed = (key, type) => {
        if (!key || key in this.settings) return;
        if (type === "checkbox") this.$set(this.settings, key, false);
        else if (SETTING_TEXT_TYPES.indexOf(type) >= 0) this.$set(this.settings, key, "");
      };
      this.groups.forEach((g) => {
        g.sections.forEach((s) => {
          (s.fields || []).forEach((f) => seed(f.key, f.type));
          (s.groups || []).forEach((grp) => {
            seed(grp.key, "checkbox");
            (grp.fields || []).forEach((f) => seed(f.key, f.type));
          });
        });
      });
      // 社交登录的 KEY/SECRET 由 SOCIALS 动态拼键，不在 groups 里
      (this.settings.SOCIALS || []).forEach((s) => {
        const v = String(s.value || "").toUpperCase();
        seed("SOCIAL_AUTH_" + v + "_KEY", "text");
        seed("SOCIAL_AUTH_" + v + "_SECRET", "text");
      });
    },
    // 全局 AppHeader 由 store.nav 的 v-if 控制渲染，可能晚于本页 mounted；出现后按其真实高度校准吸顶偏移
    watchAppBar() {
      const attach = () => {
        const header = document.querySelector(".v-app-bar");
        if (!header) return false;
        this._barObserver = new ResizeObserver(this.updateBarOffset);
        this._barObserver.observe(header);
        this.updateBarOffset();
        return true;
      };
      if (attach()) return;
      this._barWatcher = new MutationObserver(() => {
        if (attach() && this._barWatcher) {
          this._barWatcher.disconnect();
          this._barWatcher = null;
        }
      });
      this._barWatcher.observe(document.body, { childList: true, subtree: true });
    },
    updateBarOffset() {
      const header = document.querySelector(".v-app-bar");
      const bottom = header ? header.getBoundingClientRect().bottom : 56;
      document.documentElement.style.setProperty(
        "--settings-bar-top",
        Math.max(48, Math.round(bottom)) + "px"
      );
    },
    // 关闭/刷新标签页前的未保存提示（浏览器只允许展示原生文案，无法本地化）
    handleBeforeUnload(e) {
      if (this.dirtyCount > 0) {
        e.preventDefault();
        e.returnValue = "";
      }
    },
    // 入参保留分组 id（调用侧 groupAccent(g.id) 不变），色值当前统一取站点主色 accent
    groupAccent(_id) {
      const ap = this.$store && this.$store.state && this.$store.state.appearance;
      const a = ap && ap.accent;
      return isHexColor(a) ? a.toLowerCase() : DEFAULT_ACCENT;
    },
    openSearch() {
      this.searchOpen = true;
      this.$nextTick(() => {
        const f = this.$refs.searchField;
        if (f && f.focus) f.focus();
      });
    },
    closeSearch() {
      this.searchQ = "";
      this.searchOpen = false;
    },
    onSearchBlur() {
      if (!this.searchQuery) this.searchOpen = false;
    },
    positionSegIndicator() {
      if (!process.client) return;
      const ind = this.$refs.segIndicator;
      if (!ind) return;
      const container = ind.parentElement;
      if (!container) return;
      const btns = container.querySelectorAll(".settings-seg-btn");
      if (!btns.length) return;
      let target = null;
      if (this.searchQuery) {
        ind.style.opacity = "0";
        return;
      }
      for (const b of btns) {
        if (b.classList.contains("is-active")) { target = b; break; }
      }
      if (!target) target = btns[0];
      ind.style.opacity = "1";
      ind.style.width = target.offsetWidth + "px";
      ind.style.height = target.offsetHeight + "px";
      ind.style.transform =
        "translate(" + target.offsetLeft + "px, " + target.offsetTop + "px)";
    },
    selectGroup(id) {
      this.searchQ = "";
      this.searchOpen = false;
      this.forceLiteGroups = false;
      this.forceCacheSize = false;
      this.activeGroup = id;
      if (process.client) window.scrollTo({ top: 0 });
    },
    // role="tab" 的方向键导航：按当前位置 ±1 环绕切换分组并把焦点移到对应标签
    focusGroupTab(i) {
      const n = this.groups.length;
      if (!n || !process.client) return;
      const idx = ((i % n) + n) % n;
      this.selectGroup(this.groups[idx].id);
      this.$nextTick(() => {
        const btns = this.$el.querySelectorAll(".settings-seg-btn");
        if (btns && btns[idx]) btns[idx].focus();
      });
    },
    jumpTo(r) {
      this.searchQ = "";
      this.searchOpen = false;
      this.activeGroup = r.gid;
      // 极速模式/缩略图缓存关闭后其子项被 v-if 隐藏；跳转只做视图层展开，
      // 并且只在「本次跳转确实需要」时展开——否则跳完一次后隐藏子项会一直可见，
      // 用户能在 PERFORMANCE_MODE=normal 下改到平时看不见的设置并保存掉
      this.forceLiteGroups = r.key.indexOf("LITE_GROUP_") === 0;
      this.forceCacheSize = r.key === "CACHE_MAX_MB";
      if (r.parentKey) {
        // 只做视图层展开：写真实 settings 会静默开启 INVITE_MODE 等父开关并计入未保存数
        this.$set(this.forceOpen, r.parentKey, true);
      }
      if (!process.client) return;
      this.$nextTick(() => {
        // 句柄存下来，页面销毁时清掉（同页其它定时器/监听器都成对清理）
        if (this._jumpTimer) clearTimeout(this._jumpTimer);
        this._jumpTimer = setTimeout(() => {
          this._jumpTimer = null;
          const domKey = ANCHOR_ALIASES[r.key] || r.key;
          const el =
            document.getElementById("f-" + domKey) ||
            document.getElementById("sec-" + r.gid + "-" + r.sid);
          if (!el) return;
          el.scrollIntoView({ behavior: "smooth", block: "center" });
          el.classList.remove("field-flash");
          void el.offsetWidth;
          el.classList.add("field-flash");
        }, 100);
      });
    },
    // 顶栏 chip 与保存栏状态共用同一个游标：每次点击跳到下一个未保存项，
    // 走到末项后回到第一项；只有一项时就地重跳（再闪一次）
    jumpToNextDirty() {
      const items = this.dirtyItems;
      if (!items.length) return;
      const idx = items.findIndex((r) => r.key === this.dirtyJumpKey);
      const next = items[(idx + 1) % items.length];
      this.dirtyJumpKey = next.key;
      this.jumpTo(next);
    },
    scrollToRouteHash() {
      const hash = this.$route && this.$route.hash;
      const matched = hash && hash.match(/^#sec-([^-]+)-(.+)$/);
      if (!matched) return;
      const gid = matched[1];
      const sid = matched[2];
      this.activeGroup = gid;
      this.$nextTick(() => {
        const el = document.getElementById("sec-" + gid + "-" + sid);
        if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    },
    openDefaultReadRangeDialog() {
      const range = this.settings["DEFAULT_READ_RANGE"] || {};
      this.$refs.defaultReadRangeDialog.open({
        mode: range.mode || 0,
        categories: range.categories || "",
        tags: range.tags || "",
      });
    },
    saveDefaultReadRange(range) {
      const defaultReadRange = {
        mode: range.mode,
        categories: range.categories,
        tags: range.tags,
      };
      this.savingDefaultReadRange = true;
      this.$backend("/admin/settings", {
        method: "POST",
        body: JSON.stringify({DEFAULT_READ_RANGE: defaultReadRange }),
      }).then((rsp) => {
        if (rsp.err !== "ok") {
          this.$alert("error", rsp.msg || this.$t("settings.save_error"));
          return;
        }
        this.$set(this.settings, "DEFAULT_READ_RANGE", defaultReadRange);
        this.$set(this.snapshot, "DEFAULT_READ_RANGE", JSON.parse(JSON.stringify(defaultReadRange)));
        this.$refs.defaultReadRangeDialog.close();
        this.$alert("success", rsp.msg || this.$t("settings.save_success"));
      }).finally(() => {
        this.savingDefaultReadRange = false;
      });
    },
    async loadThanksTo() {
      try {
        const rsp = await this.$backend("/admin/thanks/notes");
        if (rsp.err === "ok") {
          this.thanksToNames = rsp.names || [];
        }
      } catch (error) {
        console.warn("Failed to load thanks-to list:", error);
      }
    },
    parseBookNav(text) {
      const list = [];
      (text || "").split("\n").forEach((line) => {
        if (!line.trim()) return;
        const idx = line.indexOf("=");
        let name = line;
        let tags = [];
        if (idx !== -1) {
          name = line.slice(0, idx);
          tags = line
            .slice(idx + 1)
            .split("/")
            .map((t) => t.trim())
            .filter((t) => t !== "");
        }
        list.push(createCategory(name.trim(), tags));
      });
      return list;
    },
    serializeBookNav(list) {
      return list
        .filter((cat) => (cat.name || "").trim() !== "")
        .map((cat) => `${cat.name.trim()}=${(cat.tags || []).join("/")}`)
        .join("\n");
    },
    saveSettings: function () {
      if (this.bookNavDuplicateNames.length > 0) {
        this.$alert(
          "error",
          this.$t("settings.book_nav_duplicate_error", {
            names: this.bookNavDuplicateNames.join("、"),
          })
        );
        return;
      }
      // 规范化只作用于提交副本：BOOK_NAV 的 parse→serialize 往返不恒等，
      // 若先改写 live settings，保存失败会留下用户没动过的假 diff 且无自愈出口
      const payload = JSON.parse(JSON.stringify(this.settings));
      payload["BOOK_NAV"] = this.serializeBookNav(this.bookNavList);
      // showToken is view state only; the server drops incomplete entries.
      payload["READER_MYDICTS"] = (payload["READER_MYDICTS"] || []).map((dict) => {
        const entry = { ...dict };
        delete entry.showToken;
        return entry;
      });

      if (payload["site_language"] === "") {
        payload["site_language"] = "zh";
      }
      if (!payload["site_timezone"]) {
        payload["site_timezone"] = "auto";
      }

      // 快照取提交时刻的值：保存期间的新编辑不会被视为已持久化
      const savedSnapshot = JSON.parse(JSON.stringify(payload));
      const savedNav = JSON.parse(JSON.stringify(this.bookNavList));
      this.$backend("/admin/settings", {
        method: "POST",
        body: JSON.stringify(payload),
      }).then((rsp) => {
        if (rsp.err != "ok") {
          this.$alert("error", rsp.msg || this.$t("settings.save_error"));
          return;
        }
      });
      const settingsToSave = { ...this.settings };
      this.$backend("/admin/settings", {
        method: "POST",
        body: JSON.stringify(settingsToSave),
      }).then((rsp) => {
        if (rsp.err != "ok") {
          this.$alert("error", rsp.msg || this.$t("settings.save_error"));
        } else {
          this.$alert("success", rsp.msg || this.$t("settings.save_success"));
          this.$store.commit("refresh_sys");
        }
        // 服务端确认后才把规范化结果落到本地状态与 localStorage
        this.settings["BOOK_NAV"] = payload["BOOK_NAV"];
        this.settings["READER_MYDICTS"] = payload["READER_MYDICTS"];
        this.settings["site_language"] = payload["site_language"];
        if (this.settings["site_language"] !== "") {
          this.$i18n.locale = this.settings["site_language"];
        }
        if (process.client) {
          if (this.settings["MAX_UPLOAD_SIZE"] !== "") {
            localStorage.setItem(
              "max_upload_size",
              this.settings["MAX_UPLOAD_SIZE"]
            );
          }

          if (this.settings["CHUNK_UPLOAD_SIZE"] !== "") {
            localStorage.setItem(
              "chunk_upload_size",
              this.settings["CHUNK_UPLOAD_SIZE"]
            );
          }

          localStorage.setItem("indexPage", this.settings["INDEX_PAGE_TYPE"]);
          localStorage.setItem("aiEnabled", this.settings["AI_ENABLED"]);
          localStorage.setItem(
            "defaultPageSize",
            this.settings["DEFAULT_PAGE_SIZE"]
          );
        }
        this.snapshot = savedSnapshot;
        this.bookNavSnapshot = savedNav;
        // 全部保存后游标归零，下次产生未保存项时从第一项开始跳
        this.dirtyJumpKey = "";
        this.forceLiteGroups = false;
        this.forceCacheSize = false;
        this.$alert("success", rsp.msg || this.$t("settings.save_success"));
      });
    },
    restartServer: function () {
      this.restartConfirmDialog = false;
      this.$backend("/admin/restart", {
        method: "POST",
      }).then((rsp) => {
        if (rsp.err != "ok") {
          this.$alert("error", rsp.msg || this.$t("settings.restart_error"));
        } else {
          this.$alert("success", rsp.msg || this.$t("settings.restart_success"));
        }
      });
    },
    confirmLeave() {
      const pending = this.pendingLeave;
      this.pendingLeave = null;
      if (!pending) return;
      const n = pending.next;
      if (typeof n === "function") {
        n();
      }
    },
    cancelLeave() {
      this.pendingLeave = null;
    },
    showSNSConfig: function (s) {
      var msg = `${this.$t("settings.sns_config_message", {
        text: s.text,
        link: s.link,
        site_url: this.site_url,
        value: s.value,
      })}`;
      this.$alert("warning", msg);
    },
    applyBookbarnToken() {
      this.appliedToken = true;
      this.$backend("/admin/bookbarn/token/apply", {
        method: "POST",
        body: JSON.stringify(this.settings),
      }).then((rsp) => {
        if (rsp.err != "ok") {
          this.appliedToken = false;
          this.$alert("error", rsp.msg);
        } else {
          this.$alert("success", rsp.msg);
          this.settings["BOOKBARN_TOKEN"] = rsp.token;
        }
      });
    },
    testEmail: function () {
      var data = new URLSearchParams();
      data.append("smtp_server", this.settings["smtp_server"]);
      data.append("smtp_username", this.settings["smtp_username"]);
      data.append("smtp_password", this.settings["smtp_password"]);
      data.append("smtp_encryption", this.settings["smtp_encryption"]);
      this.$backend("/admin/testmail", {
        method: "POST",
        body: data,
      }).then((rsp) => {
        if (rsp.err != "ok") {
          this.$alert("error", rsp.msg);
        } else {
          this.$alert("success", rsp.msg);
        }
      });
    },
    run: function (func) {
      this[func]();
    },
    generateMCPToken: function () {
      // Call backend API to generate token
      this.$backend("/admin/token")
        .then((rsp) => {
          if (rsp.err !== "ok") {
            this.$alert(
              "error",
              this.$t("settings.ai_mcp_token_generate_failed")
            );
          } else {
            this.settings["AI_MCP_TOKEN"] = rsp.token;
            this.$alert("success", this.$t("settings.ai_mcp_token_generated"));
          }
        })
        .catch((_err) => {
          this.$alert(
            "error",
            this.$t("settings.ai_mcp_token_generate_failed")
          );
        });
    },
    fetchTrashSize() {
      this.trashLoading = true;
      this.$backend("/admin/trash/size").then((rsp) => {
        this.trashLoading = false;
        if (rsp && rsp.err === "ok" && rsp.sizes) {
          this.trashSizes = rsp.sizes;
          this.trashSizeTexts = {
            trash: this.formatTrashSize(rsp.sizes.trash),
            upload: this.formatTrashSize(rsp.sizes.upload),
          };
        } else {
          this.trashSizeTexts = {
            trash: this.$t("settings.trash_unknown"),
            upload: this.$t("settings.trash_unknown"),
          };
        }
      });
    },
    formatTrashSize(size) {
      if (size < 1024) return size + " B";
      if (size < 1024 * 1024) return (size / 1024).toFixed(1) + " KB";
      if (size < 1024 * 1024 * 1024)
        return (size / 1024 / 1024).toFixed(2) + " MB";
      return (size / 1024 / 1024 / 1024).toFixed(2) + " GB";
    },
    clearTrash() {
      this.trashConfirmDialog = false;
      this.$backend("/admin/trash/clear", {
        method: "POST",
      }).then((rsp) => {
        if (rsp && rsp.err === "ok") {
          this.$alert("success", rsp.msg);
          this.fetchTrashSize();
        } else {
          this.$alert("error", rsp.msg);
        }
      });
    },
    uploadStampImage(event) {
      const file = event.target.files[0];
      if (!file) return;

      // 验证文件类型
      if (file.type !== 'image/png') {
        this.$alert("error", this.$t('settings.stamp_image_format_error'));
        return;
      }

      // 验证文件大小
      const maxSize = 128 * 1024; // 128KB
      if (file.size > maxSize) {
        this.$alert("error", this.$t('settings.stamp_image_size_error'));
        return;
      }

      // 验证图片尺寸
      const img = new Image();
      const reader = new FileReader();

      reader.onload = (e) => {
        img.onload = () => {
          if (img.width > 480 || img.height > 480) {
            this.$alert("error", this.$t('settings.stamp_image_dimension_error'));
            return;
          }

          // 验证通过，上传图片
          const formData = new FormData();
          formData.append('file', file);

          this.$backend("/admin/stamp", {
            method: "POST",
            body: formData,
          }).then((rsp) => {
            if (rsp.err === "ok") {
              this.$alert("success", this.$t('settings.stamp_upload_success'));
              this.loadStampImage();
            } else {
              this.$alert("error", rsp.msg);
            }
          });
        };
        img.src = e.target.result;
      };

      reader.readAsDataURL(file);
    },
    loadStampImage() {
      // 加载图章预览图片
      const timestamp = new Date().getTime();
      this.stampPreviewUrl = `${this.site_url}/logo/stamp.png?t=${timestamp}`;
    },
    openStampFileDialog() {
      // 处理ref可能是数组的情况（在v-for中）
      const input = this.$refs.stampFileInput;
      if (input) {
        const element = Array.isArray(input) ? input[0] : input;
        if (element && typeof element.click === 'function') {
          element.click();
        }
      }
    },
    testAISettings() {
      const data = {
        api_url: this.settings['AI_API_URL'],
        api_key: this.settings['AI_DEEPSEEK_API_KEY'],
        api_model: this.settings['AI_MODEL'],
      };
      this.testingAI = true;
      this.$backend("/admin/ai/test", {
        method: "POST",
        body: JSON.stringify(data)
      }).then((rsp) => {
        if (rsp && rsp.err === "ok") {
          this.$alert("success", rsp.msg);
        } else {
          this.$alert("error", rsp.msg);
        }
      }).catch((err) => {
        this.$alert("error", err.message || this.$t("settings.test_ai_failed"));
      }).finally(() => {
        this.testingAI = false;
      });
    },
    testMyNexusConnection() {
      this.testingMynexus = true;
      this.$backend("/admin/mynexus/test", {
        method: "POST",
        body: JSON.stringify({
          url: this.settings["MYNEXUS_URL"],
          token: this.settings["MYNEXUS_TOKEN"],
        }),
      }).then((rsp) => {
        if (rsp && rsp.err === "ok") {
          this.$alert("success", rsp.msg);
        } else {
          this.$alert("error", rsp.msg || this.$t("settings.mynexus_test_failed"));
        }
      }).catch((err) => {
        this.$alert("error", err.message || this.$t("settings.mynexus_test_failed"));
      }).finally(() => {
        this.testingMynexus = false;
      });
    },
  },
};
</script>

<style>
.cursor-pointer {
  cursor: pointer;
}

/* 页内吸顶分组条：top 动态取全局 v-app-bar 实际底边（mounted 时测量写入 CSS 变量，
   xs 端 AppHeader 的搜索扩展行有无会导致高度在 48~120px 间变化，不能硬编码） */
.settings-group-bar {
  position: sticky;
  top: var(--settings-bar-top, 56px);
  z-index: 2;
  padding: 10px 12px 8px;
  margin-bottom: 12px;
}
.settings-group-bar-row {
  gap: 10px;
  flex-wrap: wrap;
}
/* iOS 分段式分组条（形态借鉴 uiverse Zanina 分段 tab，样式为本仓 clean-room 实现）：
   灰底容器 + 激活项高亮 + 品牌主色条；8 个按钮均分整行，圆角跟随 --app-radius
  （与右上角外观菜单的按钮圆角同一变量） */
.settings-seg {
  position: relative;
  display: grid;
  grid-template-columns: repeat(8, minmax(0, 1fr));
  grid-auto-rows: min-content;
  gap: 4px 2px;
  flex: 1 1 auto;
  min-width: 0;
  background: #e8e8e8;
  border-radius: var(--app-radius, 4px);
  padding: 4px;
}
@media (max-width: 1100px) {
  .settings-seg {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }
}
@media (max-width: 440px) {
  .settings-seg {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}
.settings-seg-indicator {
  position: absolute;
  top: 0;
  left: 0;
  z-index: 0;
  height: 100%;
  background: #fff;
  border-radius: var(--app-radius, 4px);
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.18);
  transition: transform 0.32s cubic-bezier(0.4, 0, 0.2, 1),
    width 0.32s cubic-bezier(0.4, 0, 0.2, 1),
    height 0.32s cubic-bezier(0.4, 0, 0.2, 1);
  pointer-events: none;
  will-change: transform, width, height;
}
.settings-seg-btn {
  position: relative;
  z-index: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  gap: 4px;
  border: 0;
  background: transparent;
  border-radius: var(--app-radius, 4px);
  padding: 6px 8px 9px;
  line-height: 1.4;
  color: inherit;
  cursor: pointer;
  white-space: nowrap;
}
.settings-seg-btn:hover {
  background: rgba(0, 0, 0, 0.06);
}
.settings-seg-btn.is-active {
  font-weight: 500;
  color: #212121;
}
.settings-seg-btn:focus-visible {
  outline: 2px solid #1976d2;
  outline-offset: 1px;
}
/* 暗色底上 #1976d2 对比度不足 3:1，换浅一档的蓝 */
.theme--dark .settings-seg-btn:focus-visible {
  outline-color: #90caf9;
}
.settings-seg-btn .v-icon {
  margin-right: 2px;
}
/* 激活项下方品牌主色条（与组标题竖条同色呼应） */
.settings-seg-bar {
  position: absolute;
  left: 14px;
  right: 14px;
  bottom: 3px;
  height: 3px;
  border-radius: 2px;
  opacity: 0;
}
.settings-seg-btn.is-active .settings-seg-bar {
  opacity: 1;
}
/* 组标题左侧竖条，与 pill 色条同色 */
.settings-group-title-bar {
  width: 4px;
  align-self: stretch;
  min-height: 36px;
  border-radius: 2px;
  margin-right: 2px;
}
.theme--dark .settings-seg {
  background: #2b2b2b;
}
.theme--dark .settings-seg-indicator {
  background: #424242;
}
.theme--dark .settings-seg-btn:hover {
  background: rgba(255, 255, 255, 0.08);
}
.theme--dark .settings-seg-btn.is-active {
  color: #fafafa;
}
/* 右侧：状态 chip + 搜索图标/展开框 */
.settings-bar-right {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-left: auto;
  flex: 0 0 auto;
}
.settings-status-chip {
  position: static;
  transform: none;
  flex: 0 0 auto;
}
/* 未保存计数可点击：逐项跳到未保存字段 */
.settings-status-chip-clickable {
  cursor: pointer;
}
.settings-status-chip-clickable:hover {
  filter: brightness(1.08);
}
.settings-status-chip-clickable:focus-visible {
  outline: 2px solid #ef6c00;
  outline-offset: 2px;
}
.theme--dark .settings-status-chip-clickable:focus-visible {
  outline-color: #90caf9;
}
/* 状态 chip 的 live region 外壳（保持与原来一致的 flex 占位） */
.settings-status-chip-wrap {
  display: inline-flex;
  align-items: center;
  flex: 0 0 auto;
}
/* 仅读屏可见（aria-describedby 的描述源）：不能 display:none，那样描述会丢失 */
.settings-sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  margin: -1px;
  padding: 0;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
.settings-search-btn {
  flex: 0 0 auto;
}
.settings-group-bar .settings-search-expanded {
  flex: 0 1 260px;
  margin: 0;
}
.settings-search .v-input__slot,
.settings-search fieldset {
  border-radius: 9999px !important;
}
@media (max-width: 599.98px) {
  .settings-seg {
    flex: 1 1 100%;
  }
  .settings-bar-right {
    flex: 1 1 100%;
    margin-left: 0;
    justify-content: flex-end;
  }
  .settings-group-bar .settings-search-expanded {
    flex: 1 1 100%;
  }
  .settings-seg-btn .v-icon {
    display: none;
  }
}
.settings-result {
  border-bottom: 1px solid #eee;
  cursor: pointer;
}
/* 含 half 字段的小节：half 项两列排布（对标 checkbox_list 的 sm=6），其余项独占整行 */
.settings-fields-2col {
  display: grid;
  grid-template-columns: 1fr 1fr;
  column-gap: 16px;
  align-items: start;
}
.settings-fields-2col > div:not(.settings-field-half) {
  grid-column: 1 / -1;
}
@media (max-width: 599.98px) {
  .settings-fields-2col {
    grid-template-columns: 1fr;
  }
}
.settings-result:hover {
  background: #f5f5f5;
}
/* 键盘焦点要给可见轮廓：原来 :focus 上写 outline:none 会抹掉焦点指示 */
.settings-result:focus-visible {
  background: #f5f5f5;
  outline: 2px solid #1976d2;
  outline-offset: -2px;
}
.theme--dark .settings-result {
  border-bottom-color: #424242;
}
.theme--dark .settings-result:hover {
  background: #303030;
}
.theme--dark .settings-result:focus-visible {
  background: #303030;
  outline-color: #90caf9;
}
[id^="f-"],
[id^="sec-"] {
  scroll-margin-top: calc(var(--settings-bar-top, 56px) + 110px);
}
@keyframes field-flash {
  0% {
    background: #fff59d;
  }
  100% {
    background: transparent;
  }
}
.field-flash {
  animation: field-flash 1.4s ease-out 2;
  border-radius: 6px;
}
.settings-savebar {
  position: sticky;
  bottom: 0;
  z-index: 1;
  display: flex;
  align-items: center;
  /* 窄屏计数位数大时允许换行，避免横排溢出 */
  flex-wrap: wrap;
  min-height: 56px;
  padding: 8px 24px;
  background: #fff;
  border-top: 1px solid #e0e0e0;
}
.settings-savebar-status {
  display: inline-flex;
  align-items: center;
  flex: 0 0 auto;
  margin-left: -6px;
  padding: 4px 6px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  font: inherit;
  color: inherit;
  text-align: left;
}
.settings-savebar-status.is-clickable {
  cursor: pointer;
}
.settings-savebar-status.is-clickable:hover {
  background: rgba(255, 152, 0, 0.12);
}
.settings-savebar-status:focus-visible {
  outline: 2px solid #1976d2;
  outline-offset: 2px;
}
.theme--dark .settings-savebar-status:focus-visible {
  outline-color: #90caf9;
}
.settings-savebar-actions {
  flex: 0 0 100%;
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}
.theme--dark .settings-savebar {
  background: #1e1e1e;
  border-top-color: #424242;
}
.settings-page-root {
  padding-bottom: 24px;
}
.settings-page-root .v-card {
  border-radius: 16px;
}

/* 设置页提示按钮 - 自定义背景色 + 大圆角，覆盖 Vuetify 默认样式 */
.settings-hint-btn,
.settings-hint-btn.v-btn--flat,
.settings-hint-btn.v-btn--is-elevated,
.settings-hint-btn:not(.v-btn--text):not(.v-btn--outlined) {
  background-color: #003153 !important;
  background: #003153 !important;
  border-radius: 9999px !important;
  -webkit-border-radius: 9999px !important;
  border-color: #003153 !important;
  color: #ffffff !important;
  padding-left: 24px !important;
  padding-right: 24px !important;
  box-shadow: none !important;
  min-height: 36px !important;
  height: 36px !important;
  overflow: hidden !important;
}

/* 覆盖 Vuetify v-btn 内部伪元素背景层（其默认会生成渐变/着色层叠加在按钮上） */
.settings-hint-btn::before,
.settings-hint-btn::after,
.settings-hint-btn .v-btn__content::before,
.settings-hint-btn .v-btn__content::after {
  background-color: transparent !important;
  background: transparent !important;
  border-radius: 9999px !important;
}

/* 覆盖 Vuetify 按钮背景层（部分版本使用 .v-btn__background / .v-btn__overlay） */
.settings-hint-btn > .v-btn__background,
.settings-hint-btn .v-btn__overlay {
  background-color: transparent !important;
  border-radius: 9999px !important;
}

/* 交互状态也强制使用同样的背景和圆角 */
.settings-hint-btn:hover,
.settings-hint-btn:focus,
.settings-hint-btn:active,
.settings-hint-btn:focus-within,
.settings-hint-btn.is-active {
  background-color: #001e34 !important;
  background: #001e34 !important;
  border-radius: 9999px !important;
  border-color: #001e34 !important;
  color: #ffffff !important;
}

/* 内部图标和文字颜色保持白色 */
.settings-hint-btn .v-btn__content,
.settings-hint-btn .v-btn__content * {
  color: #ffffff !important;
}

.thanks-heart-icon {
  animation: thanks-to-heartbeat 1.2s ease-in-out infinite;
}

@keyframes thanks-to-heartbeat {
  0%, 100% { transform: scale(1); }
  50% { transform: scale(1.25); }
}

.thanks-to-section {
  position: relative;
  padding: 12px 10px;
  border-radius: 14px;
  background-color: rgba(223, 219, 214, 0.25);
  text-align: center;
  overflow: hidden;
}

.thanks-to-section::before {
  content: "";
  position: absolute;
  inset: 0;
  background-image: url('/static/images/star.svg');
  background-repeat: no-repeat;
  background-position: center;
  background-size: cover;
  opacity: 0.9;
  pointer-events: none;
}

.thanks-to-desc,
.thanks-to-names {
  position: relative;
  z-index: 1;
}

.thanks-to-desc {
  margin-bottom: 8px;
  color: #ff7300;
  font-weight: bold;
}

.thanks-to-names {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 6px;
}

.thanks-to-chip {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 999px;
  background: #005692e0;
  font-size: 13px;
  color: #fff;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.15);
}

.device-item {
  border: 1.5px dashed rgba(0, 0, 0, 0.8);
  border-radius: 6px;
  padding: 15px 4px 15px;
}
.theme--dark .device-item {
  border-color: rgba(255, 255, 255, 0.8);
}
</style>
