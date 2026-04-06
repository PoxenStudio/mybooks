<template>
  <div>
    <v-card class="my-2 elevation-4" v-for="card in cards" :key="card.title">
      <v-card-title @click="card.show = !card.show">
        <v-btn @click.once="card.show = !card.show" icon>
          <v-icon>{{
            card.show ? "keyboard_arrow_down" : "keyboard_arrow_up"
          }}</v-icon>
        </v-btn>
        {{ $t(card.title) }}
      </v-card-title>
      <v-expand-transition>
        <!-- v-card-text的padding导致动画收起时卡顿，置为 0，内部用一个div来控制-->
        <v-card-text v-show="card.show" style="padding: 0">
          <div style="padding: 0 16px 16px">
            <p v-if="card.subtitle" class="">{{ $t(card.subtitle) }}</p>
            <template v-if="card.tips">
              <p v-for="t in card.tips" :key="t.text">
                {{ $t(t.text) }}
                <a v-if="t.link" target="_blank" :href="t.link">{{
                  $t("settings.link")
                }}</a>
              </p>
            </template>

            <template v-for="f in card.fields">
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
                :key="f.key + '-textarea'"
                :label="$t(f.label)"
              ></v-textarea>
              <v-select
                small
                v-else-if="f.type === 'select'"
                :prepend-icon="f.icon"
                v-model="settings[f.key]"
                :items="f.items"
                :key="f.key + '-select'"
                :label="$t(f.label)"
              >
              </v-select>
              <v-select
                small
                v-else-if="f.type === 'select_image'"
                :prepend-icon="f.icon"
                v-model="settings[f.key]"
                :items="f.items"
                :key="f.key + '-select_image'"
                :label="$t(f.label)"
              >
                <template #item="{ item }">
                  <v-img
                    :src="`${site_url}/logo/${item.image_file}.ico`"
                    max-width="32"
                    max-height="32"
                  />
                </template>
                <template #selection="{ item }">
                  <v-img
                    :src="`${site_url}/logo/${item.image_file}.ico`"
                    max-width="32"
                    max-height="32"
                  />
                </template>
              </v-select>
              <template
                v-else-if="f.type === 'meta_sources'"
                :key="f.key + '-meta_sources'"
              >
                <v-select
                  small
                  ref="metaSourceSelect"
                  v-model="settings['META_SELECTED_SOURCES']"
                  :items="metaSourceItems"
                  :label="$t(f.label)"
                  :prepend-icon="f.icon"
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
                </v-select>
              </template>
              <v-text-field
                v-else
                :prepend-icon="f.icon"
                v-model="settings[f.key]"
                :key="f.key + '-text'"
                :label="$t(f.label)"
                type="text"
              ></v-text-field>
            </template>

            <template v-for="b in card.buttons">
              <v-btn :key="b.label" @click="run(b.action)" color="primary"
                ><v-icon>{{ b.icon }}</v-icon
                >{{ $t(b.label) }}</v-btn
              >
            </template>

            <template v-for="g in card.groups">
              <v-checkbox
                :key="g.label"
                small
                hide-details
                v-model="settings[g.key]"
                :label="$t(g.label)"
                :prepend-icon="g.icon"
              >
              </v-checkbox>
              <template v-if="settings[g.key]">
                <template v-for="f in g.fields">
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
                  <v-text-field
                    v-else
                    :prepend-icon="f.icon"
                    v-model="settings[f.key]"
                    :key="f.key + '-text'"
                    :label="$t(f.label)"
                    type="text"
                  ></v-text-field>
                </template>
              </template>
            </template>

            <template v-if="card.show_friends">
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
                <v-col class="pa-0" cols="9">
                  <v-text-field
                    flat
                    small
                    hide-details
                    single-line
                    v-model="friend.href"
                    :label="$t('settings.link')"
                    type="text"
                    append-outer-icon="delete"
                    @click:append-outer="settings.FRIENDS.splice(idx, 1)"
                  ></v-text-field>
                </v-col>
              </v-row>
              <v-row>
                <v-col align="center">
                  <v-btn
                    color="primary"
                    @click="settings.FRIENDS.push({ text: '', href: '' })"
                    ><v-icon>add</v-icon>{{ $t("settings.add") }}</v-btn
                  >
                </v-col>
              </v-row>
            </template>

            <template v-if="card.show_devices">
              <v-row
                v-for="(device, idx) in settings.DEVICES"
                :key="'device-' + idx"
              >
                <v-col class="py-0" cols="2">
                  <v-text-field
                    flat
                    small
                    hide-details
                    single-line
                    v-model="device.name"
                    :label="$t('settings.device_name')"
                    type="text"
                    maxlength="64"
                  ></v-text-field>
                </v-col>
                <v-col class="py-0" cols="2">
                  <v-select
                    flat
                    small
                    hide-details
                    single-line
                    v-model="device.type"
                    :items="deviceTypes"
                    :label="$t('settings.device_type')"
                  >
                  </v-select>
                </v-col>
                <template v-if="device.type === 'kindle'">
                  <v-col class="py-0" cols="6">
                    <v-text-field
                      flat
                      small
                      hide-details
                      single-line
                      v-model="device.mailbox"
                      :label="$t('settings.device_mailbox')"
                      type="email"
                      placeholder="user@kindle.com"
                    ></v-text-field>
                  </v-col>
                </template>
                <template v-else>
                  <v-col class="py-0" cols="2">
                    <v-text-field
                      flat
                      small
                      hide-details
                      single-line
                      v-model="device.ip"
                      :label="$t('settings.device_ip')"
                      type="text"
                    ></v-text-field>
                  </v-col>
                  <v-col class="py-0" cols="2">
                    <v-text-field
                      flat
                      small
                      hide-details
                      single-line
                      v-model.number="device.port"
                      :label="$t('settings.device_port')"
                      type="number"
                    ></v-text-field>
                  </v-col>
                  <v-col class="py-0" cols="2">
                    <v-select
                      flat
                      small
                      hide-details
                      single-line
                      v-model="device.schema"
                      :items="deviceSchemas"
                      :label="$t('settings.device_schema')"
                    >
                    </v-select>
                  </v-col>
                </template>
                <v-col class="py-0" cols="1" align-self="end">
                  <v-btn icon small @click="settings.DEVICES.splice(idx, 1)">
                    <v-icon>delete</v-icon>
                  </v-btn>
                </v-col>
              </v-row>
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
                    <v-icon>add</v-icon>{{ $t("settings.add") }}
                  </v-btn>
                </v-col>
              </v-row>
            </template>

            <template v-if="card.show_bookbarn">
              <p>{{ $t("settings.book_barn_description") }}</p>
              <v-checkbox
                small
                hide-details
                v-model="settings['ENABLE_BOOKBARN']"
                :key="'ENABLE_BOOKBARN'"
                :label="$t('settings.bookbarn_enable')"
              ></v-checkbox>
              <v-text-field
                flat
                small
                v-model="settings['BOOKBARN_TOKEN']"
                :label="$t('settings.bookbarn_token')"
                type="text"
                :disabled="true"
              ></v-text-field>
              <v-btn
                color="primary"
                :disabled="!settings['ENABLE_BOOKBARN'] || appliedToken"
                style="margin-bottom: 24px"
                @click="apply_bookbarn_token"
              >
                <v-icon>key</v-icon>{{ $t("settings.bookbarn_apply_token") }}
              </v-btn>
              <v-checkbox
                small
                hide-details
                v-model="settings['ENABLE_RECEIVING_BOOKS']"
                :key="'ENABLE_RECEIVING_BOOKS'"
                :label="$t('settings.enable_receiving_books')"
                :disabled="!settings['ENABLE_BOOKBARN']"
              >
              </v-checkbox>
              <v-select
                small
                :prepend-icon="clock"
                v-model="settings['BOOKBARN_COLLECTION_HOUR']"
                :disabled="
                  !settings['ENABLE_BOOKBARN'] ||
                  !settings['ENABLE_RECEIVING_BOOKS']
                "
                :items="card.hours"
                :key="'BOOKBARN_COLLECTION_HOUR'"
                :label="$t('settings.bookbarn_collection_hour')"
              >
              </v-select>
            </template>

            <template v-if="card.show_ai_capabilities">
              <p>{{ $t("settings.ai_capabilities_description") }}</p>
              <v-checkbox
                small
                hide-details
                v-model="settings['AI_ENABLED']"
                :key="'AI_ENABLED'"
                :label="$t('settings.ai_enabled')"
              ></v-checkbox>
              <v-text-field
                :disabled="!settings['AI_ENABLED']"
                :prepend-icon="'mdi-key'"
                v-model="settings['AI_DEEPSEEK_API_KEY']"
                :label="$t('settings.ai_deepseek_api_key')"
                :placeholder="$t('settings.ai_deepseek_api_key_description')"
                type="text"
                :rules="apiKeyRules"
                :maxlength="128"
              ></v-text-field>
              <v-text-field
                :prepend-icon="'mdi-key'"
                v-model="settings['AI_MCP_TOKEN']"
                :label="$t('settings.ai_mcp_token')"
                type="text"
                :append-icon="'mdi-refresh'"
                @click:append="generateMCPToken"
                readonly
              ></v-text-field>
            </template>

            <template v-if="card.show_socials">
              <p>{{ $t("settings.socials_description") }}</p>
              <v-combobox
                v-model="settings.SOCIALS"
                :items="sns_items"
                :label="$t('settings.select_socials')"
                hide-selected
                multiple
                small-chips
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
                      >close</v-icon
                    >
                  </v-chip>
                </template>
              </v-combobox>
              <v-row v-for="s in settings.SOCIALS" :key="'social-' + s.value">
                <v-col class="py-0" cols="12" sm="2">
                  <v-subheader
                    class="px-0 pt-4"
                    :class="$vuetify.breakpoint.smAndUp ? 'float-right' : ''"
                  >
                    {{ s.text }} (<a @click="show_sns_config(s)">{{
                      $t("settings.description")
                    }}</a
                    >)
                  </v-subheader>
                </v-col>
                <v-col class="py-0" cols="12" sm="3">
                  <v-text-field
                    small
                    hide-details
                    single-line
                    v-model="
                      settings['SOCIAL_AUTH_' + s.value.toUpperCase() + '_KEY']
                    "
                    :label="Key"
                    placeholder="Key/AppID"
                    type="text"
                  ></v-text-field>
                </v-col>
                <v-col class="py-0" cols="12" sm="7">
                  <v-text-field
                    small
                    hide-details
                    single-line
                    v-model="
                      settings[
                        'SOCIAL_AUTH_' + s.value.toUpperCase() + '_SECRET'
                      ]
                    "
                    :label="Secert"
                    placeholder="Secret"
                    type="text"
                  ></v-text-field>
                </v-col>
              </v-row>
            </template>

            <template v-if="card.show_trash">
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
                  <v-icon>delete</v-icon>{{ $t("settings.trash_clear_button") }}
                </v-btn>
              </div>
            </template>
            <template v-if="card.show_ssl">
              <ssl-manager />
            </template>
          </div>
        </v-card-text>
      </v-expand-transition>
    </v-card>

    <v-dialog v-model="trashConfirmDialog" max-width="400" persistent>
      <v-card>
        <v-card-title class="headline">{{
          $t("settings.trash_clear_confirm_title")
        }}</v-card-title>
        <v-card-text>{{
          $t("settings.trash_clear_confirm_message")
        }}</v-card-text>
        <v-card-actions>
          <v-spacer></v-spacer>
          <v-btn text @click="trashConfirmDialog = false">{{
            $t("common.cancel")
          }}</v-btn>
          <v-btn color="red" dark @click="clearTrash">{{
            $t("settings.trash_clear_confirm_button")
          }}</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <br />
    <div class="text-center">
      <p>{{ $t("settings.save_hints") }}</p>
      <v-btn color="primary" @click="save_settings">{{
        $t("settings.save")
      }}</v-btn>
    </div>
  </div>
