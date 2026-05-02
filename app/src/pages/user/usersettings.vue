<template>
  <div>
    <!-- Tab navigation -->
    <v-tabs v-model="activeTab" class="mb-4">
      <v-tab>{{ $t("user.basic_info") }}</v-tab>
      <v-tab>{{ $t("user.device_mgt") }}</v-tab>
    </v-tabs>

    <!-- Tab 1: Basic Info -->
    <v-tabs-items v-model="activeTab">
      <v-tab-item>
        <v-form ref="form" @submit.prevent="save" style="padding: 15px">
          <v-row align="start">
            <!-- Avatar -->
            <v-col cols="3">
              <v-subheader class="pa-0 float-right">{{
                $t("user.avatar")
              }}</v-subheader>
            </v-col>
            <v-col cols="9">
              <div class="d-flex align-center">
                <v-avatar size="80" class="mr-4">
                  <v-img :src="user.avatar" style="cursor: pointer" />
                </v-avatar>
                <v-btn color="primary" @click="showAvatarDialog = true">
                  {{ $t("user.modifyAvatar") }}
                </v-btn>
              </div>

              <!-- Avatar Dialog -->
              <v-dialog v-model="showAvatarDialog" persistent max-width="500">
                <v-card>
                  <v-toolbar flat dense dark color="primary">
                    {{ $t("user.uploadAvatar") }}
                    <v-spacer></v-spacer>
                    <v-btn icon dark @click="closeAvatarDialog">
                      <v-icon>mdi-close</v-icon>
                    </v-btn>
                  </v-toolbar>

                  <v-card-text class="mt-4">
                    <p>{{ $t("user.uploadWarning") }}</p>

                    <v-file-input
                      v-model="avatarImage"
                      accept="image/png,image/jpeg"
                      :label="$t('user.uploadImage')"
                      prepend-icon="mdi-upload"
                      @change="onAvatarChange"
                      :disabled="isUploading"
                    ></v-file-input>

                    <div v-if="avatarUrl" class="cropper-container mt-4">
                      <!-- 关键修改：使用动态组件和延迟加载 -->
                      <img
                        :src="avatarUrl"
                        ref="cropperImage"
                        style="max-width: 100%"
                      />
                      <!-- 加载状态 -->
                      <v-overlay v-if="isCropping" absolute>
                        <v-progress-circular
                          indeterminate
                          size="64"
                        ></v-progress-circular>
                      </v-overlay>
                    </div>
                  </v-card-text>

                  <v-card-actions>
                    <v-spacer></v-spacer>
                    <v-btn
                      color="primary"
                      @click="uploadAvatar"
                      :disabled="!avatarUrl || isUploading"
                    >
                      {{ $t("user.save") }}
                    </v-btn>
                    <v-btn
                      text
                      @click="closeAvatarDialog"
                      :disabled="isUploading"
                    >
                      {{ $t("user.cancel") }}
                    </v-btn>
                  </v-card-actions>
                </v-card>
              </v-dialog>
            </v-col>

            <!-- Username -->
            <v-col cols="3">
              <v-subheader class="pa-0 float-right">{{
                $t("user.username")
              }}</v-subheader>
            </v-col>
            <v-col cols="9">
              <p class="pt-3 mb-0">{{ user.username }}</p>
            </v-col>

            <!-- Email -->
            <v-col cols="3">
              <v-subheader class="pa-0 float-right">{{
                $t("user.email")
              }}</v-subheader>
            </v-col>
            <v-col cols="9">
              <p class="pt-3 mb-0">
                {{ user.email }}
                <a
                  href="#"
                  v-if="!user.is_active"
                  @click.prevent="sendActiveEmail"
                >
                  {{ $t("user.resendActivationEmail") }}
                </a>
              </p>
              <v-checkbox
                v-model="user.extra.allow_sending_mail"
                :label="$t('user.allow_sending_mail')"
                hide-details
                class="mt-0"
              ></v-checkbox>
            </v-col>

            <!-- Password -->
            <v-col cols="3">
              <v-subheader class="pa-0 float-right">{{
                $t("user.password")
              }}</v-subheader>
            </v-col>
            <v-col cols="9">
              <v-subheader class="pa-0">
                <a href="#" @click.stop="show_pass = !show_pass">{{
                  $t("user.modifyPassword")
                }}</a>
              </v-subheader>
              <div v-if="show_pass">
                <v-text-field
                  solo
                  v-model="user.password0"
                  :label="$t('user.currentPassword')"
                  type="password"
                  autocomplete="new-password0"
                  :rules="[rules.pass]"
                ></v-text-field>
                <v-text-field
                  solo
                  v-model="user.password1"
                  :label="$t('user.newPassword')"
                  type="password"
                  autocomplete="new-password1"
                  :rules="[rules.pass]"
                ></v-text-field>
                <v-text-field
                  solo
                  v-model="user.password2"
                  :label="$t('user.confirmPassword')"
                  type="password"
                  autocomplete="new-password2"
                  :rules="[valid]"
                ></v-text-field>
              </div>
            </v-col>

            <!-- Nickname -->
            <v-col cols="3">
              <v-subheader class="pa-0 float-right">{{
                $t("user.nickname")
              }}</v-subheader>
            </v-col>
            <v-col cols="9">
              <v-text-field
                solo
                v-model="user.nickname"
                :label="$t('user.nickname')"
                type="text"
                autocomplete="new-nickname"
                :rules="[rules.nick]"
              ></v-text-field>
            </v-col>

            <!-- Podcast Token -->
            <v-col cols="3">
              <v-subheader class="pa-0 float-right">{{
                $t("user.podcast_token") || "Podcast Token"
              }}</v-subheader>
            </v-col>
            <v-col cols="9">
              <v-text-field
                solo
                v-model="user.podcast_token"
                :label="$t('user.podcast_token_label') || 'Token'"
                type="text"
                readonly
              >
                <template v-slot:prepend>
                  <v-btn
                    color="primary"
                    small
                    @click="generatePodcastToken"
                    rounded
                    >{{ $t("user.generate_token") || "Generate Token" }}</v-btn
                  >
                </template>
              </v-text-field>
            </v-col>

            <!-- VIP Quota -->
            <v-col cols="3" v-if="user.vipquota !== undefined">
              <v-subheader class="pa-0 float-right">{{
                $t("user.vipquota")
              }}</v-subheader>
            </v-col>
            <v-col cols="9" v-if="user.vipquota !== undefined">
              <p class="pt-3 mb-0">{{ user.vipquota }}</p>
            </v-col>

            <!-- VIP Expire -->
            <v-col
              cols="3"
              v-if="user.vip_expire && user.vip_expire.length > 0"
            >
              <v-subheader class="pa-0 float-right">{{
                $t("user.vip_expire")
              }}</v-subheader>
            </v-col>
            <v-col
              cols="9"
              v-if="user.vip_expire && user.vip_expire.length > 0"
            >
              <p class="pt-3 mb-0">{{ user.vip_expire }}</p>
            </v-col>

            <!-- Save Button -->
            <v-col cols="12">
              <div class="text-center">
                <v-btn dark large rounded color="orange" type="submit">{{
                  $t("user.save")
                }}</v-btn>
              </div>
            </v-col>
          </v-row>
        </v-form>
      </v-tab-item>

      <!-- Tab 2: Reading Devices -->
      <v-tab-item>
        <v-card flat class="pa-2">
          <v-card-subtitle class="px-0 text-center">{{
            $t("user.device_mgt_description")
          }}</v-card-subtitle>

          <v-row v-for="(device, idx) in userDevices" :key="'udev-' + idx">
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
              ></v-select>
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
                ></v-select>
              </v-col>
            </template>
            <v-col class="py-0" cols="1" align-self="end">
              <v-btn icon small @click="userDevices.splice(idx, 1)">
                <v-icon>delete</v-icon>
              </v-btn>
            </v-col>
          </v-row>

          <v-row>
            <v-col align="center">
              <v-btn
                color="primary"
                @click="
                  userDevices.push({
                    name: $t('settings.default_reader_name'),
                    type: 'duokan',
                    ip: '',
                    port: 12121,
                    schema: 'http',
                    mailbox: '',
                  })
                "
              >
                <v-icon>add</v-icon>{{ $t("settings.add") }}
              </v-btn>
            </v-col>
          </v-row>

          <v-row class="mt-4">
            <v-col cols="12" class="text-center">
              <v-btn
                dark
                large
                rounded
                color="orange"
                @click="saveDevices"
                :loading="savingDevices"
              >
                {{ $t("user.save") }}
              </v-btn>
            </v-col>
          </v-row>
        </v-card>
      </v-tab-item>
    </v-tabs-items>
  </div>
