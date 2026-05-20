<template>
  <div class="wap-page">
    <main class="wap-main">
      <h2 class="wap-site-title">{{ sys.title }}</h2>

      <div v-if="show_login" class="wap-login-form">
        <h3>{{ $t('login.welcome') }}</h3>
        <form @submit.prevent="do_login">
          <div class="form-group">
            <label>{{ $t('login.username') }}</label>
            <input
              type="text"
              v-model="username"
              :placeholder="$t('login.username')"
              required
            />
          </div>
          <div class="form-group">
            <label>{{ $t('login.password') }}</label>
            <input
              type="password"
              v-model="password"
              :placeholder="$t('login.password')"
              required
            />
          </div>
          <div class="form-actions">
            <button type="submit" class="login-btn">{{ $t('login.login') }}</button>
          </div>
          <div class="form-links">
            <a @click="show_login = false">{{ $t('login.forgot_password') }}</a>
          </div>
        </form>

        <div v-if="socials.length > 0" class="social-login">
          <hr />
          <p>{{ $t('login.social_login') }}</p>
          <div class="social-buttons">
            <a
              v-for="s in socials"
              :key="s.value"
              :href="'/auth/login/' + s.value"
              class="social-btn"
            >
              {{ s.text }}
            </a>
          </div>
        </div>
      </div>

      <div v-else class="wap-login-form">
        <h3>{{ $t('login.reset_password') }}</h3>
        <form @submit.prevent="do_reset">
          <div class="form-group">
            <label>{{ $t('login.username') }}</label>
            <input
              type="text"
              v-model="username"
              :placeholder="$t('login.username')"
              required
            />
          </div>
          <div class="form-group">
            <label>{{ $t('login.email') }}</label>
            <input
              type="email"
              v-model="email"
              :placeholder="$t('login.email')"
              required
            />
          </div>
          <div class="form-actions">
            <button type="button" class="back-btn" @click="show_login = true">
              {{ $t('login.back') }}
            </button>
            <button type="submit" class="reset-btn">{{ $t('login.reset') }}</button>
          </div>
        </form>
      </div>

      <div v-if="alert.msg" :class="['alert', alert.type]">
        {{ alert.msg }}
      </div>

      <div class="wap-nav-links">
        <a href="/wap">{{ $t('common.backToHome') }}</a>
      </div>
    </main>
    <wap-footer />
  </div>
</template>

<script>
import WapFooter from '~/components/WapFooter.vue';

export default {
  layout: 'wap',
  components: {
    WapFooter
  },
  data() {
    return {
      username: '',
      password: '',
      email: '',
      show_login: true,
      alert: {
        type: 'error',
        msg: ''
      },
      sys: {}
    };
  },
  head() {
    return { title: this.$t('login.login') };
  },
  computed: {
    socials() {
      if (!this.sys || !this.sys.socials) {
        return [];
      }
      return this.sys.socials;
    }
  },
  async created() {
    // 获取系统信息
    try {
      const rsp = await this.$backend('/user/info');
      if (rsp.err === 'ok') {
        this.sys = rsp.sys || {};
        // 如果已经登录，跳转到 WAP 首页
        if (rsp.user && rsp.user.id) {
          this.$router.push('/wap');
        }
      }
    } catch (e) {
      console.error(e);
    }
  },
  methods: {
    async do_login() {
      const data = new URLSearchParams();
      data.append('username', this.username);
      data.append('password', this.password);

      try {
        const rsp = await this.$backend('/user/sign_in', {
          method: 'POST',
          body: data
        });

        if (rsp.err !== 'ok') {
          this.alert.type = 'error';
          this.alert.msg = rsp.msg;
        } else {
          // 登录成功，更新 store 中的用户信息
          this.$store.commit('login', rsp);
          // 跳转到 WAP 首页
          this.$router.push('/wap');
        }
      } catch (e) {
        this.alert.type = 'error';
        this.alert.msg = '登录失败，请稍后重试';
      }
    },
    async do_reset() {
      const data = new URLSearchParams();
      data.append('username', this.username);
      data.append('email', this.email);

      try {
        const rsp = await this.$backend('/user/reset', {
          method: 'POST',
          body: data
        });

        if (rsp.err === 'ok') {
          this.alert.type = 'success';
          this.alert.msg = '重置成功！请查阅密码通知邮件。';
        } else {
          this.alert.type = 'error';
          this.alert.msg = rsp.msg;
        }
      } catch (e) {
        this.alert.type = 'error';
        this.alert.msg = '重置失败，请稍后重试';
      }
    }
  }
};
</script>

<style scoped>
.wap-page {
  max-width: 1200px;
  margin: 0 auto;
  padding: 16px;
  min-height: 100vh;
}
.wap-site-title {
  text-align: center;
  margin-bottom: 32px;
}
.wap-login-form {
  max-width: 400px;
  margin: 0 auto 32px;
  padding: 24px;
  border: 1px solid #ddd;
  border-radius: 8px;
  background: #fff;
}
.wap-login-form h3 {
  text-align: center;
  margin-bottom: 24px;
}
.form-group {
  margin-bottom: 16px;
}
.form-group label {
  display: block;
  margin-bottom: 4px;
  font-weight: bold;
}
.form-group input {
  width: 100%;
  padding: 8px 12px;
  border: 1px solid #ccc;
  border-radius: 4px;
  font-size: 16px;
  box-sizing: border-box;
}
.form-actions {
  margin-top: 24px;
}
.login-btn, .reset-btn {
  width: 100%;
  padding: 12px;
  background: #003153;
  color: white;
  border: none;
  border-radius: 4px;
  font-size: 16px;
  cursor: pointer;
}
.back-btn {
  width: 100%;
  padding: 12px;
  background: #f0f0f0;
  color: #333;
  border: 1px solid #ccc;
  border-radius: 4px;
  font-size: 16px;
  cursor: pointer;
  margin-bottom: 12px;
}
.form-links {
  text-align: center;
  margin-top: 16px;
}
.form-links a {
  color: #003153;
  text-decoration: underline;
  cursor: pointer;
}
.social-login {
  margin-top: 24px;
  text-align: center;
}
.social-login hr {
  border: none;
  border-top: 1px solid #ddd;
  margin: 16px 0;
}
.social-buttons {
  display: flex;
  gap: 8px;
  justify-content: center;
  flex-wrap: wrap;
  margin-top: 12px;
}
.social-btn {
  padding: 8px 16px;
  border: 1px solid #ccc;
  border-radius: 4px;
  text-decoration: none;
  color: #333;
  background: #f5f5f5;
}
.alert {
  max-width: 400px;
  margin: 16px auto;
  padding: 12px;
  border-radius: 4px;
  text-align: center;
}
.alert.error {
  background: #ffebee;
  color: #c62828;
  border: 1px solid #ef9a9a;
}
.alert.success {
  background: #e8f5e9;
  color: #2e7d32;
  border: 1px solid #a5d6a7;
}
.wap-nav-links {
  text-align: center;
  margin-top: 24px;
}
.wap-nav-links a {
  color: #003153;
  text-decoration: none;
}
</style>