</template>

<script>
import SSLManager from "~/components/SSLManager.vue";
export default {
  components: {
    "ssl-manager": SSLManager,
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
      { text: this.$t("settings.device_type_dangdang"), value: "dangdang" },
      { text: "Kindle", value: "kindle" },
      { text: "PureLibro", value: "purelibro" },
    ];

    this.cards = [
      {
        show: false,
        title: "settings.basic_info",
        fields: [
          { icon: "home", key: "site_title", label: "settings.site_title" },
          {
            icon: "info",
            key: "site_icon",
            label: "settings.site_icon",
            type: "select_image",
            items: Array.from({ length: 9 }, (_, i) => ({
              image_file: "favicon_" + i.toString(),
              value: "favicon_" + i.toString(),
            })),
          },
          {
            icon: "mdi-copyright",
            key: "HEADER",
            label: "settings.site_header",
            type: "textarea",
          },
          {
            icon: "mdi-copyright",
            key: "FOOTER",
            label: "settings.site_footer",
            type: "textarea",
          },
          {
            icon: "language",
            key: "site_language",
            label: "settings.language_switch",
            type: "select",
            items: [
              { text: "简体中文", value: "zh" },
              { text: "English", value: "en" },
            ],
          },
          {
            icon: "palette",
            key: "site_theme",
            label: "settings.theme_switch",
            type: "select",
            items: [
              { text: this.$t("settings.light_color"), value: "light" },
              { text: this.$t("settings.dark_color"), value: "dark" },
            ],
          },
          {
            icon: "home",
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
        ],
        groups: [
          {
            key: "INVITE_MODE",
            label: "settings.private_library_mode",
            fields: [
              {
                icon: "lock",
                key: "INVITE_CODE",
                label: "settings.access_code",
              },
              {
                icon: "person",
                key: "INVITE_MESSAGE",
                type: "textarea",
                label: "settings.invite_message",
              },
            ],
          },
        ],
      },
      {
        show: false,
        title: "settings.user_settings",
        fields: [
          {
            icon: "mdi-read",
            key: "ALLOW_GUEST_READ",
            label: "settings.allow_guest_read",
            type: "checkbox",
          },
          {
            icon: "mdi-download",
            key: "ALLOW_GUEST_DOWNLOAD",
            label: "settings.allow_guest_download",
            type: "checkbox",
          },
          {
            icon: "mdi-upload",
            key: "ALLOW_GUEST_UPLOAD",
            label: "settings.allow_guest_upload",
            type: "checkbox",
          },
          {
            icon: "mdi-send",
            key: "ALLOW_GUEST_PUSH",
            label: "settings.allow_guest_push",
            type: "checkbox",
          },
          {
            icon: "mdi-book-multiple",
            key: "ALLOW_NEW_USER_MANAGE_BOOK",
            label: "settings.allow_new_user_manage_book",
            type: "checkbox",
          },
          {
            icon: "mdi-tablet-cellphone",
            key: "ALLOW_NEW_USER_PUSH_BOOK",
            label: "settings.allow_new_user_push_book",
            type: "checkbox",
          },
          {
            icon: "info",
            key: "ALLOW_READ_RANGE_SETTING",
            label: "settings.allow_read_range_setting",
            type: "checkbox",
          },
        ],
        groups: [
          {
            icon: "mdi-at",
            key: "ALLOW_REGISTER",
            label: "settings.allow_guest_register",
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
          },
        ],
      },
      {
        show: false,
        title: "settings.book_barn_service",
        fields: [],
        buttons: [],
        hours: Array.from({ length: 24 }, (_, i) => ({
          text: i.toString(),
          value: i.toString(),
        })),
        show_bookbarn: true,
      },
      {
        show: false,
        title: "settings.ai_capability",
        fields: [],
        buttons: [],
        show_ai_capabilities: true,
      },
      {
        show: false,
        title: "settings.social_network_login",
        fields: [],
        show_socials: true,
      },
      {
        show: false,
        title: "settings.email_service",
        subtitle: "settings.email_service_description",
        fields: [
          { icon: "email", key: "smtp_server", label: "settings.smtp_server" },
          {
            icon: "person",
            key: "smtp_username",
            label: "settings.smtp_username",
          },
          {
            icon: "lock",
            key: "smtp_password",
            label: "settings.smtp_password",
          },
          {
            icon: "info",
            key: "smtp_encryption",
            label: "settings.smtp_encryption",
            type: "select",
            items: [
              { text: "SSL", value: "SSL" },
              { text: "TLS", value: "TLS" },
            ],
          },
        ],
        buttons: [
          { icon: "email", label: "settings.test_email", action: "test_email" },
        ],
      },
      {
        show: false,
        title: "settings.book_tags",
        subtitle: "settings.book_tags_description",
        fields: [
          {
            icon: "person",
            key: "BOOK_NAV",
            type: "textarea",
            label: "settings.book_nav",
          },
        ],
      },
      {
        show: false,
        title: "settings.friend_links",
        fields: [],
        show_friends: true,
      },

      {
        show: false,
        title: "settings.device_mgt",
        subtitle: "settings.device_mgt_description",
        fields: [],
        show_devices: true,
      },

      {
        show: false,
        title: "settings.internet_book_sources",
        fields: [
          {
            icon: "mdi-web-sync",
            key: "auto_fill_meta",
            label: "settings.auto_fill_meta",
            type: "checkbox",
          },
          {
            icon: "mdi-source-branch",
            key: "META_SELECTED_SOURCES",
            label: "settings.meta_selected_source",
            type: "meta_sources",
          },
          {
            icon: "info",
            key: "douban_baseurl",
            label: "settings.douban_baseurl",
          },
          {
            icon: "info",
            key: "douban_apikey",
            label: "settings.douban_api_key",
          },
          {
            icon: "info",
            key: "douban_max_count",
            label: "settings.douban_max_count",
          },
        ],
        tips: [
          {
            text: "settings.douban_plugin_description",
            link: "https://github.com/PoxenStudio/talebook/blob/master/document/README.zh_CN.md#%E5%A6%82%E6%9E%9C%E9%85%8D%E7%BD%AE%E8%B1%86%E7%93%A3%E6%8F%92%E4%BB%B6",
          },
        ],
      },

      {
        show: false,
        title: "settings.import_and_upload",
        fields: [
          {
            icon: "mdi-import",
            key: "scan_upload_path",
            label: "settings.scan_upload_path",
          },
          {
            icon: "info",
            key: "MAX_UPLOAD_SIZE",
            label: "settings.max_upload_size",
          },
          {
            icon: "info",
            key: "CHUNK_UPLOAD_SIZE",
            label: "settings.chunk_upload_size",
          },
          {
            icon: "mdi-shape-plus",
            key: "IMPORT_CATEGORY_WITH_FOLDER",
            label: "settings.category_with_folder",
            type: "checkbox",
          },
        ],
        groups: [
          {
            icon: "mdi-crosshairs-gps",
            key: "IMPORT_BY_INOTIFY",
            label: "settings.auto_importing",
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
        show: false,
        title: "settings.advanced_settings",
        fields: [
          { icon: "home", key: "static_host", label: "settings.cdn_domain" },
          {
            icon: "info",
            key: "BOOK_NAMES_FORMAT",
            label: "settings.book_names_format",
            type: "select",
            items: [
              { text: this.$t("settings.pinyin_directory"), value: "en" },
              { text: this.$t("settings.utf8_directory"), value: "utf8" },
            ],
          },
          {
            icon: "info",
            key: "EPUB_VIEWER",
            label: "settings.epub_viewer",
            type: "select",
            items: [
              { text: this.$t("settings.epubjs"), value: "epubjs.html" },
              { text: this.$t("settings.creader"), value: "creader.html" },
            ],
          },
          {
            icon: "lock",
            key: "cookie_secret",
            label: "settings.cookie_secret",
          },
          { icon: "info", key: "push_title", label: "settings.push_title" },
          { icon: "info", key: "push_content", label: "settings.push_content" },
          {
            icon: "info",
            key: "convert_timeout",
            label: "settings.convert_timeout",
          },
          {
            icon: "mdi-file-pdf-box",
            key: "PDF_TILE_WITH_FILE_NAME",
            label: "settings.pdf_tile_with_file_name",
            type: "checkbox",
          },
          {
            icon: "mdi-bookshelf",
            key: "ENABLE_PHYSICAL_BOOKS",
            label: "settings.enable_physical_books",
            type: "checkbox",
          },
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
          {
            icon: "mdi-cloud-print-outline",
            key: "ENABLE_OPDS_SERVICE",
            label: "settings.enable_opds_service",
            type: "checkbox",
          },
          {
            icon: "mdi-restart",
            key: "autoreload",
            label: "settings.autoreload",
            type: "checkbox",
          },
          {
            icon: "mdi-math-log",
            key: "ENABLE_AUDIO_CONVERSION_LOG",
            label: "settings.enable_audio_conversion_log",
            type: "checkbox",
          },
        ],
      },

      {
        show: false,
        title: "settings.ssl_certificate_management",
        fields: [],
        show_ssl: true,
      },
      {
        show: false,
        title: "settings.trash_management",
        fields: [],
        show_trash: true,
      },
    ];

    this.$backend("/admin/settings").then((rsp) => {
      this.sns_items = rsp.sns;
      this.settings = rsp.settings;
      this.site_url = rsp.site_url;

      if (this.settings) {
        if (this.settings["site_language"] === "") {
          this.settings["site_language"] = this.$i18n.locale;
        }
        if (
          !("site_theme" in this.settings) ||
          this.settings["site_theme"] === ""
        ) {
          this.settings["site_theme"] = "light";
        }
        if (
          !("site_icon" in this.settings) ||
          this.settings["site_icon"] === ""
        ) {
          this.settings["site_icon"] = "favicon_0";
        }
        if (
          !("DEVICES" in this.settings) ||
          !Array.isArray(this.settings["DEVICES"])
        ) {
          this.settings["DEVICES"] = [];
        }
        if (
          !("META_SELECTED_SOURCES" in this.settings) ||
          !Array.isArray(this.settings["META_SELECTED_SOURCES"])
        ) {
          this.settings["META_SELECTED_SOURCES"] = (
            this.settings["META_ALL_SOURCES"] || [
              "douban",
              "baidu",
              "google",
              "amazon",
              "xinhua",
            ]
          ).slice();
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
      }
    });
  },
  data: () => ({
    combo_input: "",
    sns: {},
    sns_items: [],
    settings: {},
    site_url: "",
    cards: [],
    appliedToken: false,
    testingConnection: false,
    deviceTypes: [],
    deviceSchemas: [
      { text: "HTTP", value: "http" },
      { text: "HTTPS", value: "https" },
    ],
    urlRule: (v) => {
      if (!v) return true;
      const pattern = /^https?:\/\/.+/;
      return pattern.test(v) || "Must be a valid HTTP/HTTPS URL";
    },
    apiKeyRules: [
      (v) =>
        !v ||
        /^[a-zA-Z0-9-]*$/.test(v) ||
        "Only alphanumeric characters allowed",
      (v) =>
        !v ||
        (v.length >= 16 && v.length <= 128) ||
        "Length must be between 16 and 128 characters",
    ],
    trashSizes: { trash: 0, upload: 0 },
    trashSizeTexts: { trash: "", upload: "" },
    trashLoading: false,
    trashConfirmDialog: false,
  }),
  computed: {
    metaSourceItems() {
      const allSources = this.settings["META_ALL_SOURCES"] || [
        "douban",
        "baidu",
        "google",
        "amazon",
        "xinhua",
      ];
      return allSources.map((source) => ({
        text: this.$t("settings.meta_source_" + source),
        value: source,
      }));
    },
  },
  mounted() {
    this.fetchTrashSize();
  },
  beforeDestroy() {
    // 页面销毁时移除settings-page类名
    if (process.client) {
      document.body.classList.remove("settings-page");
    }
  },
  methods: {
    save_settings: function () {
      if (this.settings["site_language"] === "") {
        this.settings["site_language"] = "zh";
      }

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

        if (this.settings["site_theme"] !== "") {
          localStorage.setItem("site_theme", this.settings["site_theme"]);
          if (this.settings["site_theme"] === "dark") {
            this.$vuetify.theme.dark = true;
          } else {
            this.$vuetify.theme.dark = false;
          }
        }
      }

      this.$backend("/admin/settings", {
        method: "POST",
        body: JSON.stringify(this.settings),
      }).then((rsp) => {
        if (rsp.err != "ok") {
          this.$alert("error", rsp.msg || this.$t("settings.save_error"));
        } else {
          this.$alert("success", rsp.msg || this.$t("settings.save_success"));
        }
      });
    },
    show_sns_config: function (s) {
      var msg = `${this.$t("settings.sns_config_message", {
        text: s.text,
        link: s.link,
        site_url: this.site_url,
        value: s.value,
      })}`;
      this.$alert("warning", msg);
    },
    apply_bookbarn_token() {
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
    test_email: function () {
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
        .catch((err) => {
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
  },
};
</script>

<style>
.cursor-pointer {
  cursor: pointer;
}
</style>
