<template>
  <v-form ref="form" @submit.prevent="save">
    <v-row align="start">
      <!-- Avatar -->
      <v-col cols="3">
        <v-subheader class="pa-0 float-right">{{ $t('user.avatar') }}</v-subheader>
      </v-col>
      <v-col cols="9">
        <div class="d-flex align-center">
          <v-avatar size="80" class="mr-4">
            <v-img :src="user.avatar" style="cursor: pointer"/>
          </v-avatar>
          <v-btn color="primary" @click="showAvatarDialog = true">
            {{ $t('user.modifyAvatar') }}
          </v-btn>
        </div>

        <!-- Avatar Dialog -->
        <v-dialog v-model="showAvatarDialog" persistent max-width="500">
          <v-card>
            <v-toolbar flat dense dark color="primary">
              {{ $t('user.uploadAvatar') }}
              <v-spacer></v-spacer>
              <v-btn icon dark @click="closeAvatarDialog">
                <v-icon>mdi-close</v-icon>
              </v-btn>
            </v-toolbar>

            <v-card-text class="mt-4">
              <p>{{ $t('user.uploadWarning') }}</p>

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
                <img :src="avatarUrl" ref="cropperImage" style="max-width: 100%">
                <!-- 加载状态 -->
                <v-overlay v-if="isCropping" absolute>
                  <v-progress-circular indeterminate size="64"></v-progress-circular>
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
                {{ $t('user.save') }}
              </v-btn>
              <v-btn text @click="closeAvatarDialog" :disabled="isUploading">
                {{ $t('user.cancel') }}
              </v-btn>
            </v-card-actions>
          </v-card>
        </v-dialog>
      </v-col>

      <!-- Username -->
      <v-col cols="3">
        <v-subheader class="pa-0 float-right">{{ $t('user.username') }}</v-subheader>
      </v-col>
      <v-col cols="9">
        <p class="pt-3 mb-0">{{ user.username }}</p>
      </v-col>

      <!-- Email -->
      <v-col cols="3">
        <v-subheader class="pa-0 float-right">{{ $t('user.email') }}</v-subheader>
      </v-col>
      <v-col cols="9">
        <p class="pt-3 mb-0">
          {{ user.email }}
          <a href="#" v-if="!user.is_active" @click.prevent="sendActiveEmail">
            {{ $t('user.resendActivationEmail') }}
          </a>
        </p>
      </v-col>

      <!-- Password -->
      <v-col cols="3">
        <v-subheader class="pa-0 float-right">{{ $t('user.password') }}</v-subheader>
      </v-col>
      <v-col cols="9">
        <v-subheader class="pa-0">
          <a href="#" @click.stop="show_pass = !show_pass">{{ $t('user.modifyPassword') }}</a>
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
        <v-subheader class="pa-0 float-right">{{ $t('user.nickname') }}</v-subheader>
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

      <!-- VIP Quota -->
      <v-col cols="3" v-if="user.vipquota !== undefined">
        <v-subheader class="pa-0 float-right">VIP配额</v-subheader>
      </v-col>
      <v-col cols="9" v-if="user.vipquota !== undefined">
        <p class="pt-3 mb-0">{{ user.vipquota }}</p>
      </v-col>

      <!-- VIP Expire -->
      <v-col cols="3" v-if="user.vip_expire && user.vip_expire.length > 0">
        <v-subheader class="pa-0 float-right">VIP有效期</v-subheader>
      </v-col>
      <v-col cols="9" v-if="user.vip_expire && user.vip_expire.length > 0">
        <p class="pt-3 mb-0">{{ user.vip_expire }}</p>
      </v-col>

      <!-- Save Button -->
      <v-col cols="12">
        <div class="text-center">
          <v-btn dark large rounded color="orange" type="submit">{{ $t('user.save') }}</v-btn>
        </div>
      </v-col>
    </v-row>
  </v-form>
</template>

