<template>
  <div>
    <v-card class="my-2 elevation-4" v-for="card in cards" :key="card.title">
      <v-card-title @click="card.show = !card.show">
        <v-btn @click.once="card.show = !card.show" icon>
          <v-icon>{{ card.show ? 'keyboard_arrow_down' : 'keyboard_arrow_up' }}</v-icon>
        </v-btn>
        {{ $t(card.title) }}
      </v-card-title>
      <v-expand-transition>
        <!-- v-card-text的padding导致动画收起时卡顿，置为 0，内部用一个div来控制-->
        <v-card-text v-show="card.show" style="padding: 0">
          <div style="padding: 0 16px 16px">
            <p v-if="card.subtitle" class="">{{ $t(card.subtitle) }}</p>
            <template v-if="card.tips">
              <p v-for="t in card.tips" :key="t.text">{{ $t(t.text) }} <a v-if="t.link" target="_blank"
                  :href="t.link">{{ $t('settings.link') }}</a></p>
            </template>

            <template v-for="f in card.fields">
              <v-checkbox small hide-details v-if="f.type === 'checkbox'" :prepend-icon="f.icon"
                v-model="settings[f.key]" :key="f.key + '-checkbox'" :label="$t(f.label)"></v-checkbox>
              <v-textarea outlined v-else-if="f.type === 'textarea'" :prepend-icon="f.icon" v-model="settings[f.key]"
                :key="f.key + '-textarea'" :label="$t(f.label)"></v-textarea>
              <v-select small v-else-if="f.type === 'select'" :prepend-icon="f.icon" v-model="settings[f.key]"
                :items="f.items" :key="f.key + '-select'" :label="$t(f.label)"> </v-select>
              <v-select small v-else-if="f.type === 'select_image'" :prepend-icon="f.icon"
                v-model="settings[f.key]" :items="f.items" :key="f.key + '-select_image'" :label="$t(f.label)">
                <template #item="{ item }">
                  <v-img :src="`${site_url}/logo/${item.image_file}.ico`" max-width="32" max-height="32" />
                </template>
                <template #selection="{ item }">
                  <v-img :src="`${site_url}/logo/${item.image_file}.ico`" max-width="32" max-height="32" />
                </template>
              </v-select>
              <v-text-field v-else :prepend-icon="f.icon" v-model="settings[f.key]" :key="f.key + '-text'" :label="$t(f.label)"
                type="text"></v-text-field>
            </template>

            <template v-for="b in card.buttons" :key="b.label">
              <v-btn @click="run(b.action)" color="primary"><v-icon>{{ b.icon }}</v-icon>{{ $t(b.label)
                }}</v-btn>
            </template>

            <template v-for="g in card.groups" :key="g.label">
              <v-checkbox small hide-details v-model="settings[g.key]" :label="$t(g.label)"></v-checkbox>
              <template v-if="settings[g.key]">
                <template v-for="f in g.fields">
                  <v-textarea outlined v-if="f.type === 'textarea'" :prepend-icon="f.icon" v-model="settings[f.key]"
                    :key="f.key" :label="$t(f.label)"></v-textarea>
                  <v-text-field v-else :prepend-icon="f.icon" v-model="settings[f.key]" :key="f.key + '-text'"
                    :label="$t(f.label)" type="text"></v-text-field>
                </template>
              </template>
            </template>

            <template v-if="card.show_friends">
              <v-row v-for="(friend, idx) in settings.FRIENDS" :key="'friend-' + friend.href">
                <v-col class='py-0' cols=3>
                  <v-text-field flat small hide-details single-line v-model="friend.text" :label="$t('settings.name')"
                    type="text"></v-text-field>
                </v-col>
                <v-col class='pa-0' cols=9>
                  <v-text-field flat small hide-details single-line v-model="friend.href" :label="$t('settings.link')"
                    type="text" append-outer-icon="delete"
                    @click:append-outer="settings.FRIENDS.splice(idx, 1)"></v-text-field>
                </v-col>
              </v-row>
              <v-row>
                <v-col align="center">
                  <v-btn color="primary" @click="settings.FRIENDS.push({ text: '', href: '' })"><v-icon>add</v-icon>{{$t('settings.add') }}</v-btn>
                </v-col>
              </v-row>
            </template>

            <template v-if="card.show_bookbarn">
              <p>{{ $t('settings.book_barn_description') }}</p>
              <v-checkbox small hide-details
                v-model="settings['ENABLE_BOOKBARN']" :key="'ENABLE_BOOKBARN'" :label="$t('settings.bookbarn_enable')"></v-checkbox>
              <v-text-field flat small v-model="settings['BOOKBARN_TOKEN']" :label="$t('settings.bookbarn_token')"
                type="text" :disabled="true"></v-text-field>
              <v-btn color="primary" :disabled="!settings['ENABLE_BOOKBARN'] || appliedToken" style="margin-bottom:24px" @click="apply_bookbarn_token">
                <v-icon>key</v-icon>{{ $t('settings.bookbarn_apply_token') }}
              </v-btn>
              <v-checkbox small hide-details v-model="settings['ENABLE_RECEIVING_BOOKS']" :key="'ENABLE_RECEIVING_BOOKS'"
                :label="$t('settings.enable_receiving_books')" :disabled="!settings['ENABLE_BOOKBARN']">
              </v-checkbox>
              <v-select small :prepend-icon="clock" v-model="settings['BOOKBARN_COLLECTION_HOUR']" :disabled="!settings['ENABLE_BOOKBARN']||!settings['ENABLE_RECEIVING_BOOKS']"
                :items=card.hours :key="'BOOKBARN_COLLECTION_HOUR'" :label="$t('settings.bookbarn_collection_hour')"> </v-select>
              <p><strong>{{ $t('settings.book2audio_proxy') }}</strong></p>
              <p>{{ $t('settings.book2audio_proxy_comment') }}</p>
              <v-checkbox small hide-details v-model="settings['USE_BOOKBARN_PROXY']" :key="'USE_BOOKBARN_PROXY'"
                :label="$t('settings.use_bookbarn_proxy')" :disabled="!settings['ENABLE_BOOKBARN']">
              </v-checkbox>
              <v-text-field flat hide-details v-model="settings['BOOK2AUDIO_PROXY']" :disabled="!settings['ENABLE_BOOKBARN'] || settings['USE_BOOKBARN_PROXY']" :label="$t('settings.book2audio_proxy_address')"
                type="text"></v-text-field>
              <v-btn color="primary" :disabled="!settings['ENABLE_BOOKBARN'] || testingConnection" style="margin-bottom:24px" @click="test_audio_connection">
                <v-icon>link</v-icon>{{ $t('settings.book2audio_proxy_test') }}
              </v-btn>
            </template>

            <template v-if="card.show_socials">
              <p>{{ $t('settings.socials_description') }}</p>
              <v-combobox v-model="settings.SOCIALS" :items="sns_items" :label="$t('settings.select_socials')" hide-selected
                multiple small-chips>
                <template v-slot:selection="{ attrs, item, parent, selected }">
                  <v-chip v-bind="attrs" color="green lighten-3" :input-value="selected" label small>
                    <span class="pr-2"> {{ item.text }} </span>
                    <v-icon small @click="parent.selectItem(item)">close</v-icon>
                  </v-chip>
                </template>
              </v-combobox>
              <v-row v-for="s in settings.SOCIALS" :key="'social-' + s.value">
                <v-col class='py-0' cols=12 sm=2>
                  <v-subheader class="px-0 pt-4" :class="$vuetify.breakpoint.smAndUp ? 'float-right' : ''">
                    {{ s.text }} (<a @click="show_sns_config(s)">{{ $t('settings.description') }}</a>)
                  </v-subheader>
                </v-col>
                <v-col class='py-0' cols=12 sm=3>
                  <v-text-field small hide-details single-line
                    v-model="settings['SOCIAL_AUTH_' + s.value.toUpperCase() + '_KEY']" :label="Key"
                    type="text"></v-text-field>
                </v-col>
                <v-col class='py-0' cols=12 sm=7>
                  <v-text-field small hide-details single-line
                    v-model="settings['SOCIAL_AUTH_' + s.value.toUpperCase() + '_SECRET']" :label="Secert"
                    type="text"></v-text-field>
                </v-col>
              </v-row>
            </template>

            <template v-if="card.show_ssl">
              <ssl-manager />
            </template>
          </div>
        </v-card-text>
      </v-expand-transition>
    </v-card>

    <br />
    <div class="text-center">
      <v-btn color="primary" @click="save_settings">{{ $t('settings.save') }}</v-btn>
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
    this.cards = [
      {
        show: false,
        title: "settings.basic_info",
        fields: [
          {
            icon: "language", key: "site_language", label: "settings.language_switch", type: 'select',
            items: [{ text: '简体中文', value: "zh" }, { text: 'English', value: "en" }]
          },
          {
            icon: "palette", key: "site_theme", label: "settings.theme_switch", type: 'select',
            items: [{ text: this.$t('settings.light_color'), value: "light" }, { text: this.$t('settings.dark_color'), value: "dark" }]
          },
          { icon: "home", key: "site_title", label: "settings.site_title", },
          { icon: "info", key: "site_icon", label: "settings.site_icon", type: 'select_image',
            items: Array.from({ length: 9 }, (_, i) => ({ image_file: "favicon_" + i.toString(), value: "favicon_" + i.toString() }))
          },
          { icon: "mdi-copyright", key: "HEADER", label: "settings.site_header", type: 'textarea' },
          { icon: "mdi-copyright", key: "FOOTER", label: "settings.site_footer", type: 'textarea' }
        ],
        groups: [
          {
            key: "INVITE_MODE",
            label: "settings.private_library_mode",
            fields: [
              { icon: "lock", key: "INVITE_CODE", label: "settings.access_code" },
              { icon: "person", key: "INVITE_MESSAGE", type: 'textarea', label: "settings.invite_message" },
            ],
          },
        ],
      },
      {
        show: false,
        title: "settings.user_settings",
        fields: [
          { icon: "", key: "ALLOW_GUEST_READ", label: "settings.allow_guest_read", type: 'checkbox' },
          { icon: "", key: "ALLOW_GUEST_DOWNLOAD", label: "settings.allow_guest_download", type: 'checkbox' },
          { icon: "", key: "ALLOW_GUEST_UPLOAD", label: "settings.allow_guest_upload", type: 'checkbox' },
          { icon: "", key: "ALLOW_GUEST_PUSH", label: "settings.allow_guest_push", type: 'checkbox' },
        ],
        groups: [
          {
            key: "ALLOW_REGISTER",
            label: "settings.allow_guest_register",
            fields: [
              { icon: "info", key: "SIGNUP_MAIL_TITLE", label: "settings.signup_mail_title" },
              { icon: "info", key: "SIGNUP_MAIL_CONTENT", label: "settings.signup_mail_content", type: 'textarea' },
              { icon: "info", key: "RESET_MAIL_TITLE", label: "settings.reset_mail_title" },
              { icon: "info", key: "RESET_MAIL_CONTENT", label: "settings.reset_mail_content", type: 'textarea' },
            ],
          },
        ],
      },
      {
        show: false,
        title: 'settings.book_barn_service',
        fields: [],
        buttons: [],
        hours: Array.from({ length: 24 }, (_, i) => ({ text: i.toString(), value: i.toString() })),
        show_bookbarn: true,
      },
      {
        show: false,
        title: 'settings.social_network_login',
        fields: [],
        show_socials: true,
      },
      {
        show: false,
        title: "settings.email_service",
        subtitle: 'settings.email_service_description',
        fields: [
          { icon: "email", key: "smtp_server", label: "settings.smtp_server" },
          { icon: "person", key: "smtp_username", label: "settings.smtp_username" },
          { icon: "lock", key: "smtp_password", label: "settings.smtp_password" },
          {
            icon: "info", key: "smtp_encryption", label: "settings.smtp_encryption", type: 'select',
            items: [{ text: "SSL", value: "SSL" }, { text: "TLS", value: "TLS" }]
          },
        ],
        buttons: [
          { icon: "email", label: "settings.test_email", action: "test_email" },
        ],
      },
      {
        show: false,
        title: "settings.book_tags",
        subtitle: 'settings.book_tags_description',
        fields: [
          { icon: "person", key: "BOOK_NAV", type: 'textarea', label: "book_nav" },
        ],
      },
      {
        show: false,
        title: 'settings.friend_links',
        fields: [],
        show_friends: true,
      },

      {
        show: false,
        title: "settings.internet_book_sources",
        fields: [
          { icon: "", key: "auto_fill_meta", label: "settings.auto_fill_meta", type: 'checkbox' },
          { icon: "info", key: "douban_baseurl", label: "settings.douban_baseurl" },
          { icon: "info", key: "douban_max_count", label: "settings.douban_max_count" },
        ],
        tips: [
          {
            text: "settings.douban_plugin_description",
            link: "https://github.com/HorkyChen/talebook/blob/master/document/README.zh_CN.md#%E5%A6%82%E6%9E%9C%E9%85%8D%E7%BD%AE%E8%B1%86%E7%93%A3%E6%8F%92%E4%BB%B6",
          }
        ],
      },
      {
        show: false,
        title: "settings.advanced_settings",
        fields: [
          { icon: "home", key: "static_host", label: "settings.cdn_domain" },
          {
            icon: "info", key: "BOOK_NAMES_FORMAT", label: "settings.book_names_format", type: 'select',
            items: [{ text: this.$t('settings.pinyin_directory'), value: "en" }, { text: this.$t('settings.utf8_directory'), value: "utf8" }]
          },
          { icon: "info", key: "EPUB_VIEWER", label: "settings.epub_viewer", type: 'select',
            items: [{ text: this.$t('settings.epubjs'), value: "epubjs.html" }, { text: this.$t('settings.creader'), value: "creader.html" }]
          },
          { icon: "info", key: "avatar_service", label: "settings.avatar_service" },
          { icon: "info", key: "MAX_UPLOAD_SIZE", label: "settings.max_upload_size" },
          { icon: "info", key: "CHUNK_UPLOAD_SIZE", label: "settings.chunk_upload_size" },
          { icon: "lock", key: "cookie_secret", label: "settings.cookie_secret" },
          { icon: "info", key: "scan_upload_path", label: "settings.scan_upload_path" },
          { icon: "info", key: "push_title", label: "settings.push_title" },
          { icon: "info", key: "push_content", label: "settings.push_content" },
          { icon: "info", key: "convert_timeout", label: "settings.convert_timeout" },
          { icon: "", key: "autoreload", label: "settings.autoreload", type: 'checkbox' },
          { icon: "", key: "ENABLE_PHYSICAL_BOOKS", label: "settings.enable_physical_books", type: 'checkbox' },
        ]
      },

      {
        show: false,
        title: "settings.ssl_certificate_management",
        fields: [],
        show_ssl: true,
      },
    ];

    this.$backend("/admin/settings").then(rsp => {
      this.sns_items = rsp.sns;
      this.settings = rsp.settings;
      this.site_url = rsp.site_url;

      if (this.settings) {
        if (this.settings['site_language'] === '') {
          this.settings['site_language'] = this.$i18n.locale;
        }
        if (!('site_theme' in this.settings) || this.settings['site_theme'] === '') {
          this.settings['site_theme'] = "light";
        }
        if (!('site_icon' in this.settings) || this.settings['site_icon'] === '') {
          this.settings['site_icon'] = "favicon_0";
        }
        if (process.client && this.settings['MAX_UPLOAD_SIZE'] !== '') {
          localStorage.setItem('max_upload_size', this.settings['MAX_UPLOAD_SIZE']);
        }
        if (process.client && this.settings['CHUNK_UPLOAD_SIZE'] !== '') {
          localStorage.setItem('chunk_upload_size', this.settings['CHUNK_UPLOAD_SIZE']);
        }
        var m = {}
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
  }),
  methods: {
    save_settings: function () {
      if (this.settings['site_language'] === '') {
        this.settings['site_language'] = "zh";
      }

      if (this.settings['site_language'] !== '') {
        this.$i18n.locale = this.settings['site_language'];
      }

      if (process.client && this.settings['MAX_UPLOAD_SIZE'] !== '') {
        localStorage.setItem('max_upload_size', this.settings['MAX_UPLOAD_SIZE']);
      }

      if (process.client && this.settings['CHUNK_UPLOAD_SIZE'] !== '') {
        localStorage.setItem('chunk_upload_size', this.settings['CHUNK_UPLOAD_SIZE']);
      }

      if (process.client && this.settings['site_theme'] !== '') {
        localStorage.setItem('site_theme', this.settings['site_theme']);
        if (this.settings['site_theme'] === 'dark') {
          this.$vuetify.theme.dark = true;
        } else {
          this.$vuetify.theme.dark = false;
        }
      }
      this.$backend("/admin/settings", {
        method: 'POST',
        body: JSON.stringify(this.settings),
      })
        .then(rsp => {
          if (rsp.err != 'ok') {
            this.$alert('error', this.$t('settings.save_error'));
          } else {
            this.$alert('success', this.$t('settings.save_success'));
          }
        });
    },
    show_sns_config: function (s) {
      var msg = `${this.$t('settings.sns_config_message', { text: s.text, link: s.link, site_url: this.site_url, value: s.value })}`;
      this.$alert("success", msg);
    },
    apply_bookbarn_token() {
      this.appliedToken = true;
      this.$backend("/admin/bookbarn/token/apply", {
        method: 'POST',
        body: JSON.stringify(this.settings),
      }).then(rsp => {
        if (rsp.err != 'ok') {
          this.appliedToken = false;
          this.$alert('error', rsp.msg);
        } else {
          this.$alert('success', rsp.msg);
          this.settings['BOOKBARN_TOKEN'] = rsp.token;
        }
      });
    },
    test_audio_connection: function () {
      this.testingConnection = true;
      this.$backend("/admin/audio/test", {
        method: 'POST',
        body: JSON.stringify({
          proxy: this.settings['BOOK2AUDIO_PROXY'] || '',
          use_bookbarn_proxy: this.settings['USE_BOOKBARN_PROXY'] || false,
        }),
      }).then(rsp => {
        this.testingConnection = false;
        if (rsp.err != 'ok') {
          this.$alert('error', rsp.msg);
        } else {
          this.$alert('success', rsp.msg);
        }
      }).catch(err => {
        this.testingConnection = false;
      });
    },
    test_email: function () {
      var data = new URLSearchParams();
      data.append('smtp_server', this.settings['smtp_server']);
      data.append('smtp_username', this.settings['smtp_username']);
      data.append('smtp_password', this.settings['smtp_password']);
      data.append('smtp_encryption', this.settings['smtp_encryption']);
      this.$backend("/admin/testmail", {
        method: 'POST',
        body: data,
      }).then(rsp => {
        if (rsp.err != 'ok') {
          this.$alert('error', rsp.msg);
        } else {
          this.$alert('success', rsp.msg);
        }
      });
    },
    run: function (func) {
      this[func]();
    },
  },
}
</script>

<style>
.cursor-pointer {
  cursor: pointer;
}
</style>