</template>

<script>
export default {
  data() {
    return {
      activeTab: 0,
      user: {
        username: "",
        email: "",
        nickname: "",
        kindle_email: "",
        avatar: null,
        password0: "",
        password1: "",
        password2: "",
        is_active: false,
        vipquota: undefined,
        vip_expire: "",
        podcast_token: "",
        extra: {
          allow_sending_mail: true
        },
      },
      show_pass: false,
      rules: {
        pass: (v) =>
          v === undefined ||
          v.length === 0 ||
          v.length >= 8 ||
          this.$t("user.password_min_length"),
        nick: (v) =>
          v === undefined ||
          v.length === 0 ||
          v.length >= 2 ||
          this.$t("user.nickname_min_length"),
        email: (v) => {
          const re =
            /^(([^<>()[\]\\.,;:\s@"]+(\.[^<>()[\]\\.,;:\s@"]+)*)|(".+"))@((\[[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\])|(([a-zA-Z\-0-9]+\.)+[a-zA-Z]{2,}))$/;
          return (
            v === undefined ||
            v.length === 0 ||
            re.test(v) ||
            this.$t("user.email_invalid")
          );
        },
      },
      valid: (v) =>
        v === this.user.password1 || this.$t("user.passwordMismatch"),
      showAvatarDialog: false,
      avatarImage: null,
      avatarUrl: null,
      isUploading: false,
      cropper: null,
      isCropping: false,
      // Device management
      userDevices: [],
      savingDevices: false,
      deviceTypes: [],
      deviceSchemas: ["http", "https"],
    };
  },
  async asyncData({ app }) {
    return app.$backend("/user/info?detail=1");
  },
  head() {
    return { title: this.$t("user.user_center") };
  },
  created() {
    this.deviceTypes = [
      { text: this.$t("settings.device_type_duokan"), value: "duokan" },
      { text: this.$t("settings.device_type_ireader"), value: "ireader" },
      { text: this.$t("settings.device_type_hanwang"), value: "hanwang" },
      { text: this.$t("settings.device_type_boox"), value: "boox" },
      { text: this.$t("settings.device_type_dangdang"), value: "dangdang" },
      { text: this.$t("user.kindle") || "Kindle", value: "kindle" },
      { text: "PureLibro", value: "purelibro" },
    ];
    this.init();
  },
  methods: {
    init() {
      this.$store.commit("navbar", true);
      this.$backend("/user/info?detail=1").then((rsp) => {
        if (rsp.user) {
          rsp.user.password0 = "";
          rsp.user.password1 = "";
          rsp.user.password2 = "";
          if (!rsp.user.extra) {
            rsp.user.extra = {};
          }
          if (rsp.user.extra.allow_sending_mail === undefined) {
            rsp.user.extra.allow_sending_mail = true;
          }
          this.user = rsp.user;
        }
      });
      this.$backend("/user/devices").then((rsp) => {
        if (rsp.err === "ok") {
          this.userDevices = rsp.devices || [];
        }
      });
    },
    async onAvatarChange(file) {
      if (!file) {
        this.avatarUrl = null;
        return;
      }

      const { type } = file;
      if (type !== "image/png" && type !== "image/jpeg") {
        this.$alert("error", this.$t("user.avatar_format_error"));
        this.avatarUrl = null;
        return;
      }

      if (file.size > 2 * 1024 * 1024) {
        this.$alert("error", this.$t("user.avatar_size_error"));
        this.avatarUrl = null;
        return;
      }

      this.avatarImage = file;
      this.avatarUrl = URL.createObjectURL(file);

      import("cropperjs")
        .then((module) => {
          const Cropper = module.default;
          import("cropperjs/dist/cropper.css");

          this.$nextTick(() => {
            if (this.$refs.cropperImage) {
              if (this.cropper) {
                this.cropper.destroy();
              }

              try {
                this.cropper = new Cropper(this.$refs.cropperImage, {
                  aspectRatio: 1,
                  viewMode: 1,
                  autoCropArea: 1,
                  movable: true,
                  zoomable: true,
                  rotatable: true,
                  scalable: true,
                  guides: false,
                  highlight: true,
                  cropBoxMovable: true,
                  cropBoxResizable: true,
                  background: false,
                });
              } catch (error) {
                console.error("Failed to initialize cropper:", error);
              }
            }
          });
        })
        .catch((error) => {
          console.error("Failed to load cropperjs:", error);
        });
    },

    async uploadAvatar() {
      if (!this.cropper) {
        this.$alert("error", this.$t("user.avatar_not_specified"));
        return;
      }

      this.isUploading = true;
      this.isCropping = true;

      try {
        await new Promise((resolve) => setTimeout(resolve, 300));

        const canvas = this.cropper.getCroppedCanvas({
          width: 96,
          height: 96,
          fillColor: "#fff",
        });

        const blob = await new Promise((resolve) =>
          canvas.toBlob(resolve, "image/png", 0.9)
        );

        if (!blob) {
          throw new Error(this.$t("user.avatar_crop_failed"));
        }

        const formData = new FormData();
        formData.append("avatar", blob, "avatar.png");

        const rsp = await this.$backend("/user/avatar", {
          method: "POST",
          body: formData,
        });

        if (rsp.err === "ok") {
          this.user.avatar = null;
          this.$alert("success", this.$t("user.avatar_update_success"));
          this.closeAvatarDialog();
          this.user.avatar = `${rsp.avatar_url}?t=${Date.now()}`;
        } else {
          throw new Error(rsp.msg || this.$t("user.avatar_upload_failed"));
        }
      } catch (error) {
        this.$alert(
          "error",
          error.message || this.$t("user.avatar_upload_failed")
        );
      } finally {
        this.isUploading = false;
        this.isCropping = false;
      }
    },
    closeAvatarDialog() {
      this.showAvatarDialog = false;
      this.avatarImage = null;
      this.avatarUrl = null;
      this.isUploading = false;
      this.isCropping = false;
      if (this.cropper) {
        this.cropper.destroy();
        this.cropper = null;
      }
    },
    save() {
      if (!this.$refs.form.validate()) {
        return false;
      }

      const d = {
        password0: this.user.password0,
        password1: this.user.password1,
        password2: this.user.password2,
        nickname: this.user.nickname,
        kindle_email: this.user.kindle_email,
        podcast_token: this.user.podcast_token,
        allow_sending_mail: this.user.extra.allow_sending_mail,
      };

      this.$backend("/user/update", {
        method: "POST",
        body: JSON.stringify(d),
      }).then((rsp) => {
        if (rsp.err !== "ok") {
          this.failmsg = rsp.msg;
        } else {
          this.$store.commit("navbar", true);
          this.$router.push("/");
        }
      });
    },
    generatePodcastToken() {
      const array = new Uint8Array(32);
      window.crypto.getRandomValues(array);
      const token = Array.from(array, (byte) =>
        ("0" + (byte & 0xff).toString(16)).slice(-2)
      ).join("");
      this.$set(this.user, "podcast_token", token);
    },
    sendActiveEmail() {
      this.$backend("/user/active/send").then((rsp) => {
        if (rsp.err === "ok") {
          this.$alert("success", this.$t("user.activationEmailSent"));
        } else {
          this.$alert("danger", rsp.msg);
        }
      });
    },
    saveDevices() {
      this.savingDevices = true;
      this.$backend("/user/devices", {
        method: "POST",
        body: JSON.stringify({ devices: this.userDevices }),
      })
        .then((rsp) => {
          if (rsp.err === "ok") {
            this.$alert(
              "success",
              rsp.msg || this.$t("user.device_save_success")
            );
          } else {
            this.$alert("error", rsp.msg);
          }
        })
        .catch(() => {
          this.$alert("error", this.$t("user.device_save_failed"));
        })
        .finally(() => {
          this.savingDevices = false;
        });
    },
  },
};
</script>

<style scoped>
.cropper-container {
  position: relative;
  min-height: 300px;
  max-height: 400px;
  display: flex;
  justify-content: center;
  align-items: center;
  border: 1px solid #eee;
  border-radius: 4px;
  overflow: hidden;
  background-color: #f5f5f5;
}

.cropper-container >>> .vue-cropper {
  width: 100%;
  min-height: 300px;
  max-height: 60vh;
}
</style>