<script>
export default {
  data() {
    return {
      user: {
        username: '',
        email: '',
        nickname: '',
        kindle_email: '',
        avatar: null,
        password0: '',
        password1: '',
        password2: '',
        is_active: false,
        vipquota: undefined,
        vip_expire: ''
      },
      show_pass: false,
      rules: {
        pass: v => v === undefined || v.length === 0 || v.length >= 8 || '密码至少 8 位',
        nick: v => v === undefined || v.length === 0 || v.length >= 2 || '昵称至少 2 个字符',
        email: v => {
          const re = /^(([^<>()[\]\\.,;:\s@"]+(\.[^<>()[\]\\.,;:\s@"]+)*)|(".+"))@((\[[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\])|(([a-zA-Z\-0-9]+\.)+[a-zA-Z]{2,}))$/
          return v === undefined || v.length === 0 || re.test(v) || '邮箱格式不正确'
        }
      },
      valid: v => v === this.user.password1 || this.$t('user.passwordMismatch'),
      showAvatarDialog: false,
      avatarImage: null,
      avatarUrl: null,
      isUploading: false,
      cropper: null,
      isCropping: false,
    }
  },
  async asyncData({ app }) {
    return app.$backend('/user/info?detail=1')
  },
  head() {
    return { title: this.$t('user.user_center') }
  },
  created() {
    this.init()
  },
  methods: {
    init() {
      this.$store.commit('navbar', true)
      this.$backend('/user/info?detail=1').then(rsp => {
        rsp.user.password0 = ''
        rsp.user.password1 = ''
        rsp.user.password2 = ''
        this.user = rsp.user
      })
    },
    async onAvatarChange(file) {
      if (!file) {
        this.avatarUrl = null;
        return;
      }

      const { type } = file;
      if (type !== 'image/png' && type !== 'image/jpeg') {
        this.$alert('error', '请上传 PNG 或 JPEG 格式的图片');
        this.avatarUrl = null;
        return;
      }

      if (file.size > 2 * 1024 * 1024) {
        this.$alert('error', '图片大小不能超过2MB');
        this.avatarUrl = null;
        return;
      }

      this.avatarImage = file;
      this.avatarUrl = URL.createObjectURL(file);

      import('cropperjs').then(module => {
        const Cropper = module.default;
        import('cropperjs/dist/cropper.css');

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
                background: false
              });
            } catch (error) {
              console.error('Failed to initialize cropper:', error);
            }
          }
        });
      }).catch(error => {
        console.error('Failed to load cropperjs:', error);
      });
    },

    async uploadAvatar() {
      if (!this.cropper) {
        this.$alert('error', '没有指定新的头像图片');
        return;
      }

      this.isUploading = true;
      this.isCropping = true;

      try {
        await new Promise(resolve => setTimeout(resolve, 300));

        const canvas = this.cropper.getCroppedCanvas({
          width: 96,
          height: 96,
          fillColor: '#fff'
        });

        const blob = await new Promise(resolve =>
          canvas.toBlob(resolve, 'image/png', 0.9)
        );

        if (!blob) {
          throw new Error('裁剪失败，请重试');
        }

        const formData = new FormData();
        formData.append('avatar', blob, 'avatar.png');

        const rsp = await this.$backend('/user/avatar', {
          method: 'POST',
          body: formData
        });

        if (rsp.err === 'ok') {
          this.user.avatar = null
          this.$alert('success', '头像更新成功');
          this.closeAvatarDialog();
          this.user.avatar = `${rsp.avatar_url}?t=${Date.now()}`;
        } else {
          throw new Error(rsp.msg || '头像上传失败');
        }
      } catch (error) {
        this.$alert('error', error.message || '头像上传失败');
      } finally {
        this.isUploading = false;
        this.isCropping = false;
      }
    },
    closeAvatarDialog() {
      this.showAvatarDialog = false
      this.avatarImage = null
      this.avatarUrl = null
      this.isUploading = false
      this.isCropping = false
      if (this.cropper) {
        this.cropper.destroy();
        this.cropper = null;
      }
    },
    save() {
      if (!this.$refs.form.validate()) {
        return false
      }

      const d = {
        password0: this.user.password0,
        password1: this.user.password1,
        password2: this.user.password2,
        nickname: this.user.nickname,
        kindle_email: this.user.kindle_email
      }

      this.$backend('/user/update', {
        method: 'POST',
        body: JSON.stringify(d)
      }).then(rsp => {
        if (rsp.err !== 'ok') {
          this.failmsg = rsp.msg
        } else {
          this.$store.commit('navbar', true)
          this.$router.push('/')
        }
      })
    },
    sendActiveEmail() {
      this.$backend('/user/active/send').then(rsp => {
        if (rsp.err === 'ok') {
          this.$alert('success', this.$t('user.activationEmailSent'))
        } else {
          this.$alert('danger', rsp.msg)
        }
      })
    }
  }
}
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